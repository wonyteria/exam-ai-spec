"""RESTORE-15 (spec) — ProblemDNA semantic contradiction checks.

Locks: symbolically equivalent choices under different labels are a
logic_conflict; a single choice is missing_condition; nonpositive
points are a logic_conflict; UNKNOWN never fabricates a contradiction.
"""
from __future__ import annotations

from document.models import (
    Choice,
    LogicFlag,
    Question,
    QuestionType,
    TextSpan,
)
from guides.mathematics.rules import verify_question


def _q(choices, points=4, body="다음을 계산하시오"):
    q = Question(number=1, type=QuestionType.MULTIPLE_CHOICE)
    q.body = [TextSpan(text=body)]
    q.points = points
    for label, text in choices:
        q.choices.append(Choice(label=label, body=[TextSpan(text=text)]))
    return q


def test_symbolically_equal_choices_flagged():
    q = _q([("①", "3"), ("②", "6/2"), ("③", "4"), ("④", "5"), ("⑤", "7")])
    kinds = [f.kind for f in verify_question(q)]
    assert "logic_conflict" in kinds
    dup = next(f for f in verify_question(q) if f.kind == "logic_conflict")
    assert "①" in dup.detail and "②" in dup.detail


def test_distinct_choices_clean():
    q = _q([("①", "3"), ("②", "4"), ("③", "5"), ("④", "6"), ("⑤", "7")])
    assert verify_question(q) == []


def test_single_choice_is_missing_condition():
    q = _q([("①", "3")])
    kinds = [f.kind for f in verify_question(q)]
    assert "missing_condition" in kinds


def test_nonpositive_points_flagged():
    q = _q([("①", "3"), ("②", "4")], points=0)
    kinds = [f.kind for f in verify_question(q)]
    assert "logic_conflict" in kinds


def test_unparseable_choices_not_flagged():
    # prose choices can't be symbolically compared — no contradiction
    q = _q([("①", "가능하다"), ("②", "불가능하다")])
    assert verify_question(q) == []


def test_empty_body_still_flagged():
    q = Question(number=1, type=QuestionType.SUBJECTIVE)
    kinds = [f.kind for f in verify_question(q)]
    assert "missing_condition" in kinds
