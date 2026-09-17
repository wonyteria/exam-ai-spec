from __future__ import annotations

from pathlib import Path

from document.models import BBox, Candidate


class StubMathOCRProvider:
    name = "stub-math-ocr"

    def recognize_math(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        return []
