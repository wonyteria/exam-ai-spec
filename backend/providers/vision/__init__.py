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
    # Local Qwen3.5 vision is the fallback that works on Apple Silicon when
    # PaddleOCR/EasyOCR are unavailable. It is candidate-only; consensus and
    # the final gate still decide whether anything is verified.
    if os.environ.get("EXAMDNA_ENABLE_LOCAL_PAGE_RESTORE") == "1":
        from providers.local.page import LocalVisionPageExtractor

        extractors.append(LocalVisionPageExtractor())
    # Tesseract is a different engine family (LSTM, not a VLM) — a real
    # independent observer for consensus, not a correlated re-read.
    if os.environ.get("EXAMDNA_TESSERACT") == "1":
        from .tesseract_page import TesseractPageExtractor

        extractors.append(TesseractPageExtractor())
    return extractors
