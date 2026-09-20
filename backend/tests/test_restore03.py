"""RESTORE-03 — page roles gate segmentation; questions carry anchors.

Locks: an ANSWER_KEY page is never scanned for question regions, a
raster grid heuristic may *suggest* the role for image-only pages, each
question gets a source anchor, and the review package exposes crops +
pending counts.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from document.models import Document, Page, PageImage


def _img(path, size=(400, 600), draw=None):
    im = Image.new("L", size, 230)
    if draw:
        arr = np.array(im)
        draw(arr)
        im = Image.fromarray(arr)
    im.save(path)
    return path


def _table_grid(arr):
    """Draw a dense ruled answer table."""
    h, w = arr.shape
    for y in range(80, h - 60, 28):
        arr[y : y + 2, 30 : w - 30] = 20
    for x in range(30, w - 30, 80):
        arr[80 : h - 60, x : x + 2] = 20


def _text_like(arr):
    """Sparse short marks — question-page-ish, no long rules."""
    h, w = arr.shape
    for y in range(100, h - 100, 45):
        arr[y : y + 8, 40 : 40 + int(w * 0.3)] = 40


def _run_segmentation(doc, tmp_path, vision=None):
    from core.examdna.context import PipelineContext, Providers
    from core.examdna.recognition import segmenter
    from jobs.models import Job

    ctx = PipelineContext(
        document=doc,
        job=Job(id="j", document_id=doc.id),
        store=None,
        workdir=tmp_path / "work",
        providers=Providers(vision=vision or []),
        event_sink=lambda *a: None,
    )
    segmenter.run(ctx)
    return ctx


def test_answer_key_page_is_not_scanned_for_questions(tmp_path):
    from providers.mock import MockVisionProvider

    q_img = _img(tmp_path / "p0.png", draw=_text_like)
    a_img = _img(tmp_path / "p1.png", draw=_table_grid)
    doc = Document(tenant_id="t")
    doc.pages.append(
        Page(index=0, original=PageImage(uri=str(q_img)),
             width=400, height=600, page_role="QUESTION", role_source="USER")
    )
    doc.pages.append(
        Page(index=1, original=PageImage(uri=str(a_img)),
             width=400, height=600, page_role="ANSWER_KEY", role_source="USER")
    )
    items = [{"label": "1", "bbox": {"xmin": 50, "ymin": 100, "xmax": 400, "ymax": 300}}]
    _run_segmentation(doc, tmp_path, vision=[MockVisionProvider(items=items)])
    # item was returned for both pages but only the question page yields a box
    assert len(doc.questions) == 1
    assert doc.questions[0].source.page == 0


def test_raster_grid_suggests_answer_key(tmp_path):
    from document.page_roles import suggest_role_from_raster

    grid = _img(tmp_path / "t.png", draw=_table_grid)
    gray = np.asarray(Image.open(grid))
    role, evidence = suggest_role_from_raster(gray)
    assert role == "ANSWER_KEY"
    assert evidence.startswith("raster_grid:")

    plain = _img(tmp_path / "q.png", draw=_text_like)
    gray = np.asarray(Image.open(plain))
    role, _ = suggest_role_from_raster(gray)
    assert role == "UNKNOWN"


def test_raster_suggestion_fills_unknown_role_and_skips(tmp_path):
    """An UNKNOWN page whose raster is a dense grid is suggested
    ANSWER_KEY (role_source AUTO) and excluded from question scan."""
    from providers.mock import MockVisionProvider

    grid = _img(tmp_path / "p.png", draw=_table_grid)
    doc = Document(tenant_id="t")
    page = Page(index=0, original=PageImage(uri=str(grid)), width=400, height=600)
    page.original.variants["grayscale"] = str(grid)
    doc.pages.append(page)
    items = [{"label": "9", "bbox": {"xmin": 50, "ymin": 50, "xmax": 300, "ymax": 200}}]
    _run_segmentation(doc, tmp_path, vision=[MockVisionProvider(items=items)])
    assert page.page_role == "ANSWER_KEY"
    assert page.role_source == "AUTO"  # suggestion only — user still confirms
    assert doc.questions == []


def test_question_carries_source_anchor(tmp_path):
    from providers.mock import MockVisionProvider
    from document.models import TransformStep

    img = _img(tmp_path / "p.png", draw=_text_like)
    doc = Document(tenant_id="t")
    page = Page(
        index=0, original=PageImage(uri=str(img)), width=400, height=600,
        sha256="abc",
        transform_chain=[TransformStep(kind="pdf_raster", params={"scale": 2.0})],
    )
    doc.pages.append(page)
    items = [{"label": "3", "bbox": {"xmin": 100, "ymin": 100, "xmax": 400, "ymax": 300}}]
    _run_segmentation(doc, tmp_path, vision=[MockVisionProvider(items=items)])
    q = doc.questions[0]
    assert q.source_anchor is not None
    assert q.source_anchor.source_sha256 == "abc"
    # bbox was padded then mapped back through scale=2
    assert q.source_anchor.source_bbox is not None
    assert q.source_anchor.source_bbox.w == pytest.approx(q.source.bbox.w / 2.0)


def test_review_package_builds_crops_and_pending(tmp_path):
    from document.models import ATU, ATUKind, Question, SourceRef, BBox, VerificationStatus
    from document.review import build_review_package

    img = _img(tmp_path / "p.png", draw=_text_like)
    doc = Document(id="d1", tenant_id="t")
    doc.pages.append(
        Page(index=0, original=PageImage(uri=str(img),
             variants={"raster": str(img)}), width=400, height=600)
    )
    q = Question(number=1, label="1",
                 source=SourceRef(page=0, bbox=BBox(x=40, y=90, w=120, h=60)))
    q.atus.append(ATU(kind=ATUKind.POINTS, field="points",
                      status=VerificationStatus.UNREADABLE))
    q.atus.append(ATU(kind=ATUKind.TEXT_TOKEN, field="body",
                      status=VerificationStatus.CONFLICT))
    doc.questions.append(q)

    pkg = build_review_package(doc, workdir=tmp_path / "w")
    assert pkg["review"]["question_count"] == 1
    assert pkg["review"]["pending_count"] == 1
    qe = pkg["questions"][0]
    assert qe["conflicts"] == 1 and qe["unreadable"] == 1
    assert Path(qe["crop"]["uri"]).exists()
    assert len(qe["crop"]["sha256"]) == 64
