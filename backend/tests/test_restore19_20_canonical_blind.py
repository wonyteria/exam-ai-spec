"""RESTORE-19 Canonical Exam + RESTORE-20 Blind Evaluation."""
from __future__ import annotations

import json

from canonical.exam import build_canonical_exam, canonical_exam_digest
from document.models import (
    Answer,
    Choice,
    Document,
    Equation,
    Page,
    PageImage,
    Question,
    QuestionType,
    Solution,
    SourceRef,
    BBox,
    TextSpan,
)
from eval.blind import load_sealed, seal_predictions, verify_seal


def _doc() -> Document:
    d = Document()
    d.metadata.school = "계남중"
    d.metadata.grade = "중2"
    d.metadata.year = 2025
    d.pages = [
        Page(index=0, original=PageImage(uri="mem://p0", sha256="aa"),
             sha256="aa", source_asset_id="asset_1")
    ]
    q = Question(number=1, type=QuestionType.MULTIPLE_CHOICE, points=4)
    q.body = [TextSpan(text="x의 값은?")]
    q.equations = [Equation(latex="2x+4=10")]
    q.choices = [
        Choice(label="①", body=[TextSpan(text="3")]),
        Choice(label="②", body=[TextSpan(text="4")]),
    ]
    q.answer = Answer(value="①")
    q.solution = Solution(steps=[TextSpan(text="2x=6")])
    q.source = SourceRef(page=0, bbox=BBox(x=1, y=2, w=3, h=4))
    d.questions = [q]
    return d


def test_canonical_exam_shape():
    exam = build_canonical_exam(_doc(), revision="rev_1")
    for key in ("exam_id", "school", "grade", "semester", "year",
                "exam_type", "subject", "pages", "questions", "layout",
                "source", "revision", "verification", "digest"):
        assert key in exam
    q = exam["questions"][0]
    for key in ("question_id", "number", "type", "stem", "conditions",
                "choices", "math_objects", "figure_graphs",
                "problem_graph", "score", "answer_space", "answer",
                "solution", "source_evidence", "verification",
                "question_dna"):
        assert key in q
    assert exam["school"] == "계남중"
    assert q["answer"] == "①"
    assert q["source_evidence"]["page"] == 0


def test_digest_stable_and_revision_independent():
    doc = _doc()
    e1 = build_canonical_exam(doc, revision="r1")
    e2 = build_canonical_exam(doc, revision="r2")
    assert e1["digest"] == e2["digest"]
    changed = dict(e1)
    changed["school"] = "다른중"
    assert canonical_exam_digest(changed) != e1["digest"]


def test_blind_seal_roundtrip(tmp_path):
    preds = {"q1": "3", "q2": "①"}
    path = tmp_path / "predictions.json"
    seal = seal_predictions(preds, path)
    assert verify_seal(path, seal)
    loaded = load_sealed(path, seal)
    assert loaded == preds


def test_blind_seal_detects_tampering(tmp_path):
    path = tmp_path / "predictions.json"
    seal = seal_predictions({"q1": "3"}, path)
    path.write_text(json.dumps({"q1": "4"}), encoding="utf-8")
    assert not verify_seal(path, seal)
    import pytest

    with pytest.raises(ValueError):
        load_sealed(path, seal)
