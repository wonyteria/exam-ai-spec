"""Deterministic replay/mock providers for offline tests and dev runs.

These never touch the network or models — they return pre-recorded
Candidates so pipeline behavior can be tested without SDK keys or model
weights. Results are candidates only; consensus still decides truth.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from document.models import BBox, Candidate


class MockOCRProvider:
    """Replays canned text lines, optionally filtered by region."""

    name = "mock-ocr"

    def __init__(self, lines: Optional[list[dict]] = None):
        # each line: {"text": str, "confidence": float, "bbox": [x0,y0,x1,y1]}
        self.lines = lines or []

    def recognize_text(
        self, image: Path, region: BBox | None = None
    ) -> list[Candidate]:
        return [
            Candidate(
                provider=self.name,
                value=l["text"],
                confidence=l.get("confidence", 0.9),
                meta={"bbox_px": l.get("bbox"), "kind": "ocr_line", "mock": True},
            )
            for l in self.lines
        ]


class MockVisionProvider:
    """Replays canned page extraction items (label + normalized bbox +
    fields) — mimics a provider's extract_page contract."""

    name = "mock-vision"

    def __init__(
        self,
        items: Optional[list[dict]] = None,
        per_page: Optional[dict[int, list[dict]]] = None,
    ):
        self.items = items or []
        self.per_page = per_page or {}
        self._calls = 0

    def extract_page(self, image: Path) -> list[Candidate]:
        idx = self._calls
        self._calls += 1
        items = self.per_page.get(idx, self.items)
        return [
            Candidate(
                provider=self.name,
                value=list(items),
                confidence=0.9,
                meta={"structured_page": True, "mock": True},
            )
        ]

    def detect_regions(self, image: Path) -> list[Candidate]:
        return [
            Candidate(
                provider=self.name,
                value=dict(i),
                confidence=0.9,
                meta={"mock": True},
            )
            for i in self.items
        ]

    def describe(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        return []


class MockMathOCRProvider:
    name = "mock-math-ocr"

    def __init__(self, equations: Optional[list[str]] = None):
        self.equations = equations or []

    def recognize_math(
        self, image: Path, region: BBox | None = None
    ) -> list[Candidate]:
        return [
            Candidate(
                provider=self.name,
                value=eq,
                confidence=0.9,
                meta={"atu_kind": "math_symbol", "mock": True},
            )
            for eq in self.equations
        ]


class MockSolverProvider:
    """Deterministic solver — maps problem text to a canned answer via a
    lookup callable, or a fixed answer for every problem."""

    name = "mock-solver"

    def __init__(
        self,
        answer: Any = "3",
        fn: Optional[Callable[[dict], Any]] = None,
    ):
        self.answer = answer
        self.fn = fn

    def solve(self, problem: dict[str, Any]) -> Candidate:
        value = self.fn(problem) if self.fn else self.answer
        return Candidate(provider=self.name, value={"answer": value}, confidence=0.9)
