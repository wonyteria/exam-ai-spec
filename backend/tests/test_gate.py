from __future__ import annotations

from document.models import (
    ATU,
    ATUKind,
    Document,
    LogicFlag,
    Question,
    TextSpan,
    VerificationStatus,
)
from document.verification import evaluate_gate


def test_empty_document_fails_gate():
    report = evaluate_gate(Document())
    assert report.document_empty
    assert not report.passed


def test_conflict_counting_by_bucket():
    doc = Document(
        questions=[
            Question(
                number=1,
                atus=[
                    ATU(kind=ATUKind.NUMBER, status=VerificationStatus.CONFLICT),
                    ATU(kind=ATUKind.CHOICE, status=VerificationStatus.CONFLICT),
                    ATU(kind=ATUKind.TEXT_TOKEN, status=VerificationStatus.AUTO_VERIFIED),
                ],
            )
        ]
    )
    report = evaluate_gate(doc)
    assert report.number_conflict == 1
    assert report.choice_conflict == 1
    assert report.unverified == 0


def test_logic_flags_counted():
    doc = Document(
        questions=[
            Question(
                number=1,
                body=[],
                atus=[],
            )
        ]
    )
    doc.questions[0].verification.logic_flags = [
        LogicFlag(kind="unsolvable_question", detail="x"),
        LogicFlag(kind="ambiguous_answer", detail="y"),
    ]
    report = evaluate_gate(doc)
    assert report.unsolvable_question == 1
    assert report.ambiguous_answer == 1
    assert report.missing_object == 1


def test_missing_printed_number_detected():
    """extract_page can drop a whole question — the gap in printed numbering
    must surface as missing_object so the gate blocks the export."""
    body = [TextSpan(text="t")]
    doc = Document(
        questions=[
            Question(number=1, label="1", body=body),
            Question(number=2, label="2", body=body),
            Question(number=3, label="4", body=body),  # printed 3 was skipped
        ]
    )
    report = evaluate_gate(doc)
    assert report.missing_object == 1
    assert report.missing_numbers == [3]
    assert not report.passed


def test_duplicate_printed_number_is_conflict():
    body = [TextSpan(text="t")]
    doc = Document(
        questions=[
            Question(number=1, label="1", body=body),
            Question(number=2, label="1", body=body),
        ]
    )
    report = evaluate_gate(doc)
    assert report.number_conflict == 1


def test_non_numeric_labels_skip_continuity_check():
    body = [TextSpan(text="t")]
    doc = Document(
        questions=[
            Question(number=1, label="논술형 2", body=body),
            Question(number=2, label="2-1", body=body),
        ]
    )
    report = evaluate_gate(doc)
    assert report.missing_object == 0


def test_verified_document_passes_gate():
    doc = Document(
        questions=[
            Question(
                number=1,
                atus=[ATU(kind=ATUKind.NUMBER, status=VerificationStatus.HUMAN_VERIFIED)],
            )
        ]
    )
    doc.questions[0].body.append(TextSpan(text="t"))
    report = evaluate_gate(doc)
    assert report.unverified == 0
    assert report.missing_object == 0
    assert report.passed
