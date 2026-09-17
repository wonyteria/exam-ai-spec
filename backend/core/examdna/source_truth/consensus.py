from __future__ import annotations

from document.models import VerificationStatus
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Source Truth: turn Candidates into verified values via consensus.

    Rules:
    - >=2 providers agree on a value -> AUTO_VERIFIED
    - providers disagree              -> CONFLICT
    - exactly one candidate           -> stays UNVERIFIED (never guess)
    - no candidates                   -> UNREADABLE
    """
    counts = {s: 0 for s in VerificationStatus}
    for atu in ctx.document.all_atus():
        values = {repr(c.value) for c in atu.candidates}
        if not atu.candidates:
            atu.status = VerificationStatus.UNREADABLE
        elif len(atu.candidates) >= 2 and len(values) == 1:
            atu.value = atu.candidates[0].value
            atu.status = VerificationStatus.AUTO_VERIFIED
        elif len(values) > 1:
            atu.status = VerificationStatus.CONFLICT
        counts[atu.status] += 1

    summary = ", ".join(f"{s.value}={n}" for s, n in counts.items() if n)
    ctx.emit("source_verification", f"원본 대조 완료 — {summary or 'ATU 없음'}")
