"""Local VLM page extractor for damaged, photographed exam sheets.

The local Qwen3.5 vision model is used as a *candidate* reader, not as a
verifier.  It transcribes printed question blocks while ignoring handwriting
and returns approximate page bboxes so the normal EvidenceDNA/consensus path
can attach provenance and keep uncertain values out of VERIFIED_FINAL.

This is deliberately separate from the trace detector: one call restores the
printed structure and another call detects student marks.  Both are local-only
and both are cached by the exact input hash.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from document.models import Candidate
from providers.local.provider import _parse_json, _strip_think
from providers.local.trace import _assert_local_base_url

_MAX_SIDE = int(os.environ.get("LOCAL_LLM_PAGE_MAX_SIDE", "1280"))
_MAX_TOKENS = int(os.environ.get("LOCAL_LLM_PAGE_MAX_TOKENS", "5000"))

_PAGE_PROMPT = """당신은 훼손된 한국어 시험지의 인쇄 레이어를 복원하는 OCR/문서 구조화기다.
학생이 손으로 쓴 풀이, 빨간 동그라미, 체크, 밑줄, 채점 표시는 모두 무시하고
인쇄된 시험 내용만 읽어라. 문제를 풀거나 정답을 추론하지 말고 보이는 글자만 전사하라.
페이지의 모든 문항과 논술형 하위 문항을 빠짐없이 반환하라.

JSON만 출력하라. 각 문항의 bbox는 원본 페이지 기준 0~1000 정규화 좌표다.
형식:
{"questions":[
  {"label":"1", "body":"인쇄된 문항 본문", "choices":["선택지1","선택지2"],
   "points":3, "figure":"△ABC, ∠A=40°, AB=12cm",
   "equations":["AB=AC"], "bbox":{"xmin":0,"ymin":0,"xmax":500,"ymax":400}}
]}

규칙:
- label은 인쇄된 번호(예: 1, 2-1, 논술형 2)를 그대로 쓴다.
- choices는 보이는 선택지 순서대로만 쓴다. 없으면 []로 둔다.
- points는 [3점]처럼 보일 때만 숫자로 쓰고, 모르면 null로 둔다.
- figure는 도형이 보일 때만 라벨·점 이름·각도·길이 등 보이는 표기를 나열한다. 없으면 null.
- equations는 본문/선택지의 수식을 보이는 기호 그대로 나열한다. 없으면 [].
- 수식/도형의 의미를 지어내지 말고 본문에 보이는 기호와 숫자를 최대한 보존한다.
- bbox는 해당 문항의 번호부터 마지막 선택지/하위 문항까지를 넉넉히 포함한다.
- 확실하지 않은 문자는 빈 문자열로 두되 문항 자체를 임의로 삭제하지 않는다.
"""

_CHOICE_PREFIX = re.compile(r"^\s*(?:[①-⑩]|\(?\d{1,2}[.)]\)?)[\s:.-]*")


class LocalVisionPageExtractor:
    """One local VLM call per page, returning structured candidates."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        client: Any = None,
    ) -> None:
        self.model = (
            model
            or os.environ.get("LOCAL_LLM_VISION_MODEL")
            or os.environ.get("LOCAL_LLM_MODEL")
            or "local-large"
        )
        if client is not None:
            self._client = client
        else:
            resolved = base_url or os.environ["LOCAL_LLM_BASE_URL"]
            _assert_local_base_url(resolved)
            from openai import OpenAI

            self._client = OpenAI(
                base_url=resolved,
                api_key=os.environ.get("LOCAL_LLM_API_KEY") or "local",
                timeout=float(os.environ.get("LOCAL_LLM_VISION_TIMEOUT", "300")),
                max_retries=0,
            )
        self.name = f"local-vision-page:{self.model}"
        self._cache_dir = Path(
            os.environ.get(
                "LOCAL_LLM_CACHE_DIR",
                Path(__file__).resolve().parents[2] / "data" / "cache" / "local_llm",
            )
        )
        self._cache_on = os.environ.get("LOCAL_LLM_CACHE", "1") != "0"

    def extract_page(self, image: Path) -> list[Candidate]:
        image = Path(image)
        b64, digest = self._encode(image)
        key = hashlib.sha256(
            f"{self.model}\npage-v2\n{digest}".encode()
        ).hexdigest()
        raw = self._cached(key)
        if raw is None:
            raw = self._call(b64)
            if raw and self._cache_on:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                (self._cache_dir / f"{key}.page.json").write_text(raw, encoding="utf-8")
        try:
            data = _parse_json(_strip_think(raw or ""))
        except (json.JSONDecodeError, TypeError):
            data = None
        items = _normalize_items(data)
        return [
            Candidate(
                provider=self.name,
                value=items,
                confidence=_confidence(items),
                model_version=self.model,
                raw_output_sha256=hashlib.sha256((raw or "").encode()).hexdigest(),
                timestamp=time.time(),
                meta={
                    "model": self.model,
                    "input_sha256": digest,
                    "input_uri": str(image),
                    "kind": "page_extraction",
                    "candidate_only": True,
                    "item_count": len(items),
                },
            )
        ]

    def detect_regions(self, image: Path) -> list[Candidate]:
        return []

    def _encode(self, image: Path) -> tuple[str, str]:
        from PIL import Image

        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        with Image.open(image) as source:
            im = source.convert("RGB")
            im.thumbnail((_MAX_SIDE, _MAX_SIDE))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=88)
        return base64.b64encode(buf.getvalue()).decode(), digest

    def _cached(self, key: str) -> Optional[str]:
        if not self._cache_on:
            return None
        path = self._cache_dir / f"{key}.page.json"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def _call(self, b64: str) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PAGE_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": _MAX_TOKENS,
        }
        if os.environ.get("LOCAL_LLM_DISABLE_THINKING") == "1":
            kwargs["extra_body"] = {"think": False}
        return self._client.chat.completions.create(**kwargs).choices[0].message.content or ""


