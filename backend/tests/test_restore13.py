"""RESTORE-13 — deterministic MathDNA checker.

Locks: SymPy-based parsing and equivalence produce only MATCH /
MISMATCH / UNKNOWN; UNKNOWN is never promoted to MATCH; SolveDNA wires
a proven MISMATCH to a math_check_failed logic flag instead of the
weaker ambiguous_answer.
"""
from __future__ import annotations

import pytest

from core.examdna.math.checker import (
    MathVerdict,
    check_units,
    equivalent,
    parse_math,
    verify_answer,
)


# -- parse_math ---------------------------------------------------------------

def test_parse_latex_forms():
    assert parse_math(r"\frac{x+1}{2}") is not None
    assert parse_math(r"x^{2}-1") is not None
    assert parse_math(r"\sqrt{3}") is not None


def test_parse_plain_and_unicode():
    assert parse_math("x*2 + 4") is not None
    assert parse_math("2×3") is not None
    assert parse_math("π") is not None


@pytest.mark.parametrize("bad", ["", "   ", "hello world", "문제입니다", None, 5])
def test_unparseable_returns_none(bad):
    assert parse_math(bad) is None


# -- equivalent ---------------------------------------------------------------

def test_equivalent_forms_match():
    assert equivalent(r"\frac{1}{2}", "0.5") is MathVerdict.MATCH
    assert equivalent("x^2 - 1", "(x-1)*(x+1)") is MathVerdict.MATCH
    assert equivalent("2x + 4", "2*(x+2)") is MathVerdict.MATCH


def test_proven_inequivalence_mismatch():
    assert equivalent("3", "5") is MathVerdict.MISMATCH
    assert equivalent(r"\frac{1}{2}", r"\frac{1}{3}") is MathVerdict.MISMATCH


def test_undecidable_or_unparseable_is_unknown():
    assert equivalent("hello", "3") is MathVerdict.UNKNOWN
    assert equivalent("x", "hello") is MathVerdict.UNKNOWN


# -- verify_answer ------------------------------------------------------------

def _choices():
    return {
        "①": "3",
        "②": r"\frac{7}{2}",
        "③": "4",
        "④": "5",
        "⑤": "x+1",
    }


def test_exact_label_and_text():
    c = _choices()
    assert verify_answer("③", c).matched_label == "③"
    assert verify_answer("4", c).matched_label == "③"


def test_symbolic_equivalence_matches_choice():
    c = _choices()
    check = verify_answer("3.5", c)
    assert check.verdict is MathVerdict.MATCH
    assert check.matched_label == "②"


def test_proven_mismatch_is_not_unknown():
    c = _choices()
    check = verify_answer("6", c)
    assert check.verdict is MathVerdict.MISMATCH
    assert check.matched_label is None


def test_no_choices_is_unknown():
    assert verify_answer("3", {}).verdict is MathVerdict.UNKNOWN


# -- units --------------------------------------------------------------------

def test_unit_check():
    assert check_units("12.5cm", ["cm"]).verdict is MathVerdict.MATCH
    assert check_units("12.5cm", ["kg"]).verdict is MathVerdict.MISMATCH
    assert check_units("12.5", ["cm"]).verdict is MathVerdict.UNKNOWN


# -- SolveDNA wiring ------------------------------------------------------------

def test_solve_mismatch_raises_math_flag(tmp_path):
    import numpy as np
    from PIL import Image
    from document.models import (
        Candidate,
        Document,
        Page,
        PageImage,
        Question,
        Choice,
        TextSpan,
        QuestionType,
    )
    from core.examdna.context import PipelineContext, Providers
    from core.examdna.verification import solving
    from jobs.models import Job

    src = tmp_path / "p.png"
    Image.fromarray(np.full((20, 20), 255, dtype=np.uint8)).save(src)
    doc = Document(tenant_id="t")
    doc.pages.append(Page(index=0, original=PageImage(uri=str(src))))
    q = Question(number=1, type=QuestionType.MULTIPLE_CHOICE)
    q.body = [TextSpan(text="계산하시오")]
    for label, body in [("①", "3"), ("②", "4")]:
        q.choices.append(Choice(label=label, body=[TextSpan(text=body)]))
    doc.questions.append(q)

    class WrongSolver:
        def solve_batch(self, problems, run=0):
            return [
                Candidate(
                    provider="wrong",
                    value=[{"number": "1", "solved": True, "answer": "6"}],
                    confidence=1.0,
                )
            ]

    ctx = PipelineContext(
        document=doc,
        job=Job(id="j", document_id=doc.id),
        store=None,
        workdir=tmp_path / "w",
        providers=Providers(solver=[WrongSolver()]),
        event_sink=lambda *a: None,
    )
    solving.run(ctx)
    flags = [f.kind for f in q.verification.logic_flags]
    assert "math_check_failed" in flags
    assert "ambiguous_answer" not in flags


def test_solve_symbolic_equivalent_answer_accepted(tmp_path):
    import numpy as np
    from PIL import Image
    from document.models import (
        Candidate,
        Document,
        Page,
        PageImage,
        Question,
        Choice,
        TextSpan,
        QuestionType,
    )
    from core.examdna.context import PipelineContext, Providers
    from core.examdna.verification import solving
    from jobs.models import Job

    src = tmp_path / "p.png"
    Image.fromarray(np.full((20, 20), 255, dtype=np.uint8)).save(src)
    doc = Document(tenant_id="t")
    doc.pages.append(Page(index=0, original=PageImage(uri=str(src))))
    q = Question(number=1, type=QuestionType.MULTIPLE_CHOICE)
    q.body = [TextSpan(text="계산하시오")]
    for label, body in [("①", r"\frac{7}{2}"), ("②", "4")]:
        q.choices.append(Choice(label=label, body=[TextSpan(text=body)]))
    doc.questions.append(q)

    class EqSolver:
        def solve_batch(self, problems, run=0):
            return [
                Candidate(
                    provider="eq",
                    value=[{"number": "1", "solved": True, "answer": "3.5"}],
                    confidence=1.0,
                )
            ]

    ctx = PipelineContext(
        document=doc,
        job=Job(id="j", document_id=doc.id),
        store=None,
        workdir=tmp_path / "w",
        providers=Providers(solver=[EqSolver()]),
        event_sink=lambda *a: None,
    )
    solving.run(ctx)
    assert q.answer.value == "①"
    assert not q.verification.logic_flags
