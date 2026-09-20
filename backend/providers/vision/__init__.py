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