def _normalize_items(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        return []
    out: list[dict[str, Any]] = []
    for raw in data["questions"]:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        body = str(raw.get("body") or "").strip()
        if not label or not body:
            continue
        item: dict[str, Any] = {"label": label, "body": body}
        choices = raw.get("choices")
        if isinstance(choices, list):
            normalized_choices = []
            for value in choices:
                text = str(value).strip()
                # VLMs sometimes include the printed choice marker even
                # though the schema already stores choices by position.
                # Strip only a leading marker; mathematical content stays
                # untouched.
                while (match := _CHOICE_PREFIX.match(text)):
                    text = text[match.end():].strip()
                if text:
                    normalized_choices.append(text)
            item["choices"] = normalized_choices
        points = raw.get("points")
        if isinstance(points, int) and 0 < points < 100:
            item["points"] = points
        figure = raw.get("figure")
        if isinstance(figure, str) and figure.strip():
            item["figure"] = figure.strip()
        equations = raw.get("equations")
        if isinstance(equations, list):
            eqs = [str(e).strip() for e in equations if str(e).strip()]
            if eqs:
                item["equations"] = eqs
        bbox = _normalize_bbox(raw.get("bbox"))
        if bbox is not None:
            item["bbox"] = bbox
        out.append(item)
    return out


def _normalize_bbox(value: Any) -> Optional[dict[str, float]]:
    if not isinstance(value, dict):
        return None
    try:
        vals = {k: float(value[k]) for k in ("xmin", "ymin", "xmax", "ymax")}
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= vals["xmin"] < vals["xmax"] <= 1000 and 0 <= vals["ymin"] < vals["ymax"] <= 1000):
        return None
    return vals


def _confidence(items: list[dict[str, Any]]) -> float:
    if not items:
        return 0.0
    with_bbox = sum(1 for item in items if item.get("bbox"))
    return round(0.7 + 0.2 * (with_bbox / len(items)), 3)
