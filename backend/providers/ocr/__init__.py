import os

from .stub import StubOCRProvider


def get_provider():
    """Default OCR provider. Local PaddleOCR is opt-in via
    EXAMDNA_PADDLEOCR=1 — engine loads lazily on first call, so this is
    safe to wire without the package installed."""
    if os.environ.get("EXAMDNA_PADDLEOCR") == "1":
        from .paddle import PaddleOCRProvider

        return PaddleOCRProvider()
    return StubOCRProvider()


def get_providers() -> list:
    """All enabled OCR observers (RESTORE-10C multi-observer).

    EasyOCR is a second, engine-independent observer — opt-in via
    EXAMDNA_EASYOCR=1. Two observers are required before any field can
    auto-verify; a single list element keeps every ATU unverified.
    """
    providers = [get_provider()]
    if os.environ.get("EXAMDNA_EASYOCR") == "1":
        from .easyocr_adapter import EasyOCRProvider

        providers.append(EasyOCRProvider())
    if os.environ.get("EXAMDNA_TESSERACT") == "1":
        from .tesseract import TesseractOCRProvider

        providers.append(TesseractOCRProvider())
    return providers
