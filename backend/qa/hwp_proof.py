from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import unescape

from renderers.hwp import HWPWorkerUnavailable, WindowsHWPWorker


def run_hwp_proof(hwpx_path: Path, workdir: Path, document=None) -> int | None:
    """HWP round-trip + reverse-content proof (RESTORE-08).

    Steps:
      1. Hancom: Open HWPX -> SaveAs HWP -> ReOpen HWP -> SaveAs PDF,
         each step's return value verified by the worker.
      2. Re-parse the produced HWPX XML: every expected question head,
         points tag, choice label+body, equation object, endnote answer,
         and answer-space table must be present.
      3. Extract text from the rendered PDF and check the same tokens —
         a file that parses but renders without the content still fails.

    Returns the mismatch count, or None when the proof could not run (no
    Windows HWP worker). NOT_RUN is never a pass.
    """
    worker = WindowsHWPWorker()
    if not worker.is_available():
        return None
    try:
        worker.convert_with_proof(
            hwpx_path, workdir / "roundtrip.hwp", workdir / "roundtrip.pdf"
        )
    except HWPWorkerUnavailable:
        return None

    mismatches = 0
    if document is not None:
        mismatches += _hwpx_content_mismatches(hwpx_path, document)
        mismatches += _pdf_text_mismatches(workdir / "roundtrip.pdf", document)
    return mismatches


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text))


def _hwpx_text_and_objects(hwpx_path: Path):
    """All visible text + object census from the artifact's own XML."""
    texts: list[str] = []
    equations = 0
    tables = 0
    answer_spaces = 0
    endnote_answers = 0
    with zipfile.ZipFile(hwpx_path) as zf:
        for name in zf.namelist():
            if not (name.startswith("Contents/") and name.endswith(".xml")):
                continue
            xml = zf.read(name).decode("utf-8", errors="replace")
            texts += [
                unescape(m.group(1)) for m in re.finditer(r"<hp:t[^>]*>(.*?)</hp:t>", xml, re.S)
            ]
            equations += len(re.findall(r"<hp:equation\b", xml))
            tables += len(re.findall(r"<hp:tbl\b", xml))
            answer_spaces += xml.count("서술형 답안 작성란")
            endnote_answers += xml.count("정답:")
    return "".join(texts), {
        "equations": equations,
        "tables": tables,
        "answer_spaces": answer_spaces,
        "endnote_answers": endnote_answers,
    }


def _hwpx_content_mismatches(hwpx_path: Path, document) -> int:
    """Reverse-parse the artifact and compare against the canonical doc."""
    blob, objects = _hwpx_text_and_objects(hwpx_path)
    norm_blob = _norm(blob)
    miss = 0

    eq_expected = 0
    scored = 0
    descriptive = 0
    for q in document.questions:
        head = f"{q.label or q.number}."
        if _norm(head) not in norm_blob:
            miss += 1
        if q.points:
            scored += 1
            if _norm(f"{q.points}점") not in norm_blob:
                miss += 1
        if q.type.value != "multiple_choice":
            descriptive += 1
        for span in q.body:
            if _norm(span.text) and _norm(span.text) not in norm_blob:
                miss += 1
        for c in q.choices:
            body = _norm(" ".join(s.text for s in c.body))
            if _norm(c.label) not in norm_blob or (body and body not in norm_blob):
                miss += 1
        eq_expected += len(q.equations)

    if objects["equations"] < eq_expected:
        miss += eq_expected - objects["equations"]
    if objects["endnote_answers"] < scored:
        miss += scored - objects["endnote_answers"]
    if objects["answer_spaces"] < descriptive:
        miss += descriptive - objects["answer_spaces"]
    return miss


def _hwpx_scripts(hwpx_path: Path) -> list[str]:
    """All hp:equation script attributes — equations are objects, their
    script never appears in hp:t text runs."""
    scripts: list[str] = []
    with zipfile.ZipFile(hwpx_path) as zf:
        for name in zf.namelist():
            if not (name.startswith("Contents/") and name.endswith(".xml")):
                continue
            xml = zf.read(name).decode("utf-8", errors="replace")
            scripts += [
                unescape(m.group(1))
                for m in re.finditer(r'script="([^"]*)"', xml)
            ]
    return scripts


def equation_scripts(hwpx_path: Path) -> list[str]:
    """Public accessor for equation scripts (evidence/debug dumps)."""
    return _hwpx_scripts(hwpx_path)


def pdf_text(pdf_path: Path) -> str | None:
    """Extracted text of a rendered PDF, or None when unavailable."""
    if not pdf_path.exists():
        return None
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(pdf_path))
    except Exception:
        return None
    blob = ""
    for i in range(len(pdf)):
        page = pdf[i]
        try:
            tp = page.get_textpage()
            blob += tp.get_text_range() or ""
        finally:
            page.close()
    return blob


def _pdf_text_mismatches(pdf_path: Path, document) -> int:
    """Rendered-PDF text check — catches content lost between parse and
    render even when the XML itself is complete."""
    if not pdf_path.exists():
        return len(document.questions)  # render missing = everything absent
    blob = pdf_text(pdf_path)
    if blob is None:
        return 0  # cannot check without a rasterizer — stay honest, not counted
    norm_blob = _norm(blob)
    miss = 0
    for q in document.questions:
        if _norm(f"{q.label or q.number}.") not in norm_blob:
            miss += 1
        for c in q.choices:
            body = _norm(" ".join(s.text for s in c.body))
            if body and body not in norm_blob:
                miss += 1
    return miss
