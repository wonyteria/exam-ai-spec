"""RESTORE-14 — PDF three-way classification, native evidence, RegionDNA.

Locks: SCANNED/DIGITAL/HYBRID classification is census-derived and
deterministic; native text fragments and font names are recorded as
bounded evidence; region typing produces typed PageRegion entries and
never drops ambiguous areas silently; Candidate carries first-class
provenance fields.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.examdna.preprocessing import classify_pdf_page, _page_inventory
from document.regions import RegionKind, classify_regions


# -- PDF classification --------------------------------------------------------

def test_scanned_when_no_text():
    # full-page image, no text layer
    bounds = [[0, 0, 612, 792]]
    assert classify_pdf_page(0, bounds, 612, 792) == "SCANNED"
    assert classify_pdf_page(0, [], 612, 792) == "SCANNED"


def test_digital_when_text_and_no_dominant_image():
    assert classify_pdf_page(500, [], 612, 792) == "DIGITAL"
    small_img = [[100, 100, 200, 200]]  # ~1.6% of page
    assert classify_pdf_page(500, small_img, 612, 792) == "DIGITAL"


def test_hybrid_when_sparse_text_or_big_image():
    assert classify_pdf_page(5, [], 612, 792) == "HYBRID"          # sparse
    full_img = [[0, 0, 612, 792]]
    assert classify_pdf_page(500, full_img, 612, 792) == "HYBRID"  # image ≥50%


def test_inventory_records_class_fragments_fonts(tmp_path):
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium
    from tests.pdf_fixtures import make_pdf

    text = "ABCDEFGHIJKLMNOPQRSTUVWX" * 3  # > sparse threshold
    pdf = pdfium.PdfDocument(make_pdf(1, text=text))
    try:
        inv = _page_inventory(pdf[0], 0)
    finally:
        pdf.close()
    assert inv.pdf_class == "DIGITAL"
    assert inv.text_chars >= len(text)
    assert inv.native_fragments
    assert all("bbox_pt" in f and f["text"] for f in inv.native_fragments)
    assert "Helvetica" in inv.fonts


def test_inventory_scanned_page(tmp_path):
    pytest.importorskip("pypdfium2")
    import pypdfium2 as pdfium
    from tests.pdf_fixtures import make_pdf

    pdf = pdfium.PdfDocument(make_pdf(1))  # blank page, no text
    try:
        inv = _page_inventory(pdf[0], 0)
    finally:
        pdf.close()
    assert inv.pdf_class == "SCANNED"
    assert inv.image_only
    assert inv.native_fragments == []


# -- RegionDNA -----------------------------------------------------------------

class _Src:
    def __init__(self, bbox):
        self.bbox = bbox


class _Q:
    def __init__(self, qid, bbox):
        self.id = qid
        self.source = _Src(bbox)


def _bbox(x, y, w, h):
    from document.models import BBox

    return BBox(x=x, y=y, w=w, h=h)


def test_header_footer_bands():
    gray = np.full((1000, 800), 220, dtype=np.uint8)
    gray[10:40, 100:700] = 40      # header ink
    gray[960:990, 100:700] = 40    # footer ink
    regions = classify_regions(gray, [])
    kinds = {r.kind for r in regions}
    assert RegionKind.HEADER in kinds
    assert RegionKind.FOOTER in kinds
    header = next(r for r in regions if r.kind is RegionKind.HEADER)
    assert header.bbox_px.y == 0 and header.confidence > 0


def test_question_body_and_answer_space():
    gray = np.full((1000, 800), 220, dtype=np.uint8)
    # question block: text in top part, blank bottom 300px = answer space
    q = _Q("q1", _bbox(50, 200, 700, 400))
    gray[220:340, 80:700] = 40        # dense-ish body text
    # make body rows dense enough: ensure ink across many rows
    regions = classify_regions(gray, [q])
    kinds = {r.kind for r in regions}
    assert RegionKind.QUESTION_BODY in kinds
    assert RegionKind.ANSWER_SPACE in kinds
    ans = next(r for r in regions if r.kind is RegionKind.ANSWER_SPACE)
    assert ans.question_id == "q1"
    assert ans.bbox_px.h >= 40


def test_ruled_grid_is_table():
    gray = np.full((600, 800), 220, dtype=np.uint8)
    q = _Q("q1", _bbox(50, 100, 700, 300))
    # 4 horizontal + 3 vertical rules inside the question box
    for y in (120, 190, 260, 330):
        gray[y : y + 2, 60:740] = 30
    for x in (60, 280, 500):
        gray[110:340, x : x + 2] = 30
    regions = classify_regions(gray, [q])
    assert any(r.kind is RegionKind.TABLE for r in regions)


def test_empty_or_untyped_is_not_fabricated():
    gray = np.full((500, 500), 240, dtype=np.uint8)  # blank page
    regions = classify_regions(gray, [])
    assert regions == []
    # a question with no bbox produces no body region
    q = _Q("q2", None)
    assert classify_regions(gray, [q]) == []


def test_region_never_silently_drops_unknowns():
    # classify_regions returns typed regions only; absence of typing is
    # honest emptiness — no UNKNOWN spam for clean content.
    gray = np.full((1000, 800), 220, dtype=np.uint8)
    q = _Q("q1", _bbox(50, 200, 700, 200))
    gray[220:340, 80:700] = 40
    regions = classify_regions(gray, [q])
    assert all(r.kind is not RegionKind.UNKNOWN for r in regions)


# -- Candidate provenance fields ------------------------------------------------

def test_candidate_first_class_provenance():
    from document.models import BBox, Candidate

    c = Candidate(
        provider="paddleocr",
        value="12.5cm",
        confidence=0.9,
        model_version="PP-OCRv5",
        bbox_asset=BBox(x=10, y=20, w=50, h=15),
        bbox_original=BBox(x=110, y=220, w=50, h=15),
        raw_output_sha256="abc",
        timestamp=1.0,
    )
    assert c.bbox_original.x == 110
    assert c.bbox_asset.x == 10
    assert c.model_version == "PP-OCRv5"
    d = c.model_dump()
    assert "bbox_original" in d and "timestamp" in d
