"""Pipeline stages for question-centric restoration.

`constraint_correction` runs right after source_verification materializes
ATUs into fields: deterministic fixes are applied to the fields and every
unresolved item is recorded as a FieldIssue — never auto-confirmed.

`question_status` runs after solving: logic flags and solver evidence are
now final, so per-question and per-document restoration status is
recomputed here.
"""
from __future__ import annotations

from document.models import QuestionStatus
from document.restoration import (
    refresh_document_status,
    refresh_question_status,
)

from .context import PipelineContext
from .correction import (
    handwriting_overlap_issue,
    renumber_duplicate_subnumbers,
    run_corrections,
)


def run_correction(ctx: PipelineContext) -> None:
    fixed = 0
    for q in ctx.document.questions:
        before = len(q.restoration.corrections)
        run_corrections(q)
        fixed += len(q.restoration.corrections) - before
        overlap = handwriting_overlap_issue(ctx.document, q)
        if overlap and not any(
            i.reason == overlap.reason for i in q.restoration.issues
        ):
            q.restoration.issues.append(overlap)
    renumber_duplicate_subnumbers(ctx.document)
    _refresh_all(ctx)
    counts = _counts(ctx)
    ctx.emit(
        "constraint_correction",
        f"제약 교정 — 자동 교정 {fixed}건 · "
        f"검토 필요 {counts.get(QuestionStatus.NEEDS_USER_REVIEW.value, 0)}문항",
    )


def run_status(ctx: PipelineContext) -> None:
    _refresh_all(ctx)
    counts = _counts(ctx)
    total = counts.get("total", 0)
    ctx.emit(
        "question_status",
        "문항 상태 — "
        f"자동 복원 {counts.get(QuestionStatus.AUTO_RESTORED.value, 0)} · "
        f"자동 교정 {counts.get(QuestionStatus.AUTO_CORRECTED.value, 0)} · "
        f"검토 필요 {counts.get(QuestionStatus.NEEDS_USER_REVIEW.value, 0)} · "
        f"복원 불가 {counts.get(QuestionStatus.BLOCKED.value, 0)} / {total}",
    )
    ctx.metric("question_status", "counts", counts)


def _refresh_all(ctx: PipelineContext) -> None:
    for q in ctx.document.questions:
        refresh_question_status(q)
    refresh_document_status(ctx.document)


def _counts(ctx: PipelineContext) -> dict[str, int]:
    counts: dict[str, int] = {}
    for q in ctx.document.questions:
        key = q.restoration.status.value
        counts[key] = counts.get(key, 0) + 1
    counts["total"] = len(ctx.document.questions)
    return counts
