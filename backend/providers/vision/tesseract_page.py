"""Tesseract page extractor — engine-independent observer.

Wraps TesseractOCRProvider (system `tesseract` binary, TSV mode — no
Python package needed) and feeds the shared column-aware
`segment_questions` bridge so items have the same shape as the Paddle
and EasyOCR page extractors. Because Tesseract's LSTM engine is a
different family from the local VLM and PaddleOCR, agreement with
another extractor is real independent evidence for consensus, and
disagreement surfaces as an honest CONFLICT.

Opt-in via EXAMDNA_TESSERACT=1; requires `kor` traineddata
(``tesseract --list-langs``). Local-only — nothing leaves the machine.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from document.models import Candidate
from providers.ocr.tesseract import TesseractOCRProvider  # noqa: PLC0415
from .paddle_page import _normalize_bboxes, segment_questions


class TesseractPageExtractor:
    name = "tesseract-page"

    def __init__(self, ocr: Optional[Any] = None) -> None:
        self._ocr = ocr or TesseractOCRProvider()

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
