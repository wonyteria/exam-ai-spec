"""RESTORE-01 — source evidence: PDF inventory, transform chains, anchors.

Locks the contract that every derived artifact can be traced back to the
immutable source: page-level native census, invertible transform steps,
variant hashes, and explicit failure markers instead of silent skips.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.pdf_fixtures import make_pdf


def _ctx(doc, workdir: Path):
    from core.examdna.context import PipelineContext, Providers
    from jobs.models import Job

    return PipelineContext(
        document=doc,
        job=Job(id="job_t", document_id=doc.id),
        store=None,
        workdir=workdir,
        providers=Providers(),
        event_sink=lambda *a: None,
    )


def _run(doc, tmp_path):
    from core.examdna import preprocessing

    ctx = _ctx(doc, tmp_path / "work")
    preprocessing.run(ctx)
    return ctx


def _doc_with_pdf(pdf: Path, pages: int):
    from document.models import Document, Page, PageImage

    doc = Document(tenant_id="t")
    for i in range(pages):
        doc.pages.append(
            Page(index=i, original=PageImage(uri=str(pdf)), pdf_page_index=i)
        )
    return doc


def test_pdf_inventory_marks_image_only(tmp_path):
    pytest.importorskip("pypdfium2")
    src = tmp_path / "scan.pdf"
    data = make_pdf(1)  # blank page — no text objects
    src.write_bytes(data)
    doc = _doc_with_pdf(src, 1)

    _run(doc, tmp_path)

    inv = doc.pages[0].inventory
    assert inv is not None
    assert inv.text_chars == 0
    assert inv.image_only is True
    assert inv.width_pt == pytest.approx(612.0)
    assert inv.height_pt == pytest.approx(792.0)
    # source bytes untouched
    assert hashlib.sha256(data).hexdigest() == hashlib.sha256(src.read_bytes()).hexdigest()


def test_pdf_inventory_text_page(tmp_path):
    pytest.importorskip("pypdfium2")
    src = tmp_path / "text.pdf"
    src.write_bytes(make_pdf(1, text="Hello exam"))
    doc = _doc_with_pdf(src, 1)

    _run(doc, tmp_path)

    inv = doc.pages[0].inventory
    assert inv is not None
    assert inv.text_chars >= 5
    assert inv.image_only is False
    assert inv.text_layer_sparse is True  # one short line < threshold


def test_pdf_inventory_rotation_and_boxes(tmp_path):
    pytest.importorskip("pypdfium2")
    src = tmp_path / "rot.pdf"
    src.write_bytes(make_pdf(1, rotate=90))
    doc = _doc_with_pdf(src, 1)

    _run(doc, tmp_path)

    inv = doc.pages[0].inventory
    assert inv is not None
    assert inv.rotation == 90
    assert inv.mediabox == [0.0, 0.0, 612.0, 792.0]


def test_transform_chain_and_variant_hashes(tmp_path):
    pytest.importorskip("pypdfium2")
    src = tmp_path / "scan.pdf"
    src.write_bytes(make_pdf(1))
    doc = _doc_with_pdf(src, 1)

    _run(doc, tmp_path)

    page = doc.pages[0]
    kinds = [s.kind for s in page.transform_chain]
    assert "pdf_raster" in kinds
    step = next(s for s in page.transform_chain if s.kind == "pdf_raster")
    assert step.params["scale"] == pytest.approx(200 / 72)
    # every derived variant carries its byte hash
    for name, uri in page.original.variants.items():
        digest = hashlib.sha256(Path(uri).read_bytes()).hexdigest()
        assert page.original.variant_sha256[name] == digest


def test_failed_pdf_render_marks_page(tmp_path):
    src = tmp_path / "corrupt.pdf"
    src.write_bytes(b"%PDF-1.4 garbage not a pdf")
    doc = _doc_with_pdf(src, 1)

    events = []
    from core.examdna import preprocessing
    from core.examdna.context import PipelineContext, Providers
    from jobs.models import Job

    ctx = PipelineContext(
        document=doc,
        job=Job(id="j", document_id=doc.id),
        store=None,
        workdir=tmp_path / "work",
        providers=Providers(),
        event_sink=lambda s, m, l: events.append(l),
    )
    preprocessing.run(ctx)

    page = doc.pages[0]
    assert page.processing_error is not None
    assert "warn" in events


def test_anchor_inverse_pdf_raster(tmp_path):
    from document.anchors import anchor_for
    from document.models import BBox, Page, PageImage, TransformStep

    page = Page(
        index=0,
        original=PageImage(uri="x"),
        pdf_page_index=0,
        transform_chain=[
            TransformStep(
                kind="pdf_raster",
                params={"pdf_page_index": 0, "scale": 200 / 72, "applied": True},
            )
        ],
    )
    a = anchor_for(page, BBox(x=100.0, y=200.0, w=50.0, h=40.0), source_sha256="s")
    assert a.source_bbox is not None
    scale = 200 / 72
    assert a.source_bbox.x == pytest.approx(100.0 / scale)
    assert a.source_bbox.h == pytest.approx(40.0 / scale)
    assert a.page_index == 0
    assert a.transform_chain[0].kind == "pdf_raster"


def test_anchor_inverse_exif_rotation(tmp_path):
    from document.anchors import anchor_for
    from document.models import BBox, Page, PageImage, TransformStep

    # stored 100x50, displayed rotated 90 CW -> 50x100
    page = Page(
        index=0,
        original=PageImage(uri="x"),
        transform_chain=[
            TransformStep(
                kind="exif_orientation",
                params={
                    "exif_orientation": 6,
                    "axes_swapped": True,
                    "original_width": 100,
                    "original_height": 50,
                },
            )
        ],
    )
    a = anchor_for(page, BBox(x=0.0, y=0.0, w=10.0, h=20.0))
    # displayed (0,0,10,20) -> stored: sx=y=0, sy=W_d-x-w=50-0-10=40
    assert a.source_bbox is not None
    assert a.source_bbox.x == pytest.approx(0.0)
    assert a.source_bbox.y == pytest.approx(40.0)
    assert a.source_bbox.w == pytest.approx(20.0)
    assert a.source_bbox.h == pytest.approx(10.0)


def test_anchor_unknown_step_refuses_to_guess(tmp_path):
    from document.anchors import anchor_for
    from document.models import BBox, Page, PageImage, TransformStep

    page = Page(
        index=0,
        original=PageImage(uri="x"),
        transform_chain=[TransformStep(kind="unknown_warp", params={})],
    )
    a = anchor_for(page, BBox(x=1, y=2, w=3, h=4))
    assert a.source_bbox is None  # never fabricate coordinates


def test_missing_source_marks_error_not_silent(tmp_path):
    from core.examdna import preprocessing
    from document.models import Document, Page, PageImage

    doc = Document(tenant_id="t")
    doc.pages.append(
        Page(index=0, original=PageImage(uri=str(tmp_path / "gone.png")))
    )
    ctx = _ctx(doc, tmp_path / "work")
    preprocessing.run(ctx)
    assert doc.pages[0].processing_error == "source_missing"
