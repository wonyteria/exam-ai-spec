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


# --- raster-based role suggestion ------------------------------------------------

# A printed answer/score sheet is visually a dense ruled table. For
# image-only pages (no text layer) this heuristic produces a *suggestion*
# — it never settles the role (role_source stays AUTO).
_ANSWER_GRID_MIN_HRULES = 12      # long horizontal rules spanning the table
_ANSWER_GRID_MIN_VRULES = 3       # table column separators
_RULE_MIN_RUN = 0.55              # contiguous dark run covering >=55% width


def suggest_role_from_raster(gray) -> tuple[str, str]:
    """Classify a rasterized page as an answer-grid candidate by detecting
    dense long table rules. Conservative: only ANSWER_KEY or UNKNOWN.
    `gray` is a 2-D numpy array (luminance)."""
    import numpy as np

    if gray is None or gray.ndim != 2 or gray.size == 0:
        return "UNKNOWN", "no_raster"
    h, w = gray.shape
    dark = gray < 150
    # Rows whose dark pixels cover a wide contiguous band = table rules.
    h_rules = 0
    for row in dark:
        if _longest_run(row) >= _RULE_MIN_RUN * w:
            h_rules += 1
    v_rules = 0
    for col in dark.T:
        if _longest_run(col) >= _RULE_MIN_RUN * h:
            v_rules += 1
    if h_rules >= _ANSWER_GRID_MIN_HRULES and v_rules >= _ANSWER_GRID_MIN_VRULES:
        return "ANSWER_KEY", f"raster_grid:h{h_rules}/v{v_rules}"
    return "UNKNOWN", f"raster_grid:h{h_rules}/v{v_rules}"


def _longest_run(row) -> int:
    """Longest contiguous True run."""
    import numpy as np

    if not row.any():
        return 0
    padded = np.concatenate(([False], row, [False]))
    diff = np.diff(padded.astype(np.int8))
    starts = np.nonzero(diff == 1)[0]
    ends = np.nonzero(diff == -1)[0]
    if not len(starts):
        return 0
    return int((ends - starts).max())


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
