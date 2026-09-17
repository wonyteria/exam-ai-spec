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
