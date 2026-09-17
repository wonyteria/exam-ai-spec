from __future__ import annotations

from document.verification import evaluate_gate
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Final gate: VERIFIED_FINAL only when every counter is zero."""
    report = evaluate_gate(ctx.document, hwp_mismatch=ctx.hwp_mismatch or 0)
    ctx.document.verification.gate = report.model_dump()
    ctx.document.verification.status = (
        "VERIFIED_FINAL" if report.passed else "NEEDS_REVIEW"
    )
    level = "info" if report.passed else "warn"
    ctx.emit(
        "zero_typo_gate",
        f"ZERO TYPO GATE — {'통과' if report.passed else '검토 필요'} {report.model_dump()}",
        level,
    )
