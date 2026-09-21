"""EasyOCR page extractor — second-observer question segmentation.

Shares the column-aware `segment_questions` bridge with the Paddle page
extractor so both engines emit the same item shape; the segmenter treats
matching labels from a second engine as corroborating evidence rather
than duplicate questions.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from document.models import Candidate
from providers.ocr.easyocr_adapter import EasyOCRProvider  # noqa: PLC0415
from .paddle_page import _normalize_bboxes, segment_questions


class EasyOCRPageExtractor:
    name = "easyocr-page"

    def __init__(self, ocr: Optional[Any] = None) -> None:
        self._ocr = ocr or EasyOCRProvider()

    def extract_page(self, image: Path) -> list[Candidate]:
        image = Path(image)
        lines = self._ocr.recognize_text(image)
        items, dropped = segment_questions(lines)
        _normalize_bboxes(items, image)
        input_sha = hashlib.sha256(image.read_bytes()).hexdigest()
        conf = min((it["line_conf"] for it in items), default=0.0)
        return [
            Candidate(
                provider=self.name,
                value=items,
                confidence=conf,
                meta={
                    "model": self._ocr.model,
                    "input_sha256": input_sha,
                    "input_uri": str(image),
                    "kind": "page_extraction",
                    "dropped_lines": dropped,
                },
            )
        ]

    def detect_regions(self, image: Path) -> list[Candidate]:
        return []
