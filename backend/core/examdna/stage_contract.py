"""Typed stage contracts (Phase 1 of the restoration architecture).

Every pipeline stage declares what it needs (capabilities) and what it
produces; the runner records a StageRecord per stage with an explicit
status — a stage without its required capability is BLOCKED (never
silently skipped), a crash is FAILED, and uncertainty is NEEDS_REVIEW.
Nothing may reach a later stage by pretending an earlier one succeeded.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class StageStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"      # required capability/tool absent — not an error
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Legal forward transitions for a single stage record. A stage may only
# leave RUNNING via one of the terminal states; nothing goes backwards.
ALLOWED_TRANSITIONS: dict[StageStatus, set[StageStatus]] = {
    StageStatus.PENDING: {StageStatus.RUNNING, StageStatus.BLOCKED, StageStatus.CANCELLED},
    StageStatus.RUNNING: {
        StageStatus.SUCCEEDED,
        StageStatus.NEEDS_REVIEW,
        StageStatus.FAILED,
        StageStatus.BLOCKED,
        StageStatus.CANCELLED,
    },
    StageStatus.SUCCEEDED: set(),
    StageStatus.NEEDS_REVIEW: set(),
    StageStatus.BLOCKED: set(),
    StageStatus.FAILED: set(),
    StageStatus.CANCELLED: set(),
}

TERMINAL = {
    StageStatus.SUCCEEDED,
    StageStatus.NEEDS_REVIEW,
    StageStatus.BLOCKED,
    StageStatus.FAILED,
    StageStatus.CANCELLED,
}


@dataclass
class StageContract:
    """What a stage is allowed to require and expected to produce.

    `requires` names capability keys from the preflight CapabilityReport
    (e.g. "solver", "ocr_audit", "hwp_worker"). When a required
    capability is absent the runner marks the stage BLOCKED and skips
    the function — the absence is evidence, not a silent pass.
    """

    name: str
    job_state: Any                       # jobs.models.JobState
    fn: Callable
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()


@dataclass
class StageRecord:
    """One executed stage: status + evidence + timing. Serialized to
    <job_dir>/stage_records.jsonl by the runner."""

    name: str
    status: StageStatus = StageStatus.PENDING
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    duration_s: Optional[float] = None
    evidence: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def transition(self, to: StageStatus, **evidence) -> None:
        if to not in ALLOWED_TRANSITIONS[self.status]:
            raise RuntimeError(
                f"illegal stage transition {self.status} -> {to} "
                f"(stage {self.name})"
            )
        self.status = to
        if to == StageStatus.RUNNING:
            self.started_at = time.time()
        if to in TERMINAL:
            self.finished_at = time.time()
            if self.started_at is not None:
                self.duration_s = self.finished_at - self.started_at
        if evidence:
            self.evidence.update(evidence)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "evidence": self.evidence,
            "error": self.error,
        }
