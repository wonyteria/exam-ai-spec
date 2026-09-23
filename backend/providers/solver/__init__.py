from .stub import StubMathSolverProvider


def get_provider() -> StubMathSolverProvider:
    return StubMathSolverProvider()
