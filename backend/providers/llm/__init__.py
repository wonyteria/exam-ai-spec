from .stub import StubReasoningProvider


def get_provider() -> StubReasoningProvider:
    return StubReasoningProvider()
