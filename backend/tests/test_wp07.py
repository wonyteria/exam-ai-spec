"""WP07 contract tests: shared layout plan, real hp:equation/hp:endNote
objects, output modes, brand separation, plan-driven web/PDF rendering.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from document.models import (
    Answer,
    Choice,
    Document,
    Equation,
    Question,
    Solution,
    TextSpan,
)
from renderers.brand import get_brand
from renderers.hwpx import render_hwpx
from renderers.pdf import render_pdf
from renderers.plan import (
    build_plan,
    collect_endnotes,
    plan_text_invariants,
)
from renderers.web import render_preview


def _doc(objective=4, descriptive=1, tenant="tn_1") -> Document:
    d = Document(tenant_id=tenant)
    for n in range(1, objective + 1):
        d.questions.append(
            Question(
                number=n,
                label=str(n),
                points=3,
                body=[TextSpan(text=f"객관식 본문 {n}")],
                choices=[
                    Choice(label="①", body=[TextSpan(text="첫째")]),
                    Choice(label="②", body=[TextSpan(text="둘째")]),
                ],
                answer=Answer(value="2"),
                solution=Solution(steps=[TextSpan(text=f"풀이 {n}")]),
                equations=[Equation(latex="x^2=4", hwp_formula="x^{2} = 4")],
            )
        )
    for n in range(objective + 1, objective + descriptive + 1):
        d.questions.append(
            Question(
                number=n,
                label=str(n),
                type="descriptive",
                points=10,
                body=[TextSpan(text=f"서술형 본문 {n}")],
                answer=Answer(value="서술 답"),
                solution=Solution(steps=[TextSpan(text="서술 풀이")]),
            )
        )
    return d


def _section(hwpx: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(hwpx)).read(
        "Contents/section0.xml"
    ).decode()


def _header(hwpx: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(hwpx)).read(
        "Contents/header.xml"
    ).decode()


def _text_of(hwpx: bytes) -> str:
    """All hp:t text content — the semantic payload of the artifact."""
    import re

    s = _section(hwpx)
    return "".join(re.findall(r"<hp:t>([^<]*)</hp:t>", s))


# --- layout plan ---------------------------------------------------------------------


def test_objective_grid_and_row_pairing():
    doc = _doc(objective=4, descriptive=0)
    plan = build_plan(doc)
    obj = [s for s in plan.slots if s.kind == "objective"]
    assert [s.column for s in obj] == [0, 1, 0, 1]
    assert [s.row for s in obj] == [0, 0, 1, 1]
    assert plan.rows == [[obj[0].question_id, obj[1].question_id],
                         [obj[2].question_id, obj[3].question_id]]
    assert plan_text_invariants(plan, doc) == []


def test_descriptive_answer_space():
    doc = _doc(objective=0, descriptive=1)
    plan = build_plan(doc)
    slot = plan.slots[0]
    assert slot.kind == "descriptive"
    assert slot.answer_lines >= 6  # 10 points * 2 lines, min 6


def test_shared_child_full_width():
    doc = _doc(objective=2, descriptive=0)
    child = Question(number=5, label="2-1", parent_id=doc.questions[1].id, points=4)
    doc.questions.append(child)
    plan = build_plan(doc)
    s = next(s for s in plan.slots if s.question_id == child.id)
    assert s.kind == "shared_child" and s.column is None


def test_student_mode_carries_no_endnotes():
    doc = _doc()
    plan = build_plan(doc, output_mode="STUDENT")
    assert plan.endnotes == []
    assert plan_text_invariants(plan, doc) == []


def test_endnote_covers_all_scored_units():
    doc = _doc(objective=4, descriptive=1)
    notes = collect_endnotes(doc)
    assert len(notes) == 5  # all five scored questions
    assert all(n.answer and n.explanation for n in notes)


def test_plan_invariant_detects_missing_endnote():
    doc = _doc()
    plan = build_plan(doc)
    plan.endnotes = plan.endnotes[:-1]  # drop one scored unit's note
    assert any("without endnote" in e for e in plan_text_invariants(plan, doc))


# --- HWPX renderer --------------------------------------------------------------------


def test_hwpx_real_endnote_and_equation_objects():
    doc = _doc(objective=3, descriptive=0)
    s = _section(render_hwpx(doc))
    assert s.count("<hp:endNote ") == 3  # one per scored unit
    assert "정답: 2" in s and "풀이" in s
    assert s.count("<hp:equation ") == 3
    assert 'baseUnit="1100"' in s
    assert "<hp:script>x^{2} = 4</hp:script>" in s
    assert "x^2" not in s  # no raw LaTeX leaks


def test_hwpx_two_column_layout():
    doc = _doc(objective=4, descriptive=0)
    s = _section(render_hwpx(doc))
    assert 'colCount="2"' in s


def test_hwpx_student_mode_hides_answers():
    """학생용 답안 비노출: STUDENT output must not carry answers anywhere."""
    doc = _doc(objective=3, descriptive=1)
    text = _text_of(render_hwpx(doc, output_mode="STUDENT"))
    assert "정답" not in text
    assert "서술 답" not in text
    assert "풀이" not in text
    s = _section(render_hwpx(doc, output_mode="STUDENT"))
    assert "<hp:endNote " not in s


def test_hwpx_answer_solution_mode():
    doc = _doc(objective=2, descriptive=0)
    s = _section(render_hwpx(doc, output_mode="ANSWER_SOLUTION"))
    assert "정답 및 해설" in s
    assert "정답: 2" in s


def test_hwpx_teacher_mode_shows_verification():
    doc = _doc(objective=2, descriptive=0)
    s = _section(render_hwpx(doc, output_mode="TEACHER"))
    assert "검증 상태" in s
    assert "UNVERIFIED" in s


def test_hwpx_unparseable_equation_dropped_not_leaked():
    doc = _doc(objective=1, descriptive=0)
    doc.questions[0].equations = [
        Equation(latex=r"\begin{matrix}a\end{matrix}")
    ]
    s = _section(render_hwpx(doc))
    assert "<hp:equation " not in s
    assert "matrix" not in s


# --- brand separation ---------------------------------------------------------------------


def test_brand_change_same_content():
    doc = _doc(objective=2, descriptive=1)
    bodies = []
    for b in ("default", "examdna", "minimal"):
        t = _text_of(render_hwpx(doc, brand_id=b))
        header = get_brand(b).header_text or "시험지"
        bodies.append(t.removeprefix(header))
    # header text differs (brand), question content is identical
    assert bodies[0] == bodies[1] == bodies[2]
    assert "객관식 본문 1" in bodies[0]
    # styling actually differs
    assert "ExamDNA 복원 시험지" in _text_of(
        render_hwpx(doc, brand_id="examdna")
    )
    assert get_brand("examdna").accent_color in _header(
        render_hwpx(doc, brand_id="examdna")
    )
    assert get_brand("nonexistent").id == "default"  # safe fallback


# --- web preview --------------------------------------------------------------------------


def test_web_preview_modes():
    doc = _doc(objective=2, descriptive=1)
    student = render_preview(doc, output_mode="STUDENT")
    assert "정답" not in student
    assert "서술 답" not in student
    notes = render_preview(doc, output_mode="STUDENT_WITH_ENDNOTES")
    assert "정답 및 해설" in notes
    assert "풀이" in notes
    assert "class='grid'" in notes and "wide" in notes


# --- PDF ------------------------------------------------------------------------------------


def test_pdf_unicode_and_modes():
    doc = _doc(objective=2, descriptive=1)
    b = render_pdf(doc, output_mode="ANSWER_SOLUTION")
    assert b.startswith(b"%PDF-1.4")
    assert b"Type0" in b and b"HYGoThic-Medium" in b
    # 실제 한글: UTF-16BE hex of '본문' present — no '?' placeholder text
    assert "본문".encode("utf-16-be").hex().encode() in b
    assert b"?" not in b.split(b"stream")[1].split(b"Tj")[0]
    student = render_pdf(doc, output_mode="STUDENT")
    assert "정답".encode("utf-16-be").hex().encode() not in student


def test_pdf_pagination():
    doc = _doc(objective=20, descriptive=0)
    b = render_pdf(doc)
    import re

    m = re.search(rb"/Count (\d+)", b)
    assert m and int(m.group(1)) >= 2  # >42 lines -> real page breaks
