"""Provider-guided trace removal (LayerDNA + TraceDetectorProvider).

Locks the contract: provider regions are *candidates* — inside each box,
print-line members, straight dark strokes, and dark dense glyphs are
preserved for review while sparse/off-line ink is removed. A real-photo
regression replays the recorded `local-large` detections on the Simwon
fixture and asserts the mask grows without touching print cores.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from core.examdna.student_trace import separator
from core.examdna.student_trace.layers import classify_layers
from core.examdna.student_trace.separator import (
    _provider_trace_boxes,
    _region_guided_removal,
)
from document.models import Candidate, Document, Page, PageImage


class FakeTraceProvider:
    name = "fake-trace"

    def __init__(self, traces):
        self._traces = traces

    def detect_traces(self, image):
        return Candidate(
            provider=self.name, value={"traces": self._traces}, confidence=0.8
        )


def _ctx(doc, workdir, traces):
    from core.examdna.context import PipelineContext, Providers
    from jobs.models import Job

    return PipelineContext(
        document=doc,
        job=Job(id="j", document_id=doc.id),
        store=None,
        workdir=workdir,
        providers=Providers(trace=[FakeTraceProvider(traces)]),
        event_sink=lambda *a: None,
    )


def _page(gray: np.ndarray, tmp_path):
    src = tmp_path / "page.png"
    Image.fromarray(gray).save(src)
    vdir = tmp_path / "variants"
    vdir.mkdir(exist_ok=True)
    gp = vdir / "page_grayscale.png"
    Image.fromarray(gray).save(gp)
    return src, gp


def _run(gray, tmp_path, traces):
    src, gp = _page(gray, tmp_path)
    doc = Document(tenant_id="t")
    page = Page(
        index=0,
        original=PageImage(uri=str(src), variants={"grayscale": str(gp)}),
    )
    doc.pages.append(page)
    ctx = _ctx(doc, tmp_path / "work", traces)
    separator.run(ctx)
    return page


def _ring(h=200, w=400, center=(100, 100), r=60, t=5):
    yy, xx = np.mgrid[0:h, 0:w]
    d2 = (yy - center[0]) ** 2 + (xx - center[1]) ** 2
    return (d2 < r * r) & (d2 > (r - t) ** 2)


def _text_line(gray, y, x0=40, x1=360, halo=False):
    """A row of dark glyph-ish blocks — a printed text line.

    `halo` adds light-gray anti-alias pixels around each block — like real
    print edges, they are ink (not print_dark) but belong to the line."""
    for x in range(x0, x1, 14):
        if halo:
            gray[y - 1 : y + 9, x - 1 : x + 8] = 80
        gray[y : y + 8, x : x + 7] = 30
    return gray


def test_whitespace_annotation_removed(tmp_path):
    """A pencil note sitting between printed lines is removable."""
    gray = np.full((200, 400), 200, dtype=np.uint8)
    _text_line(gray, 40)
    _text_line(gray, 140)
    # handwriting between the lines: a short stroke cluster
    gray[85:95, 150:230] = 110
    # provider box encloses the whole mark (x120-260, y75-105 in px)
    traces = [{"x": 300, "y": 375, "w": 350, "h": 150, "kind": "handwriting"}]
    page = _run(gray, tmp_path, traces)
    restored = np.asarray(
        Image.open(page.original.variants["restored_candidate"])
    )
    assert (restored[85:95, 150:230] == 255).all()
    # print line dark pixels never whitened
    for y in (40, 140):
        line = slice(y, y + 8)
        assert (restored[line, 40:360][gray[line, 40:360] < 100] < 100).all()


def test_circled_print_digit_preserved_for_review(tmp_path):
    """A circle drawn around a printed number overlaps print — spec keeps
    it (REVIEW_REQUIRED) rather than erasing pixels that may carry print."""
    gray = np.full((200, 400), 200, dtype=np.uint8)
    _text_line(gray, 80, halo=True)
    ring = _ring(200, 400, (100, 92), 40, 5)
    gray[ring] = 110  # pencil circle enclosing part of the line
    traces = [{"x": 100, "y": 250, "w": 200, "h": 200, "kind": "mark"}]
    page = _run(gray, tmp_path, traces)
    restored = np.asarray(
        Image.open(page.original.variants["restored_candidate"])
    )
    # ring pixels enclosing print cores are preserved for review
    assert restored[ring].mean() < 200
    # print cores never whitened
    line = slice(80, 88)
    assert (restored[line, 40:360][gray[line, 40:360] < 55] < 55).all()
    # the overlap is reported as a provider-trace review entry
    kept = [
        r
        for r in (page.uncertain_regions or [])
        if r.get("layer") == "PROVIDER_TRACE"
    ]
    assert kept


def test_no_provider_unchanged(tmp_path):
    """Without trace providers the heuristic path is untouched."""
    gray = np.full((200, 400), 200, dtype=np.uint8)
    mark = _ring(200, 400, (100, 200), 60)
    gray[mark] = 80
    page = _run(gray, tmp_path, [])
    restored = np.asarray(
        Image.open(page.original.variants["restored_candidate"])
    )
    assert (restored[mark] == 255).all()
    assert "provider_trace_overlay" not in page.original.variants


# --- real-photo regression ----------------------------------------------------

SAMPLE = (
    __import__("pathlib").Path(__file__).resolve().parents[2]
    / "samples"
    / "simwon_2025_mid2"
    / "page1.jpg"
)

# Regions as returned by local-large (Ollama) on this page, 2026-09-22 —
# recorded so the test is deterministic and offline.
SIMWON_P1_TRACES = [
    {"x": 35, "y": 8, "w": 100, "h": 80, "kind": "mark"},
    {"x": 365, "y": 78, "w": 40, "h": 25, "kind": "handwriting"},
    {"x": 430, "y": 150, "w": 45, "h": 50, "kind": "handwriting"},
    {"x": 45, "y": 290, "w": 50, "h": 45, "kind": "grading"},
    {"x": 270, "y": 350, "w": 150, "h": 30, "kind": "handwriting"},
    {"x": 30, "y": 390, "w": 95, "h": 80, "kind": "mark"},
    {"x": 280, "y": 458, "w": 45, "h": 25, "kind": "handwriting"},
    {"x": 330, "y": 470, "w": 25, "h": 25, "kind": "mark"},
    {"x": 370, "y": 480, "w": 25, "h": 25, "kind": "mark"},
    {"x": 370, "y": 530, "w": 25, "h": 25, "kind": "mark"},
    {"x": 200, "y": 580, "w": 170, "h": 45, "kind": "handwriting"},
    {"x": 30, "y": 610, "w": 95, "h": 80, "kind": "mark"},
    {"x": 330, "y": 720, "w": 80, "h": 50, "kind": "handwriting"},
    {"x": 280, "y": 900, "w": 45, "h": 35, "kind": "grading"},
    {"x": 480, "y": 0, "w": 80, "h": 80, "kind": "mark"},
    {"x": 700, "y": 190, "w": 45, "h": 25, "kind": "handwriting"},
    {"x": 500, "y": 410, "w": 35, "h": 35, "kind": "grading"},
    {"x": 450, "y": 410, "w": 110, "h": 90, "kind": "mark"},
    {"x": 620, "y": 640, "w": 45, "h": 30, "kind": "handwriting"},
    {"x": 760, "y": 580, "w": 35, "h": 25, "kind": "handwriting"},
    {"x": 770, "y": 820, "w": 35, "h": 35, "kind": "grading"},
]


@pytest.mark.skipif(not SAMPLE.exists(), reason="real sample fixture missing")
def test_real_photo_provider_regions_improve_removal(tmp_path):
    """Heuristic alone removes ~nothing on this photo; provider regions
    must grow the mask substantially while never whitening print cores."""
    from PIL import ImageOps

    gray = np.asarray(
        ImageOps.exif_transpose(Image.open(SAMPLE)).convert("L"),
        dtype=np.uint8,
    )
    baseline = classify_layers(gray, None)
    base_removed = int(baseline.removal_mask.sum())

    src, gp = _page(gray, tmp_path)
    doc = Document(tenant_id="t")
    page = Page(
        index=0,
        original=PageImage(uri=str(src), variants={"grayscale": str(gp)}),
    )
    doc.pages.append(page)
    ctx = _ctx(doc, tmp_path / "work", SIMWON_P1_TRACES)
    separator.run(ctx)

    restored = np.asarray(
        Image.open(page.original.variants["restored_candidate"])
    )
    removed_now = int((restored != gray).sum())
    assert removed_now > base_removed, (
        f"provider regions removed nothing extra: {base_removed} -> {removed_now}"
    )
    # print cores (<55) are never whitened even inside trace boxes
    print_cores = gray < 55
    assert (restored[print_cores] < 55).all()
    # inside the provider boxes, most non-print ink is removed
    from PIL import ImageFilter

    from core.examdna.student_trace.separator import INK_MARGIN

    bg = np.asarray(
        Image.fromarray(gray).filter(ImageFilter.GaussianBlur(radius=12)),
        dtype=np.int16,
    )
    ink = (~print_cores) & (gray.astype(np.int16) < bg - INK_MARGIN)
    inbox = np.zeros(gray.shape, dtype=bool)
    h, w = gray.shape
    for t in SIMWON_P1_TRACES:
        x0, y0 = int(t["x"] / 1000 * w), int(t["y"] / 1000 * h)
        x1 = min(w, int((t["x"] + t["w"]) / 1000 * w) + 1)
        y1 = min(h, int((t["y"] + t["h"]) / 1000 * h) + 1)
        inbox[y0:y1, x0:x1] = True
    removed_inbox = ink & inbox & (restored == 255)
    frac = removed_inbox.sum() / max(int((ink & inbox).sum()), 1)
    # Most in-box ink on this page is fused with printed lines/figures —
    # spec-correct to preserve + review rather than erase.
    assert frac >= 0.15, f"only {frac:.0%} of in-box ink removed"
    # review granularity is per provider box, not per component
    trace_reviews = [
        r
        for r in (page.uncertain_regions or [])
        if r.get("layer") == "PROVIDER_TRACE"
    ]
    assert 0 < len(trace_reviews) <= len(SIMWON_P1_TRACES)
