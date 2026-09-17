from __future__ import annotations

from pydantic import BaseModel

from .models import ATUKind, Document, VerificationStatus

_CONFLICT_BUCKET: dict[ATUKind, str] = {
    ATUKind.QUESTION_NUMBER: "number_conflict",
    ATUKind.NUMBER: "number_conflict",
    ATUKind.POINTS: "number_conflict",
    ATUKind.TEXT_TOKEN: "text_conflict",
    ATUKind.VARIABLE: "math_conflict",
    ATUKind.MATH_SYMBOL: "math_conflict",
    ATUKind.UNIT: "math_conflict",
    ATUKind.CHOICE: "choice_conflict",
    ATUKind.FIGURE_LABEL: "figure_conflict",
    ATUKind.ANGLE: "figure_conflict",
    ATUKind.LENGTH: "figure_conflict",
}


class GateReport(BaseModel):
    text_conflict: int = 0
    number_conflict: int = 0
    math_conflict: int = 0
    choice_conflict: int = 0
    figure_conflict: int = 0
    missing_condition: int = 0
    missing_object: int = 0
    logic_conflict: int = 0
    unsolvable_question: int = 0
    ambiguous_answer: int = 0
    unverified: int = 0
    hwp_mismatch: int = 0
    document_empty: bool = False

    @property
    def passed(self) -> bool:
        return (
            all(v == 0 for k, v in self.model_dump().items() if k != "document_empty")
            and not self.document_empty
        )


def evaluate_gate(document: Document, hwp_mismatch: int = 0) -> GateReport:
    """P0-A ZERO TYPO FINAL: every counter must be zero to ship VERIFIED_FINAL."""
    report = GateReport(hwp_mismatch=hwp_mismatch)

    for atu in document.all_atus():
        if atu.status in (
            VerificationStatus.UNVERIFIED,
            VerificationStatus.UNREADABLE,
        ):
            report.unverified += 1
        elif atu.status == VerificationStatus.CONFLICT:
            bucket = _CONFLICT_BUCKET.get(atu.kind, "text_conflict")
            setattr(report, bucket, getattr(report, bucket) + 1)

    for question in document.questions:
        if not question.body and not question.equations and not question.figures:
            report.missing_object += 1
        for flag in question.verification.logic_flags:
            setattr(report, flag.kind, getattr(report, flag.kind) + 1)

    report.document_empty = len(document.questions) == 0
    return report
