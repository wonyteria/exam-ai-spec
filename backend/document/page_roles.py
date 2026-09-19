"""Source-page role classification (AT-061 / REQ user-materials).

A photographed/scanned exam PDF may embed an answer/score sheet among
question pages. That page must never be silently treated as a question
page or dropped: every SourcePage carries `page_role` + `role_source`,
an AUTO heuristic may *suggest* a role, and only a USER confirmation
settles it. When the text layer is absent (pure scans) the page stays
UNKNOWN so the UI must ask rather than guess.
"""
from __future__ import annotations

# Korean/English markers that strongly suggest an answer/score sheet
_ANSWER_MARKERS = (
    "정답", "해답", "답안", "배점", "채점", "정답지", "정답 및",
    "answer key", "answer sheet", "solutions", "marking scheme",
)

# Question-page markers (문제/번호 패턴) — presence lowers answer-key score
_QUESTION_MARKERS = ("문제", "다음", "물음", "구하시오", "답하시오", "풀이하시오")


def suggest_page_role(text: str, pdf_page_index: int | None, page_count: int) -> tuple[str, str]:
    """Heuristic suggestion only — returns (role, evidence_label).
    Never authoritative: role_source stays AUTO until a user confirms."""
    t = (text or "").strip()
    if not t:
        # Scanned/photographed page with no text layer — cannot classify
        # offline; leave UNKNOWN so the user must designate the role.
        return "UNKNOWN", "no_text_layer"
    low = t.lower()
    answer_hits = sum(1 for m in _ANSWER_MARKERS if m in t or m in low)
    question_hits = sum(1 for m in _QUESTION_MARKERS if m in t)
    if answer_hits >= 1 and answer_hits > question_hits:
        return "ANSWER_KEY", f"markers:{answer_hits}"
    if question_hits >= 1:
        return "QUESTION", f"markers:{question_hits}"
    return "UNKNOWN", "insufficient_markers"


def extract_pdf_page_text(pdf_bytes: bytes, page_index: int) -> str:
    """Best-effort text-layer extraction via pypdfium2. Returns '' for
    image-only pages or when the rasterizer is unavailable — the caller
    must treat '' as 'cannot classify', never as 'question page'."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return ""
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        if page_index >= len(pdf):
            return ""
        page = pdf[page_index]
        try:
            tp = page.get_textpage()
            return tp.get_text_range() or ""
        finally:
            page.close()
    except Exception:
        return ""
