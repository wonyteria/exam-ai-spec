"""RESTORE-22 (spec) — DOCX render + round-trip verification.

Locks: the DOCX artifact re-parses with every expected token (heads,
points, choices, equations, answers, answer-space rules); a corrupted
or content-stripped file fails; missing python-docx is NOT_RUN(None),
never a pass.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

docx = pytest.importorskip("docx")
from docx import Document as DocxDocument  # noqa: E402

from document.models import (
    Answer,
    Choice,
    Document,
    Equation,
    Question,
    QuestionType,
    Solution,
    TextSpan,
)
from qa.docx_proof import docx_content_mismatches, docx_text, run_docx_proof
from renderers.docx.renderer import render_docx


def _doc() -> Document:
    d = Document()
    q1 = Question(number=1, type=QuestionType.MULTIPLE_CHOICE, points=4)
    q1.body = [TextSpan(text="다음 중 x의 값은?")]
    q1.equations = [Equation(latex="2x+4=10")]
    for label, t in [("①", "3"), ("②", "4"), ("③", "5")]:
        q1.choices.append(Choice(label=label, body=[TextSpan(text=t)]))
    q1.answer = Answer(value="①")
    q1.solution = Solution(steps=[TextSpan(text="x=3")])
    q2 = Question(number=2, type=QuestionType.DESCRIPTIVE, points=6)
    q2.body = [TextSpan(text="풀이 과정을 쓰시오")]
    q2.answer = Answer(value="6")
    d.questions = [q1, q2]
    return d


def test_render_and_roundtrip(tmp_path):
    doc = _doc()
    path = tmp_path / "exam.docx"
    path.write_bytes(render_docx(doc, title="중간고사"))
    assert docx_content_mismatches(path, doc) == 0
    assert run_docx_proof(path, doc) == 0


def test_answers_present_in_endnote_mode(tmp_path):
    doc = _doc()
    path = tmp_path / "exam.docx"
    path.write_bytes(render_docx(doc, output_mode="ANSWER_SOLUTION"))
    text = docx_text(path)
    assert "정답" in text and "①" in text


def test_student_mode_hides_answers(tmp_path):
    doc = _doc()
    path = tmp_path / "exam.docx"
    path.write_bytes(render_docx(doc, output_mode="STUDENT"))
    text = docx_text(path)
    assert "정답" not in text


def test_corrupt_docx_fails(tmp_path):
    doc = _doc()
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip")
    assert run_docx_proof(path, doc) != 0


def test_stripped_docx_fails(tmp_path):
    doc = _doc()
    out = DocxDocument()
    out.add_paragraph("empty")
    path = tmp_path / "stripped.docx"
    out.save(str(path))
    assert run_docx_proof(path, doc) > 0


def test_docx_is_valid_zip(tmp_path):
    path = tmp_path / "exam.docx"
    path.write_bytes(render_docx(_doc()))
    with zipfile.ZipFile(path) as zf:
        assert "word/document.xml" in zf.namelist()
