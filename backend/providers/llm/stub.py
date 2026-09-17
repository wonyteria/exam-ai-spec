from __future__ import annotations

from typing import Any

from document.models import Candidate


class StubReasoningProvider:
    name = "stub-llm"

    def complete(self, prompt: str, context: dict[str, Any] | None = None) -> Candidate:
        return Candidate(
            provider=self.name,
            value={"reply": "", "applied": False},
            confidence=0.0,
            meta={"stub": True},
        )
