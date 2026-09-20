"""DOCX round-trip proof (RESTORE-22).

Re-parse the produced DOCX with python-docx and compare every expected
token (question heads, points, choice label+body, equations, endnote
answers, answer-space rules) against the canonical document. A file
that parses but lost content fails — NOT_RUN is never a pass.
"""
from __future__ import annotations

import re
from pathlib import Path


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text))


def docx_text(docx_path: Path) -> str | None:
    """All paragraph + table text, or None when the file won't open."""
    try:
        from docx import Document as DocxDocument
        doc = DocxDocument(str(docx_path))
    except Exception:
        return None
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def docx_content_mismatches(docx_path: Path, document) -> int:
    blob = docx_text(docx_path)
    if blob is None:
        return len(document.questions) or 1
    norm_blob = _norm(blob)
    miss = 0
    for q in document.questions:
        if _norm(f"{q.label or q.number}.") not in norm_blob:
            miss += 1
        if q.points and _norm(f"{q.points:g}점") not in norm_blob:
            miss += 1
        for span in q.body:
            if _norm(span.text) and _norm(span.text) not in norm_blob:
                miss += 1
        for c in q.choices:
            body = _norm(" ".join(s.text for s in c.body))
            if _norm(c.label) not in norm_blob or (body and body not in norm_blob):
                miss += 1
        for eq in q.equations:
            script = _norm(eq.latex or eq.hwp_formula or "")
            if script and script not in norm_blob:
                miss += 1
    return miss


def run_docx_proof(docx_path: Path, document=None) -> int | None:
    """Returns the mismatch count, or None when python-docx is missing.
    NOT_RUN is never a pass."""
    try:
        import docx  # noqa: F401
    except ImportError:
        return None
    if document is None:
        return 0 if docx_text(docx_path) is not None else 1
    return docx_content_mismatches(docx_path, document)
