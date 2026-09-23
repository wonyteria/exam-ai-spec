from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

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
    # TraceDetectorProvider list — region-level trace candidates for
    # LayerDNA. Optional; empty keeps the heuristic-only path.
    trace: list = field(default_factory=list)


@dataclass
class PipelineContext:
    document: Document
    job: Job
    store: Store
    workdir: Path
    providers: Providers
    objects: Optional[object] = None  # ObjectStore — resolves local:// URIs
    event_sink: Optional[Callable[[str, str, str], None]] = None
    hwp_mismatch: int | None = None
    # Hash-bound artifact proof from export_verification (RESTORE-07).
    artifact_proof: Optional[dict] = None
    # Per-stage measurable counters (removed_px, review regions, …) —
    # flushed into worker_metrics.jsonl by run_pipeline, never an event.
    stage_metrics: dict[str, dict] = field(default_factory=dict)
    # Phase 1 contracts: capability preflight report (set by the
    # capability_preflight stage) and the fail-closed latch — any
    # BLOCKED stage pins the job to NEEDS_REVIEW at best.
    capabilities: Optional[object] = None  # preflight.CapabilityReport
    stage_blocked: bool = False

    def metric(self, stage: str, key: str, value) -> None:
        self.stage_metrics.setdefault(stage, {})[key] = value

    def emit(self, stage: str, message: str, level: str = "info") -> None:
        # WP10: secrets/paths/emails never reach stored job events.
        from core.logscrub import scrub_text

        message = scrub_text(message)
        if self.event_sink is not None:
            self.event_sink(stage, message, level)
        else:
            self.store.emit(self.job, stage, message, level)

    def resolve_uri(self, uri: str) -> Path:
        """Map a stored URI to a readable local path. `local://` keys go
        through the private object store; plain paths (legacy/sample data,
        job-workdir intermediates) pass through unchanged."""
        if uri.startswith("local://"):
            if self.objects is None:
                raise RuntimeError("object store is not configured")
            return self.objects.open(uri)  # type: ignore[union-attr]
        return Path(uri)


StageFn = Callable[[PipelineContext], None]
