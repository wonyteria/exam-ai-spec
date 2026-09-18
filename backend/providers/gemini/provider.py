from __future__ import annotations

import hashlib
import io
import json
import os
import random
import re
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image

from document.models import BBox, Candidate

MAX_RETRIES = 8
_RETRYABLE = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "500")
MIN_INTERVAL = float(os.environ.get("GEMINI_MIN_INTERVAL", "4.0"))
_rate_lock = threading.Lock()
_last_call = 0.0

CACHE_DIR = Path(
    os.environ.get(
        "GEMINI_CACHE_DIR",
        Path(__file__).resolve().parents[2] / "data" / "cache" / "gemini",
    )
)
CACHE_ENABLED = os.environ.get("GEMINI_CACHE", "1") != "0"


class DailyQuotaExhausted(RuntimeError):
    pass


def _cache_key(model: str, contents: list[Any]) -> str:
    h = hashlib.sha256(model.encode())
    for c in contents:
        if isinstance(c, str):
            h.update(c.encode())
            continue
        data = getattr(getattr(c, "inline_data", None), "data", None)
        h.update(data if isinstance(data, bytes) else repr(c).encode())
    return h.hexdigest()


def _cache_get(key: str) -> str | None:
    if not CACHE_ENABLED:
        return None
    path = CACHE_DIR / f"{key}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else None


def _cache_put(key: str, text: str) -> None:
    if not CACHE_ENABLED or not text:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.txt").write_text(text, encoding="utf-8")


def _pace() -> None:
    """Keep request rate under the free-tier per-minute quota."""
    global _last_call
    with _rate_lock:
        gap = time.time() - _last_call
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        _last_call = time.time()


def _server_retry_after(exc: Exception) -> float | None:
    m = re.search(r"retry in ([\d.]+)\s*s", str(exc))
    return float(m.group(1)) + 1.0 if m else None

_REGION_PROMPT = """이 이미지는 학생이 풀고 채점한 시험지 페이지입니다.
각 문제(문항)가 차지하는 영역을 찾아 JSON 배열로만 답하세요.
[{"label": "인쇄된 문항 표기(예: 6, 논술형 2, 2-1)", "ymin": 0-1000, "xmin": 0-1000, "ymax": 0-1000, "xmax": 0-1000}]
좌표는 이미지 전체를 1000x1000으로 정규화한 값입니다. 문항이 없으면 []를 답하세요.
서술형 답안 공간(빈칸)은 문항이 아니면 제외하세요."""

_EXTRACT_PROMPT = """이 이미지는 시험지의 한 문항 영역입니다. 인쇄된 문제 내용만 구조화해서 JSON으로만 답하세요.
학생 필기·채점 표시(동그라미, 밑줄, 풀이 메모)는 절대 포함하지 마세요.
{
 "number": "인쇄된 문항 번호(예: 6 또는 논술형 2-1)",
 "type": "multiple_choice" | "subjective" | "descriptive",
 "points": 배점(정수, 없으면 null),
 "body": "문제 본문 텍스트(수식 위치는 $...$ LaTeX로 인라인)",
 "choices": {"①": "보기내용", "②": "...", ...} (객관식만, 아니면 {}),
 "equations": ["별도 수식 블록 LaTeX", ...] (없으면 []),
 "figure": "도형·그림이 있으면 문제 풀이에 필요한 정보를 글로 설명(점 이름, 길이, 각도, 관계). 없으면 null"
}
읽기 어려운 부분은 추측하지 말고 해당 필드를 null로 두세요."""

_SOLVE_PROMPT = """다음은 복원된 중학교 수학 문제입니다. 실제로 풀어서 JSON으로만 답하세요.
{"solved": true|false, "answer": 정답(객관식이면 기호, 아니면 값), "steps": ["풀이 단계1", ...], "reason": "풀 수 없으면 이유"}
문제 조건이 불완전하거나 모순이면 solved=false로 두세요."""

