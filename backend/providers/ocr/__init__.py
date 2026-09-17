from .stub import StubOCRProvider


def get_provider() -> StubOCRProvider:
    return StubOCRProvider()
