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
