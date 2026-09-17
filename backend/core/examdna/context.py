from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from document.models import Document
from jobs.models import Job
from jobs.store import Store
from providers.base import (
    MathOCRProvider,
    MathSolverProvider,
    OCRProvider,
    ReasoningProvider,
    VisionProvider,
)


@dataclass
class Providers:
    ocr: list[OCRProvider] = field(default_factory=list)
    vision: list[VisionProvider] = field(default_factory=list)
    math_ocr: list[MathOCRProvider] = field(default_factory=list)
    reasoning: list[ReasoningProvider] = field(default_factory=list)
    solver: list[MathSolverProvider] = field(default_factory=list)


@dataclass
class PipelineContext:
    document: Document
    job: Job
    store: Store
    workdir: Path
    providers: Providers
    hwp_mismatch: int | None = None

    def emit(self, stage: str, message: str, level: str = "info") -> None:
        self.store.emit(self.job, stage, message, level)


StageFn = Callable[[PipelineContext], None]
