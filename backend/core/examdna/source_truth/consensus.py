from __future__ import annotations

from document.models import (
    Choice,
    Document,
    Equation,
    Question,
    TextSpan,
    VerificationStatus,
)
from ..context import PipelineContext

AUTO_VERIFY_CONFIDENCE = 0.9


def run(ctx: PipelineContext) -> None:
    """Source Truth: turn Candidates into verified values via consensus.

    Rules:
    - >=2 providers agree on a value       -> AUTO_VERIFIED
    - providers disagree                   -> CONFLICT
    - single candidate, high confidence    -> AUTO_VERIFIED
    - single candidate, low confidence     -> stays UNVERIFIED (never guess)
    - no candidates                        -> UNREADABLE
    """
    counts = {s: 0 for s in VerificationStatus}
    for atu in ctx.document.all_atus():
        values = {repr(c.value) for c in atu.candidates}
        if not atu.candidates:
            atu.status = VerificationStatus.UNREADABLE
        elif len(values) > 1:
            atu.status = VerificationStatus.CONFLICT
        elif len(atu.candidates) >= 2 or atu.candidates[0].confidence >= AUTO_VERIFY_CONFIDENCE:
            atu.value = atu.candidates[0].value
            atu.status = VerificationStatus.AUTO_VERIFIED
        counts[atu.status] += 1

    _materialize(ctx.document)

    summary = ", ".join(f"{s.value}={n}" for s, n in counts.items() if n)
    ctx.emit("source_verification", f"원본 대조 완료 — {summary or 'ATU 없음'}")


def _materialize(document: Document) -> None:
    """Populate question fields from verified ATUs only."""
    verified = {VerificationStatus.AUTO_VERIFIED, VerificationStatus.HUMAN_VERIFIED}
    for q in document.questions:
        choices: dict[str, str] = {}
        for atu in q.atus:
            if atu.status not in verified or atu.field is None:
                continue
            if atu.field == "body":
                q.body.append(TextSpan(text=str(atu.value), atu_ids=[atu.id]))
            elif atu.field == "points":
                try:
                    q.points = int(atu.value)
                except (TypeError, ValueError):
                    pass
            elif atu.field == "type":
                try:
                    q.type = type(q.type)(atu.value)
                except ValueError:
                    pass
            elif atu.field.startswith("choice:"):
                choices[atu.field.split(":", 1)[1]] = str(atu.value)
            elif atu.field.startswith("equation:"):
                q.equations.append(Equation(latex=str(atu.value), source=atu.source))
        q.choices = [
            Choice(label=label, body=[TextSpan(text=text)]) for label, text in choices.items()
        ]
