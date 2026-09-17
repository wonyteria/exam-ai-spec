from __future__ import annotations

from typing import Any

from document.models import Candidate


class StubMathSolverProvider:
    name = "stub-solver"

    def solve(self, problem: dict[str, Any]) -> Candidate:
        return Candidate(
            provider=self.name,
            value={"solved": False, "answer": None},
            confidence=0.0,
            meta={"stub": True},
        )
