from __future__ import annotations

from document.models import VerificationStatus
from guides.mathematics.rules import verify_question
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Question logic verification via the active subject guide."""
    flagged = 0
    for question in ctx.document.questions:
        flags = verify_question(question)
        question.verification.logic_flags = flags
        flagged += len(flags)
        unresolved = any(
            atu.status in (VerificationStatus.UNVERIFIED, VerificationStatus.CONFLICT)
            for atu in question.atus
        )
        if not flags and not unresolved:
            question.verification.status = VerificationStatus.AUTO_VERIFIED
        elif flags or unresolved:
            question.verification.status = VerificationStatus.UNVERIFIED
    ctx.emit("logic_verification", f"문항 논리 검증 — 플래그 {flagged}건")
