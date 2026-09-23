from __future__ import annotations

from jobs.models import JobState
from . import (
    export_verification,
    preflight,
    preprocessing,
    rendering,
    source_integrity,
)
from .context import PipelineContext
from .correction_stage import run_correction, run_status
from .print_layer import engine as print_layer_engine
from .reconstruction import engine as reconstruction_engine
from .recognition import runner as recognition_runner
from .recognition import segmenter
from .source_truth import consensus
from .stage_contract import StageContract
from .student_trace import separator
from .verification import logic, solving
from .zero_typo_gate import gate


def _preflight(ctx: PipelineContext) -> None:
    """Stage 0: probe capabilities once and pin the report on the ctx —
    every later `requires=` check reads this, not live discovery."""
    report = preflight.run_preflight(ctx.providers)
    preflight.write_report(report, ctx.workdir)
    ctx.capabilities = report
    slots = report.capabilities.get("solver", {}).get("slots", [])
    ctx.emit(
        "capability_preflight",
        "capabilities: "
        + ", ".join(
            f"{k}={'OK' if v.get('available') else 'unavailable'}"
            for k, v in report.capabilities.items()
        ),
    )
    ctx.metric("capability_preflight", "solver_slots", len(slots))


STAGES: list[StageContract] = [
    # --- architecture contracts (Phase 1) --------------------------------
    StageContract(
        "capability_preflight", JobState.PREPROCESSING, _preflight,
    ),
    # --- restoration ------------------------------------------------------
    StageContract(
        "preprocessing", JobState.PREPROCESSING, preprocessing.run,
    ),
    # Page hashing runs right after preprocessing materializes doc.pages
    # (from uploads or the canonical manifest) — before any derived work
    # consumes the bytes. Variant hashes recorded by preprocessing are
    # re-verified here too.
    StageContract(
        "source_integrity", JobState.PREPROCESSING, source_integrity.run,
        produces=("page_hashes_verified",),
    ),
    StageContract(
        "student_trace", JobState.SEPARATING_TRACES, separator.run,
    ),
    StageContract(
        "print_layer", JobState.RESTORING_PRINT, print_layer_engine.run,
    ),
    StageContract(
        "reconstruction", JobState.RESTORING_PRINT,
        reconstruction_engine.run,
    ),
    StageContract(
        "segmentation", JobState.RECOGNIZING, segmenter.run,
    ),
    StageContract(
        "recognition", JobState.RECOGNIZING, recognition_runner.run,
    ),
    # --- verification -----------------------------------------------------
    StageContract(
        "source_verification", JobState.VERIFYING_SOURCE, consensus.run,
        requires=("ocr_audit",),
    ),
    # Deterministic constraint fixes + per-question issue flags — runs on
    # materialized fields before logic/solver verification judges truth.
    StageContract(
        "constraint_correction", JobState.VERIFYING_LOGIC, run_correction,
    ),
    StageContract(
        "logic_verification", JobState.VERIFYING_LOGIC, logic.run,
    ),
    StageContract(
        "solving", JobState.SOLVING, solving.run,
        requires=("solver",),
    ),
    # Final question/document restoration status — after every flag that
    # could still send a question to review has been recorded.
    StageContract(
        "question_status", JobState.SOLVING, run_status,
    ),
    # --- output -----------------------------------------------------------
    StageContract(
        "rendering", JobState.RENDERING, rendering.run,
    ),
    StageContract(
        "export_verification", JobState.VERIFYING_EXPORT,
        export_verification.run,
    ),
    StageContract(
        "zero_typo_gate", JobState.COMPLETED, gate.run,
    ),
]
