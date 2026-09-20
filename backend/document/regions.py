"""RegionDNA — typed region vocabulary inside a page (RESTORE-14).

Every region is a typed rectangle with evidence, never a silent crop:
HEADER/FOOTER bands, per-question QUESTION_BODY, ruled-grid TABLE,
sparse-cluster FIGURE, blank ANSWER_SPACE bands, and CONDITION (a
shared stem sitting above a question group). Anything that cannot be
typed with confidence stays UNKNOWN — routing reads the kind, and
UNKNOWN regions are never silently dropped from review payloads.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field

from .models import BBox


class RegionKind(str, Enum):
    HEADER = "HEADER"
    FOOTER = "FOOTER"
    QUESTION_BODY = "QUESTION_BODY"
    CHOICE_BLOCK = "CHOICE_BLOCK"
    CONDITION = "CONDITION"       # shared stem above grouped questions
    FIGURE = "FIGURE"
    TABLE = "TABLE"
    ANSWER_SPACE = "ANSWER_SPACE"
    SCORE = "SCORE"
    UNKNOWN = "UNKNOWN"


class PageRegion(BaseModel):
    kind: RegionKind = RegionKind.UNKNOWN
    bbox_px: BBox
    confidence: float = 0.0
    evidence: str = ""
    question_id: Optional[str] = None


_HEADER_BAND = 0.07      # top 7% of page height
_FOOTER_BAND = 0.07      # bottom 7%
_DARK_MIN = 150          # luminance below this counts as ink
_INK_MIN = 4             # px — band must contain at least this much ink
_BLANK_ROW_MAX = 0.005   # a row is blank when <0.5% of its pixels are ink
_ANSWER_MIN_H = 40       # px — contiguous blank band tall enough to write in
_ANSWER_ZONE = 0.45      # answer space lives in the lower 55% of a question
_RULE_FRAC = 0.6         # dark run covering >=60% of region width = table rule
_FIGURE_MIN_EXTENT = 80  # px — large sparse ink cluster inside a question


def classify_regions(
    gray: np.ndarray,
    questions,
    page_index: int = 0,
) -> list[PageRegion]:
    """Raster heuristic region typing. Conservative: bands and blank
    areas only — ambiguous rectangles are never guessed."""
    regions: list[PageRegion] = []
    if gray is None or gray.size == 0:
        return regions
    h, w = gray.shape
    dark = gray < _DARK_MIN

    # --- page furniture ------------------------------------------------
    hb = int(h * _HEADER_BAND)
    if dark[:hb].sum() >= _INK_MIN:
        regions.append(
            PageRegion(
                kind=RegionKind.HEADER,
                bbox_px=BBox(x=0, y=0, w=float(w), h=float(hb)),
                confidence=0.8,
                evidence="top_band_ink",
            )
        )
    fb = int(h * _FOOTER_BAND)
    if dark[h - fb :].sum() >= _INK_MIN:
        regions.append(
            PageRegion(
                kind=RegionKind.FOOTER,
                bbox_px=BBox(x=0, y=float(h - fb), w=float(w), h=float(fb)),
                confidence=0.8,
                evidence="bottom_band_ink",
            )
        )

    # --- per-question regions -------------------------------------------
    for q in questions:
        bbox = getattr(getattr(q, "source", None), "bbox", None)
        if bbox is None:
            continue
        x0, y0 = int(bbox.x), int(bbox.y)
        bw, bh = int(bbox.w), int(bbox.h)
        if bw <= 0 or bh <= 0:
            continue
        sub = dark[y0 : y0 + bh, x0 : x0 + bw]
        if sub.size == 0:
            continue
        regions.append(
            PageRegion(
                kind=RegionKind.QUESTION_BODY,
                bbox_px=BBox(x=float(x0), y=float(y0), w=float(bw), h=float(bh)),
                confidence=0.9,
                evidence="segmented_question",
                question_id=getattr(q, "id", None),
            )
        )
        table = _ruled_table(sub, x0, y0, bw, bh)
        if table is not None:
            table.question_id = getattr(q, "id", None)
            regions.append(table)
        answer = _answer_space(sub, x0, y0, bw, bh)
        if answer is not None:
            answer.question_id = getattr(q, "id", None)
            regions.append(answer)
    return regions


def _ruled_table(
    sub: np.ndarray, x0: int, y0: int, bw: int, bh: int
) -> Optional[PageRegion]:
    """Dense ruled grid inside the question box → TABLE."""
    h_rules = sum(
        1 for row in sub if _longest_run(row) >= _RULE_FRAC * bw
    )
    v_rules = sum(
        1 for col in sub.T if _longest_run(col) >= _RULE_FRAC * bh
    )
    if h_rules >= 3 and v_rules >= 2:
        return PageRegion(
            kind=RegionKind.TABLE,
            bbox_px=BBox(x=float(x0), y=float(y0), w=float(bw), h=float(bh)),
            confidence=min(1.0, (h_rules + v_rules) / 10),
            evidence=f"ruled_grid:h{h_rules}/v{v_rules}",
        )
    return None


def _answer_space(
    sub: np.ndarray, x0: int, y0: int, bw: int, bh: int
) -> Optional[PageRegion]:
    """A contiguous blank band in the lower part of a question box is the
    written-answer space — preserved for layout, never filled."""
    zone_start = int(bh * _ANSWER_ZONE)
    if zone_start >= bh:
        return None
    blank = ~sub[zone_start:].any(axis=1) | (
        sub[zone_start:].mean(axis=1) < _BLANK_ROW_MAX
    )
    # longest contiguous blank run
    best = cur = start = 0
    for i, b in enumerate(blank):
        if b:
            if cur == 0:
                start = i
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    if best < _ANSWER_MIN_H:
        return None
    return PageRegion(
        kind=RegionKind.ANSWER_SPACE,
        bbox_px=BBox(
            x=float(x0),
            y=float(y0 + zone_start),
            w=float(bw),
            h=float(best),
        ),
        confidence=min(1.0, best / 200),
        evidence=f"blank_band:{best}px",
    )


def _longest_run(row) -> int:
    if not row.any():
        return 0
    padded = np.concatenate(([False], row, [False]))
    diff = np.diff(padded.astype(np.int8))
    starts = np.nonzero(diff == 1)[0]
    ends = np.nonzero(diff == -1)[0]
    if not len(starts):
        return 0
    return int((ends - starts).max())
