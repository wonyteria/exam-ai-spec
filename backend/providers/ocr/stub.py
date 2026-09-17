from __future__ import annotations

from pathlib import Path

from document.models import BBox, Candidate


class StubOCRProvider:
    """No-op provider. Real OCR providers plug in behind the same interface."""

    name = "stub-ocr"

    def recognize_text(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        return []
