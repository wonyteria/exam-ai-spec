from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image

from document.models import BBox, Candidate

_REGION_PROMPT = """이 이미지는 학생이 풀고 채점한 시험지 페이지입니다.
각 문제(문항)가 차지하는 영역을 찾아 JSON 배열로만 답하세요.
[{"number": 문항번호(정수), "ymin": 0-1000, "xmin": 0-1000, "ymax": 0-1000, "xmax": 0-1000}]
좌표는 이미지 전체를 1000x1000으로 정규화한 값입니다. 문항이 없으면 []를 답하세요."""

_EXTRACT_PROMPT = """이 이미지는 시험지의 한 문항 영역입니다. 인쇄된 문제 내용만 구조화해서 JSON으로만 답하세요.
학생 필기·채점 표시(동그라미, 밑줄, 풀이 메모)는 절대 포함하지 마세요.
{
 "number": 문항번호(정수),
 "type": "multiple_choice" | "subjective" | "descriptive",
 "points": 배점(정수, 없으면 null),
 "body": "문제 본문 텍스트(수식 위치는 $...$ LaTeX로 인라인)",
 "choices": {"①": "보기내용", "②": "...", ...} (객관식만, 아니면 {}),
 "equations": ["별도 수식 블록 LaTeX", ...] (없으면 [])
}
읽기 어려운 부분은 추측하지 말고 해당 필드를 null로 두세요."""

_SOLVE_PROMPT = """다음은 복원된 중학교 수학 문제입니다. 실제로 풀어서 JSON으로만 답하세요.
{"solved": true|false, "answer": 정답(객관식이면 기호, 아니면 값), "steps": ["풀이 단계1", ...], "reason": "풀 수 없으면 이유"}
문제 조건이 불완전하거나 모순이면 solved=false로 두세요."""


class GeminiProvider:
    """Gemini-backed provider covering vision/ocr/math-ocr/llm/solver roles."""

    name = "gemini"

    def __init__(self, model: str | None = None):
        from google import genai

        self._client = genai.Client()
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    def detect_regions(self, image: Path) -> list[Candidate]:
        data = self._generate_json([_image_part(image)], _REGION_PROMPT)
        if not isinstance(data, list):
            return []
        return [
            Candidate(
                provider=self.name,
                confidence=0.9,
                value={
                    "number": int(item.get("number", i + 1)),
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
        data = self._generate_json([part], _EXTRACT_PROMPT)
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

    def complete(self, prompt: str, context: dict[str, Any] | None = None) -> Candidate:
        text = self._generate_text([json.dumps(context or {}, ensure_ascii=False), prompt])
        return Candidate(provider=self.name, value={"reply": text}, confidence=0.8)

    def solve(self, problem: dict[str, Any]) -> Candidate:
        prompt = _SOLVE_PROMPT + "\n\n문제:\n" + json.dumps(problem, ensure_ascii=False)
        data = self._generate_json([prompt])
        if not isinstance(data, dict):
            return Candidate(provider=self.name, value={"solved": False, "answer": None}, confidence=0.0)
        return Candidate(provider=self.name, value=data, confidence=0.85)

    def _generate_json(self, parts: list[Any], prompt: str | None = None) -> Any:
        from google.genai import types

        contents = [*parts, prompt] if prompt else parts
        resp = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return json.loads(resp.text)

    def _generate_text(self, parts: list[Any]) -> str:
        resp = self._client.models.generate_content(model=self.model, contents=parts)
        return resp.text


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