_PAGE_PROMPT = """이 이미지는 학생이 풀고 채점한 시험지 한 페이지입니다.
인쇄된 모든 문항을 찾아 JSON 배열로만 답하세요. 학생 필기·채점 표시는 절대 포함하지 마세요.
[{
 "label": "인쇄된 문항 표기(예: 6, 논술형 2, 2-1)",
 "bbox": {"ymin": 0-1000, "xmin": 0-1000, "ymax": 0-1000, "xmax": 0-1000},
 "type": "multiple_choice" | "subjective" | "descriptive",
 "points": 배점(정수, 없으면 null),
 "body": "문제 본문 텍스트(수식은 $...$ LaTeX 인라인)",
 "choices": {"①": "보기내용", ...} (객관식만, 아니면 {}),
 "equations": ["별도 수식 블록 LaTeX", ...],
 "figure": "도형이 있으면 풀이에 필요한 정보를 글로 설명. 없으면 null"
}]
좌표는 페이지를 1000x1000으로 정규화한 값입니다. 읽기 어려운 부분은 추측하지 말고 null로 두세요."""

_SOLVE_BATCH_PROMPT = """다음은 복원된 중학교 수학 문제들입니다. 각각 실제로 풀어서 JSON 배열로만 답하세요.
[{"number": 문항 표기, "solved": true|false, "answer": 정답(객관식이면 기호, 아니면 값), "steps": ["단계1", ...], "reason": "풀 수 없으면 이유"}]
shared_stem이 있으면 공통 지문입니다. 조건이 불완전하거나 모순이면 solved=false로 두세요."""

_EDIT_PROMPT = """복원된 시험지 문서와 사용자의 수정 지시가 주어집니다.
지시를 문서 수정 연산 목록으로 변환해 JSON 배열로만 답하세요.
[{"question": "문항 표기(예: 13, 논술형 2, 2-1)", "field": "body|choice|points|answer|type|equation|figure",
  "choice": "선택지 기호(choice일 때)", "index": 수식 번호(equation일 때), "value": 새 값}]
지시가 모호하거나 문서에 없는 문항이면 그 연산은 만들지 마세요. 수정할 게 없으면 []를 답하세요."""


