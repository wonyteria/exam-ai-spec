from .stub import StubVisionProvider


def get_provider() -> StubVisionProvider:
    return StubVisionProvider()
