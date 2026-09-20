from __future__ import annotations

import json

from document.review import build_review_package
from document.verification import evaluate_gate
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Final gate: VERIFIED_FINAL only when every counter is zero."""
    proof_status = (ctx.artifact_proof or {}).get("status", "NOT_RUN")
    report = evaluate_gate(
        ctx.document,
        hwp_mismatch=ctx.hwp_mismatch or 0,
        artifact_proof=proof_status,
    )
    ctx.document.verification.gate = report.model_dump()
    ctx.document.verification.status = (
        "VERIFIED_FINAL" if report.passed else "NEEDS_REVIEW"
    )
    # RESTORE-03: persist the review package — page roles, per-question
    # source crops + anchors, and pending ATU counts — next to the job's
    # other artifacts so the review UI can render evidence, not guesses.
    try:
        pkg = build_review_package(
            ctx.document, workdir=ctx.workdir, resolve_uri=ctx.resolve_uri
        )
        out = ctx.workdir / "review_package.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
        ctx.emit(
            "zero_typo_gate",
            f"검수 패키지 기록 — 문항 {pkg['review']['question_count']}개, "
            f"미해결 {pkg['review']['pending_count']}개, "
            f"불확실 영역 {pkg['review']['uncertain_region_count']}개",
        )
    except Exception as exc:  # noqa: BLE001 — packaging must never mask the gate
        ctx.emit("zero_typo_gate", f"검수 패키지 기록 실패: {exc}", "warn")
    level = "info" if report.passed else "warn"
    ctx.emit(
        "zero_typo_gate",
        f"ZERO TYPO GATE — {'통과' if report.passed else '검토 필요'} {report.model_dump()}",
        level,
    )