class GeminiProvider:
    """Gemini-backed provider covering vision/ocr/math-ocr/llm/solver roles."""

    name = "gemini"

    def __init__(self, model: str | None = None):
        from google import genai

        self._client = genai.Client()
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
        self.quota_exhausted = False

    def extract_page(self, image: Path) -> list[Candidate]:
        """One call per page: regions AND structured extraction together.

        Returns a single structured Candidate holding the question list;
        segmentation and recognition both consume it (second use = cache hit).
        """
        try:
            data = self._generate_json([_image_part(image)], _PAGE_PROMPT)
        except (json.JSONDecodeError, DailyQuotaExhausted):
            return []
        if not isinstance(data, list):
            return []
        return [
            Candidate(provider=self.name, value=data, confidence=0.9, meta={"page_extract": True})
        ]

    def solve_batch(self, problems: list[dict[str, Any]], run: int = 0) -> list[Candidate]:
        """Solve many questions in one call; returns one Candidate with the
        per-question result list. `run` varies the prompt so consensus runs
        are real calls, not cache hits."""
        prompt = _SOLVE_BATCH_PROMPT + "\n\n문제들:\n" + json.dumps(problems, ensure_ascii=False)
        if run:
            prompt += f"\n\n(독립 검증 {run + 1}회차)"
        try:
            data = self._generate_json([prompt])
        except (json.JSONDecodeError, DailyQuotaExhausted):
            data = None
        if not isinstance(data, list):
            return [Candidate(provider=self.name, value=[], confidence=0.0)]
        return [Candidate(provider=self.name, value=data, confidence=0.85)]

    def detect_regions(self, image: Path) -> list[Candidate]:
        try:
            data = self._generate_json([_image_part(image)], _REGION_PROMPT)
        except (json.JSONDecodeError, DailyQuotaExhausted):
            return []
        if not isinstance(data, list):
            return []
        return [
            Candidate(
                provider=self.name,
                confidence=0.9,
                value={
                    "label": str(item.get("label", i + 1)),
                    "bbox": {
                        "ymin": float(item["ymin"]),
                        "xmin": float(item["xmin"]),
                        "ymax": float(item["ymax"]),
                        "xmax": float(item["xmax"]),
                    },
                },
            )
            for i, item in enumerate(data)
            if isinstance(item, dict)
        ]

    def recognize_text(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        part = _image_part(image, region)
        try:
            data = self._generate_json([part], _EXTRACT_PROMPT)
        except (json.JSONDecodeError, DailyQuotaExhausted):
            return []
        if not isinstance(data, dict):
            return []
        return [
            Candidate(
                provider=self.name,
                value=data,
                confidence=0.9,
                meta={"structured": True},
            )
        ]

    def recognize_math(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        return []

    def describe(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        return []

    def edit_ops(self, summary: list[dict], instruction: str) -> list[dict]:
        """Natural-language edit -> structured ops (applied by core.editing)."""
        prompt = (
            _EDIT_PROMPT
            + "\n\n문서:\n"
            + json.dumps(summary, ensure_ascii=False)
            + "\n\n지시:\n"
            + instruction
        )
        try:
            data = self._generate_json([prompt])
        except (json.JSONDecodeError, DailyQuotaExhausted):
            return []
        return data if isinstance(data, list) else []

    def complete(self, prompt: str, context: dict[str, Any] | None = None) -> Candidate:
        text = self._generate_text([json.dumps(context or {}, ensure_ascii=False), prompt])
        return Candidate(provider=self.name, value={"reply": text}, confidence=0.8)

    def solve(self, problem: dict[str, Any], run: int = 0) -> Candidate:
        prompt = _SOLVE_PROMPT + "\n\n문제:\n" + json.dumps(problem, ensure_ascii=False)
        if run:
            prompt += f"\n\n(독립 검증 {run + 1}회차)"
        try:
            data = self._generate_json([prompt])
        except (json.JSONDecodeError, DailyQuotaExhausted):
            data = None
        if not isinstance(data, dict):
            return Candidate(provider=self.name, value={"solved": False, "answer": None}, confidence=0.0)
        return Candidate(provider=self.name, value=data, confidence=0.85)

    def _generate_json(self, parts: list[Any], prompt: str | None = None) -> Any:
        from google.genai import types

        contents = [*parts, prompt] if prompt else parts
        resp = self._call(
            contents,
            self._config(
                types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0,
                    max_output_tokens=32768,
                )
            ),
        )
        return _parse_json(resp.text)

    def _generate_text(self, parts: list[Any]) -> str:
        from google.genai import types

        return self._call(parts, self._config(types.GenerateContentConfig())).text

    @staticmethod
    def _config(config):
        from google.genai import types

        config.automatic_function_calling = types.AutomaticFunctionCallingConfig(
            disable=True
        )
        return config

    def _call(self, contents: list[Any], config):
        if self.quota_exhausted:
            raise DailyQuotaExhausted(self.model)
        key = _cache_key(self.model, contents)
        if (cached := _cache_get(key)) is not None:
            return _CachedResponse(cached)
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            _pace()
            try:
                resp = self._client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                _cache_put(key, resp.text or "")
                return resp
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if "PerDay" in str(exc) or "PerProjectPerDay" in str(exc):
                    self.quota_exhausted = True
                    raise DailyQuotaExhausted(self.model) from exc
                if not any(tag in str(exc) for tag in _RETRYABLE):
                    raise
                wait = _server_retry_after(exc) or (
                    min(2**attempt * 2, 60) + random.uniform(0, 2)
                )
                time.sleep(wait)
        raise last_exc


class _CachedResponse:
    """Mimics the SDK response surface used by this provider (.text)."""

    def __init__(self, text: str):
        self.text = text


def _parse_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    for candidate in (cleaned, _escape_latex(cleaned)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    value, _ = decoder.raw_decode(cleaned)
    return value


def _escape_latex(text: str) -> str:
    """Models emit raw LaTeX like \\angle inside JSON strings."""
    return re.sub(r'\\(?![\\"/bfnrtu])', r"\\\\", text)


def _image_part(image: Path, region: BBox | None = None):
    from google.genai import types

    with Image.open(image) as im:
        base = im.convert("RGB")
        if region is not None:
            base = base.crop(
                (
                    int(region.x),
                    int(region.y),
                    int(region.x + region.w),
                    int(region.y + region.h),
                )
            )
        buf = io.BytesIO()
        base.save(buf, "PNG")
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png")
