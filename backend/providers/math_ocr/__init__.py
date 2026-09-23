from .stub import StubMathOCRProvider


def get_provider() -> StubMathOCRProvider:
    return StubMathOCRProvider()
