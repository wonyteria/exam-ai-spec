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
    invalid_figure: int = 0
    math_check_failed: int = 0
    unverified: int = 0
    hwp_mismatch: int = 0
    # RESTORE-07: expected-manifest reconciliation + artifact proof.
    manifest_mismatch: int = 0
    unprocessed_pages: int = 0
    artifact_proof: str = "NOT_RUN"  # PASS | FAILED | NOT_RUN
    document_empty: bool = False
    missing_numbers: list[int] = []  # detail for missing_object, not a counter
    manifest_mismatches: list[dict] = []  # detail for manifest_mismatch
    lineage: dict = {}  # hash chain evidence, not a counter

    @property
    def passed(self) -> bool:
        counters = all(
            v == 0
            for k, v in self.model_dump().items()
            if k
            not in (
                "document_empty",
                "missing_numbers",
                "manifest_mismatches",
                "lineage",
                "artifact_proof",
            )
        )
        # VERIFIED_FINAL needs a real hash-bound artifact proof — an
        # artifact that was never verified is NOT_RUN, never a pass.
        return (
            counters
            and not self.document_empty
            and self.artifact_proof == "PASS"
        )


def evaluate_gate(
    document: Document,
    hwp_mismatch: int = 0,
    artifact_proof: str = "NOT_RUN",
) -> GateReport:
    """P0-A ZERO TYPO FINAL + RESTORE-07 expected-manifest coverage.

    `ATU=0` is never read as "zero missing": the expected manifest (built
    from candidate evidence) is reconciled against what materialized, and
    unprocessed pages count too. The artifact proof must be a real PASS —
    NOT_RUN or FAILED block VERIFIED_FINAL.
    """
    from document.manifest import build_expected_manifest, build_lineage, reconcile

    report = GateReport(
        hwp_mismatch=hwp_mismatch, artifact_proof=artifact_proof
    )

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

    # Printed-number continuity: page extraction can miss a whole question,
    # leaving a gap (or duplicate) in the numeric label sequence.
    numbers = [
        int(q.label)
        for q in document.questions
        if (q.label or "").isdigit()
    ]
    if numbers:
        seen: set[int] = set()
        for n in numbers:
            if n in seen:
                report.number_conflict += 1
            seen.add(n)
        gaps = sorted(set(range(min(numbers), max(numbers) + 1)) - seen)
        report.missing_object += len(gaps)
        report.missing_numbers = gaps

    report.document_empty = len(document.questions) == 0

    manifest = build_expected_manifest(document)
    report.manifest_mismatches = reconcile(manifest, document)
    report.manifest_mismatch = len(report.manifest_mismatches)
    report.unprocessed_pages = len(manifest["unprocessed_pages"])
    report.lineage = build_lineage(document)
    return report
