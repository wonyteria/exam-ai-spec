from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from document.models import BBox, Candidate


class OCRProvider(Protocol):
    name: str

    def recognize_text(self, image: Path, region: BBox | None = None) -> list[Candidate]: ...


class VisionProvider(Protocol):
    name: str

    def detect_regions(self, image: Path) -> list[Candidate]: ...

    def describe(self, image: Path, region: BBox | None = None) -> list[Candidate]: ...


class MathOCRProvider(Protocol):
    name: str

    def recognize_math(self, image: Path, region: BBox | None = None) -> list[Candidate]: ...


class ReasoningProvider(Protocol):
    name: str

    def complete(self, prompt: str, context: dict[str, Any] | None = None) -> Candidate: ...


class MathSolverProvider(Protocol):
    name: str

    def solve(self, problem: dict[str, Any]) -> Candidate: ...


class TraceDetectorProvider(Protocol):
    """Student-trace region detector (LayerDNA candidate source).

    Returns one Candidate whose value is
    `{"traces": [{"x","y","w","h","kind"}]}` on a normalized 0-1000 grid —
    a region-level claim, never a pixel mask. ExamDNA applies its own
    pixel policy inside each box.
    """

    name: str

    def detect_traces(self, image: Path) -> Candidate: ...
