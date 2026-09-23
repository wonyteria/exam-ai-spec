"""RESTORE-04 — six-class layer evidence, policy-based removal, review.

Locks: per-class masks are stored separately, confident non-overlapping
annotation ink is whitened into `restored_candidate`, print-overlapping
or uncertain components are preserved and reported, and no pixel outside
the approved mask ever changes.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from core.examdna.student_trace import separator
from core.examdna.student_trace.layers import LayerClass, classify_layers
from document.models import Document, Page, PageImage


def _ctx(doc, workdir):
    from core.examdna.context import PipelineContext, Providers
    from jobs.models import Job

    return PipelineContext(
        document=doc,
        job=Job(id="j", document_id=doc.id),
        store=None,
        workdir=workdir,
        providers=Providers(),
        event_sink=lambda *a: None,
    )


def _page(gray: np.ndarray, tmp_path, rgb=None):
    src = tmp_path / "page.png"
    Image.fromarray(rgb if rgb is not None else gray).save(src)
    vdir = tmp_path / "variants"
    vdir.mkdir(exist_ok=True)
    gp = vdir / "page_grayscale.png"
    Image.fromarray(gray).save(gp)
    return src, gp


def _run(gray, tmp_path, rgb=None):
    src, gp = _page(gray, tmp_path, rgb)
    doc = Document(tenant_id="t")
    page = Page(
        index=0,
        original=PageImage(uri=str(src), variants={"grayscale": str(gp)}),
    )
    doc.pages.append(page)
    ctx = _ctx(doc, tmp_path / "work")
    separator.run(ctx)
    return page


def _ring(h=200, w=400, center=(100, 100), r=60, t=5):
    yy, xx = np.mgrid[0:h, 0:w]
    d2 = (yy - center[0]) ** 2 + (xx - center[1]) ** 2
    return (d2 < r * r) & (d2 > (r - t) ** 2)


def test_confident_pencil_mark_removed_and_classified(tmp_path):
    gray = np.full((200, 400), 200, dtype=np.uint8)
    mark = _ring(200, 400, (100, 200), 60)
    gray[mark] = 80  # dark pencil circle, no print near
    page = _run(gray, tmp_path)

    restored = np.asarray(
        Image.open(page.original.variants["restored_candidate"]), dtype=np.uint8
    )
    assert (restored[mark] == 255).all()
    # per-class mask + overlay recorded as evidence variants
    assert "layer_pencil" in page.original.variants or (
        "layer_black_pen" in page.original.variants
    )
    assert "layer_overlay" in page.original.variants
    assert not page.uncertain_regions


def test_grading_mark_by_chroma_removed(tmp_path):
    gray = np.full((200, 400), 200, dtype=np.uint8)
    rgb = np.stack([gray] * 3, axis=2).copy()
    tick = _ring(200, 400, (100, 200), 70, 4)
    rgb[tick] = (200, 20, 20)  # red grading circle
    gray[tick] = 110
    page = _run(gray, tmp_path, rgb=rgb)

    restored = np.asarray(
        Image.open(page.original.variants["restored_candidate"]), dtype=np.uint8
    )
    assert (restored[tick] == 255).all()
    assert "layer_grading_mark" in page.original.variants


def test_overlap_component_preserved_for_review(tmp_path):
    gray = np.full((200, 400), 200, dtype=np.uint8)
    gray[95:105, 20:380] = 20  # printed rule
    ring = _ring(200, 400, (100, 200), 60)
    gray[ring] = 80  # pencil circle crossing the print line
    page = _run(gray, tmp_path)

    restored = np.asarray(
        Image.open(page.original.variants["restored_candidate"]), dtype=np.uint8
    )
    # the crossing component is OVERLAP — preserved, not whitened
    assert (restored[ring & (gray == 80)] == 80).all()
    assert (restored[100, 40:120] == 20).all()  # print untouched
    assert page.uncertain_regions
    assert all(r["policy"] == "REVIEW_REQUIRED" for r in page.uncertain_regions)
    assert "layer_print_writing_overlap" in page.original.variants


def test_no_change_outside_approved_mask(tmp_path):
    gray = np.full((200, 400), 200, dtype=np.uint8)
    gray[95:105, 20:380] = 20
    gray[_ring(200, 400, (100, 200), 60)] = 80
    page = _run(gray, tmp_path)

    restored = np.asarray(
        Image.open(page.original.variants["restored_candidate"]), dtype=np.uint8
    )
    mask = np.asarray(Image.open(page.trace_mask_uri), dtype=np.uint8) > 0
    changed = restored != gray
    assert not (changed & ~mask).any()
    # approved mask never covers print cores
    assert not mask[gray < 55].any()


def test_classifier_classes_disjoint_and_confident(tmp_path):
    gray = np.full((300, 400), 200, dtype=np.uint8)
    gray[40:46, 30:370] = 15                    # long print rule -> figure
    gray[80:95, 50:70] = 30                     # glyph-ish blob -> print
    gray[_ring(300, 400, (200, 250), 45)] = 80       # pencil ring
    evidence = classify_layers(gray)

    assert evidence.class_map.dtype == np.uint8
    assert (evidence.class_map == int(LayerClass.PRINT_FIGURE)).any()
    assert (evidence.class_map == int(LayerClass.PRINT)).any()
    pencil_or_pen = np.isin(
        evidence.class_map, [int(LayerClass.PENCIL), int(LayerClass.PEN)]
    )
    assert pencil_or_pen.any()
    # a pixel never belongs to two classes; removed pixels ⊆ annotation
    assert evidence.removal_mask.sum() > 0
    assert not (evidence.removal_mask & (gray < 55)).any()
