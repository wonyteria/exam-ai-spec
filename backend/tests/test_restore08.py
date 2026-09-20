"""RESTORE-08 — HWPX artifact reverse verification.

Locks: the proof re-parses the produced HWPX (question heads, points,
choices, equation objects, endnote answers, answer spaces) and compares
rendered-PDF text; content missing from the artifact is a mismatch, and
the proof stays hash-bound to the exact artifact bytes.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from document.models import (
    Answer,
    Choice,
    Document,
    Equation,
    Question,
    QuestionType,
    TextSpan,
)
from qa.hwp_proof import _hwpx_content_mismatches, run_hwp_proof
from renderers.hwpx import render_hwpx


def _doc() -> Document:
    doc = Document(tenant_id="t")
    q = Question(
        number=1,
        label="1",
        points=4,
        body=[TextSpan(text="다음 중 옳은 것은?")],
        choices=[
            Choice(label="①", body=[TextSpan(text="가")]),
            Choice(label="②", body=[TextSpan(text="나")]),
        ],
        equations=[Equation(latex="x^2")],
        answer=Answer(value="②"),
    )
    doc.questions.append(q)
    return doc


def test_reverse_parse_finds_all_content(tmp_path):
    hwpx = tmp_path / "exam.hwpx"
    hwpx.write_bytes(render_hwpx(_doc()))
    assert _hwpx_content_mismatches(hwpx, _doc()) == 0


def test_missing_content_is_a_mismatch(tmp_path):
    hwpx = tmp_path / "exam.hwpx"
    hwpx.write_bytes(render_hwpx(_doc()))
    # A document claiming content the artifact does not contain.
    other = _doc()
    other.questions[0].choices.append(
        Choice(label="⑤", body=[TextSpan(text="없는선지")])
    )
    assert _hwpx_content_mismatches(hwpx, other) >= 1


def test_dropped_equation_is_a_mismatch(tmp_path):
    doc = _doc()
    hwpx = tmp_path / "exam.hwpx"
    hwpx.write_bytes(render_hwpx(doc))
    # Strip the equation object from the artifact — simulates silent loss.
    with zipfile.ZipFile(hwpx) as zf:
        files = {n: zf.read(n) for n in zf.namelist()}
    sec = files["Contents/section0.xml"].decode("utf-8")
    import re

    sec = re.sub(r"<hp:equation\b.*?</hp:equation>", "", sec, flags=re.S)
    files["Contents/section0.xml"] = sec.encode("utf-8")
    with zipfile.ZipFile(hwpx, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, data in files.items():
            zf.writestr(n, data)
    assert _hwpx_content_mismatches(hwpx, doc) >= 1


def test_descriptive_needs_answer_space(tmp_path):
    doc = _doc()
    doc.questions[0].type = QuestionType.DESCRIPTIVE
    doc.questions[0].choices = []
    hwpx = tmp_path / "exam.hwpx"
    hwpx.write_bytes(render_hwpx(doc))
    assert _hwpx_content_mismatches(hwpx, doc) == 0

    # A descriptive question with no answer space in the artifact fails.
    with zipfile.ZipFile(hwpx) as zf:
        files = {n: zf.read(n) for n in zf.namelist()}
    files["Contents/section0.xml"] = (
        files["Contents/section0.xml"]
        .decode("utf-8")
        .replace("서술형 답안 작성란", "")
        .encode("utf-8")
    )
    with zipfile.ZipFile(hwpx, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, data in files.items():
            zf.writestr(n, data)
    assert _hwpx_content_mismatches(hwpx, doc) >= 1


@pytest.mark.skipif(
    __import__("platform").system() != "Windows",
    reason="Hancom worker requires Windows",
)
def test_real_hancom_roundtrip_proof(tmp_path):
    """Actual Hancom open/render/reparse on the produced artifact — skips
    cleanly (NOT_RUN) only where the worker is genuinely unavailable."""
    from renderers.hwp import WindowsHWPWorker

    if not WindowsHWPWorker.is_available():
        pytest.skip("HWP worker unavailable")
    hwpx = tmp_path / "exam.hwpx"
    hwpx.write_bytes(render_hwpx(_doc()))
    work = tmp_path / "proof"
    work.mkdir()
    mismatch = run_hwp_proof(hwpx, work, _doc())
    assert mismatch is not None
    assert (work / "roundtrip.hwp").exists()
    assert (work / "roundtrip.pdf").exists()
    assert mismatch == 0
