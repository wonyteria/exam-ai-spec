import os

from .stub import StubVisionProvider


def get_provider():
    """Default vision/layout provider. Local PP-Structure layout is
    opt-in via EXAMDNA_PADDLE_LAYOUT=1 — lazy engine, safe without the
    package installed."""
    if os.environ.get("EXAMDNA_PADDLE_LAYOUT") == "1":
        from .paddle import PaddleLayoutProvider

        return PaddleLayoutProvider()
    return StubVisionProvider()


def get_page_extractor():
    """Structured page extraction provider — line-OCR → question blocks.

    Opt-in via EXAMDNA_PADDLE_PAGE=1; shares the PaddleOCR engine. None
    when disabled — callers must not treat absence as an error."""
    if os.environ.get("EXAMDNA_PADDLE_PAGE") == "1":
        from .paddle_page import PaddlePageExtractor

        return PaddlePageExtractor()
    return None


def get_page_extractors() -> list:
    """All enabled page extractors — one per independent OCR engine.

    The segmenter treats identical labels from a second engine as
    corroboration; engines are opt-in and absent by default.
    """
    extractors = []
    if os.environ.get("EXAMDNA_PADDLE_PAGE") == "1":
        from .paddle_page import PaddlePageExtractor

        extractors.append(PaddlePageExtractor())
    if os.environ.get("EXAMDNA_EASYOCR") == "1":
        from .easyocr_page import EasyOCRPageExtractor

        extractors.append(EasyOCRPageExtractor())
    return extractors
