"""Model routing for the local OpenAI-compatible server.

  local-large — ordinary questions, formulas, figures (default)
  local-long  — long-context / descriptive (논술·서술) questions only
  local-small — auxiliary only; NEVER a solver slot

Routing is per-problem: a descriptive question goes to local-long, every
other to local-large. Each inner provider keeps its own name, so
Candidates keep honest model identity (no shared-source masquerading).
Caching is inherited from LocalLLMProvider (model+prompt hash).
"""
from __future__ import annotations

import os
from typing import Any

from document.models import Candidate

_LONG_BODY_CHARS = int(os.environ.get("LOCAL_LLM_LONG_MIN_CHARS", "400"))


def _is_long(problem: dict[str, Any]) -> bool:
    label = str(problem.get("label") or problem.get("number") or "")
    qtype = str(problem.get("type") or "")
    body = str(problem.get("body") or "")
    return (
        "서술" in label
        or "논술" in label
        or qtype in ("descriptive", "서술형", "논술형")
        or len(body) > _LONG_BODY_CHARS
    )


class LocalLLMRouter:
    """Solver/reasoning role facade routing problems between two local
    providers. `local-small` is never constructed here."""

    name = "local-llm"

    def __init__(self, large, long_model=None):
        self.large = large
        self.long = long_model or large

    @property
    def model(self) -> str:
        """Primary model identity — local-large is the default route."""
        return self.large.model

    def _pick(self, problem: dict[str, Any]):
        return self.long if _is_long(problem) else self.large

    def solve(self, problem: dict[str, Any], run: int = 0) -> Candidate:
        provider = self._pick(problem)
        cand = provider.solve(problem, run=run)
        cand.meta = dict(cand.meta or {})
        cand.meta["routed_model"] = provider.model
        return cand

    def solve_batch(
        self, problems: list[dict[str, Any]], run: int = 0
    ) -> list[Candidate]:
        """Split the batch by route so each model sees only its own
        problems — one Candidate per model keeps evidence sources
        honest (local-large and local-long are different sources)."""
        by_provider: dict[int, tuple[Any, list[dict[str, Any]]]] = {}
        for p in problems:
            provider = self._pick(p)
            key = id(provider)
            if key not in by_provider:
                by_provider[key] = (provider, [])
            by_provider[key][1].append(p)
        out: list[Candidate] = []
        for provider, subset in by_provider.values():
            for cand in provider.solve_batch(subset, run=run):
                cand.meta = dict(cand.meta or {})
                cand.meta["routed_model"] = provider.model
                out.append(cand)
        return out

    def complete(
        self, prompt: str, context: dict[str, Any] | None = None
    ) -> Candidate:
        # Rewrites / cleanups go to local-large; a huge context window
        # (whole descriptive stem + marks) can opt into local-long.
        provider = self.large
        if context and _is_long(context):
            provider = self.long
        return provider.complete(prompt, context=context)

    def edit_ops(self, summary: dict, instruction: str):
        provider = self.large
        if not hasattr(provider, "edit_ops"):
            return []
        return provider.edit_ops(summary, instruction)
