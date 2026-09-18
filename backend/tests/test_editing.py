from __future__ import annotations

from core.examdna.editing import apply_ops, summarize
from document.models import (
    Choice,
    Document,
    Question,
    TextSpan,
    VerificationStatus,
)


def _doc() -> Document:
    return Document(
        questions=[
            Question(
                number=1,
                label="1",
                body=[TextSpan(text="다음 중 $x^2=4$의 해는?")],
                choices=[
                    Choice(label="①", body=[TextSpan(text="-2")]),
                    Choice(label="②", body=[TextSpan(text="2")]),
                ],
                points=4,
            ),
            Question(number=2, label="논술형 1", body=[TextSpan(text="지문")]),
        ]
    )


def test_apply_choice_and_body_ops():
    doc = _doc()
    before = doc.version
    result = apply_ops(
        doc,
        [
            {"question": "1", "field": "choice", "choice": "②", "value": "3"},
            {"question": "1", "field": "body", "value": "수정된 본문"},
            {"question": "1", "field": "points", "value": 5},
        ],
    )
    assert len(result["applied"]) == 3
    q = doc.questions[0]
    assert q.choices[1].body[0].text == "3"
    assert q.body[0].text == "수정된 본문"
    assert q.points == 5
    assert doc.version == before + 1
    # provenance ATUs are human-verified so the gate stays satisfied
    edited = [a for a in q.atus if a.status == VerificationStatus.HUMAN_VERIFIED]
    assert {a.field for a in edited} == {"choice:②", "body", "points"}


def test_label_resolves_named_question():
    doc = _doc()
    result = apply_ops(
        doc, [{"question": "논술형 1", "field": "body", "value": "새 지문"}]
    )
    assert result["applied"]
    assert doc.questions[1].body[0].text == "새 지문"


def test_unknown_question_and_field_skipped():
    doc = _doc()
    result = apply_ops(
        doc,
        [
            {"question": "99", "field": "body", "value": "x"},
            {"question": "1", "field": "nonsense", "value": "y"},
        ],
    )
    assert result["applied"] == []
    assert len(result["skipped"]) == 2
    assert doc.version == Document().version  # nothing applied -> no bump


def test_summarize_covers_editable_fields():
    doc = _doc()
    (entry,) = [s for s in summarize(doc) if s["question"] == "1"]
    assert entry["choices"] == {"①": "-2", "②": "2"}
    assert entry["points"] == 4
