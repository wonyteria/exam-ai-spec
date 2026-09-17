from __future__ import annotations

from pathlib import Path

from document.models import BBox, Candidate


class StubVisionProvider:
    name = "stub-vision"

    def detect_regions(self, image: Path) -> list[Candidate]:
        return []

    def describe(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        return []
