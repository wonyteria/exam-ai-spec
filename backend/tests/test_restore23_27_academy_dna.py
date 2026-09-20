"""RESTORE-23 AcademyDNA + RESTORE-24/27 QuestionDNA/Difficulty."""
from __future__ import annotations

import pytest

from academy.profile import (
    AcademyProfile,
    extract_style,
    apply_style,
)
from document.models import (
    Answer,
    Choice,
    Document,
    Equation,
    Page,
    PageImage,
    PdfPageInventory,
    Question,
    QuestionType,
    Solution,
    TextSpan,
)
from question_dna.dna import derive_dna, difficulty_band, difficulty_score


def _doc_with_inventory() -> Document:
    d = Document()
    p = Page(index=0, original=PageImage(uri="mem://p0", sha256="x"))
    p.inventory = PdfPageInventory(
        page_index=0, width_pt=595.0, height_pt=842.0,
        fonts=["Helvetica", "NanumGothic"],
    )
    d.pages = [p]
    q = Question(number=1, type=QuestionType.MULTIPLE_CHOICE, points=4)
    q.choices = [Choice(label="①"), Choice(label="②")]
    d.questions = [q]
    return d


def test_extract_style_uses_measured_evidence():
    style = extract_style(_doc_with_inventory())
    assert style.page_size == [595.0, 842.0]
    assert "NanumGothic" in style.fonts
    assert style.choice_style == "circled"
    assert style.evidence  # every claim cites its source


def test_apply_style_separates_content_and_style():
    doc = _doc_with_inventory()
    profile = AcademyProfile(
        academy_id="ac_1", academy_name="행복학원",
        phone="02-123-4567",
    )
    bundle = apply_style(doc, profile, extract_style(doc), "midterm")
    assert bundle["header_text"] == "행복학원"
    assert bundle["columns"] == 2
    # the document itself is untouched
    assert doc.metadata.school == ""


def test_unknown_profile_kind_rejected():
    with pytest.raises(ValueError):
        apply_style(
            _doc_with_inventory(),
            AcademyProfile(academy_id="a", academy_name="x"),
            None,
            "birthday_party",
        )


def _math_q() -> Question:
    q = Question(number=1, type=QuestionType.MULTIPLE_CHOICE, points=4)
    q.body = [TextSpan(text="다음 중 옳지 않은 것은?")]
    q.equations = [Equation(latex="2*x+4=10")]
    for label, t in [("①", "3"), ("②", "-3"), ("③", "5")]:
        q.choices.append(Choice(label=label, body=[TextSpan(text=t)]))
    q.answer = Answer(value="①")
    q.solution = Solution(
        steps=[TextSpan(text="2x=6"), TextSpan(text="x=3")],
        concepts=["linear_equation"],
    )
    return q


def test_question_dna_features():
    dna = derive_dna(_math_q(), grade="중2", semester=1)
    for key in ("subject", "grade", "concepts", "problem_type",
                "required_skills", "solution_steps", "difficulty",
                "calculation_complexity", "condition_count",
                "figure_complexity", "trap_elements", "answer_type",
                "estimated_time"):
        assert key in dna
    assert dna["solution_steps"] == 2
    assert dna["calculation_complexity"] > 0
    assert "linear_equation" in dna["concepts"]
    assert any("negation" in t for t in dna["trap_elements"])
    assert dna["answer_type"] == "choice"
    assert dna["estimated_time"] > 0


def test_difficulty_is_feature_based_not_llm():
    easy = derive_dna(Question(number=1, type=QuestionType.SUBJECTIVE))
    hard_q = _math_q()
    hard_q.solution.steps += [TextSpan(text=str(i)) for i in range(6)]
    hard = derive_dna(hard_q)
    assert hard["difficulty"] > easy["difficulty"]
    assert difficulty_band(0.0) == "하"
    assert difficulty_band(2.0) == "중"
    assert difficulty_band(4.0) == "상"
    assert 0 <= difficulty_score({}) <= 5
