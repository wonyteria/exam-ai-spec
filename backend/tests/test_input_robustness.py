"""Damaged-input robustness: arbitrary uploads must degrade to
per-page warnings/review, never to a crashed job or a lost batch."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from core.examdna import preprocessing
from core.examdna.preprocessing import MAX_NORMALIZED_SIDE
from core.examdna.student_trace import separator
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


def test_corrupt_image_page_isolated(tmp_path):
    """A truncated/corrupt upload marks its page, not the whole job."""
    bad = tmp_path / "torn.jpg"
    bad.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)  # broken jpeg
    good = tmp_path / "ok.png"
    Image.fromarray(np.full((100, 200, 3), 220, np.uint8)).save(good)

    doc = Document(tenant_id="t")
    doc.pages.append(Page(index=0, original=PageImage(uri=str(bad))))
    doc.pages.append(Page(index=1, original=PageImage(uri=str(good))))
    ctx = _ctx(doc, tmp_path / "work")
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    preprocessing.run(ctx)

    assert doc.pages[0].processing_error  # marked, skipped
    assert "grayscale" in doc.pages[1].original.variants  # rest survives


def test_oversized_photo_is_capped_and_invertible(tmp_path):
    """A 12MP phone photo is normalized down and the scale is recorded."""
    big = np.full((3000, 4100, 3), 210, np.uint8)
    p = tmp_path / "photo.jpg"
    Image.fromarray(big).save(p)
    doc = Document(tenant_id="t")
    page = Page(index=0, original=PageImage(uri=str(p)))
    doc.pages.append(page)
    ctx = _ctx(doc, tmp_path / "work")
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    preprocessing.run(ctx)

    assert max(page.width, page.height) <= MAX_NORMALIZED_SIDE
    step = next(
        s for s in page.transform_chain if s.kind == "normalize_scale"
    )
    assert step.params["from_width"] == 4100
    # inverse mapping is exact to within rounding
    assert abs(step.params["scale"] * 4100 - page.width) <= 1


def test_separator_page_failure_does_not_kill_batch(tmp_path, monkeypatch):
    """A page that explodes inside separation is marked; the next page
    still gets its restored candidate."""
    pages = []
    for i, v in enumerate((210, 210)):
        p = tmp_path / f"p{i}.png"
        Image.fromarray(np.full((120, 200), v, np.uint8)).save(p)
        gp = tmp_path / f"p{i}_g.png"
        Image.fromarray(np.full((120, 200), v, np.uint8)).save(gp)
        pages.append(
            Page(
                index=i,
                original=PageImage(uri=str(p), variants={"grayscale": str(gp)}),
            )
        )
    doc = Document(tenant_id="t")
    doc.pages.extend(pages)
    ctx = _ctx(doc, tmp_path / "work")
    ctx.workdir.mkdir(parents=True, exist_ok=True)

    real = separator.classify_layers

    def boom(gray, rgb):
        page_call[0] += 1
        if page_call[0] == 1:
            raise RuntimeError("kaboom")
        return real(gray, rgb)

    page_call = [0]
    monkeypatch.setattr(separator, "classify_layers", boom)
    separator.run(ctx)

    assert "trace_separation_failed" in (doc.pages[0].processing_error or "")
    assert "restored_candidate" in doc.pages[1].original.variants


def test_trace_provider_parses_malformed_and_orientation(tmp_path):
    """Provider output is untrusted: bad JSON → empty traces; the
    upside-down flag is surfaced for review."""
    from providers.local.trace import LocalVisionTraceProvider

    class _Resp:
        def __init__(self, text):
            msg = type("M", (), {"content": text})()
            self.choices = [type("C", (), {"message": msg})()]

    class FakeClient:
        def __init__(self, text):
            def create(**kw):
                return _Resp(text)

            self.chat = type(
                "Chat",
                (),
                {"completions": type("Comp", (), {"create": staticmethod(create)})()},
            )()

    img = tmp_path / "p.png"
    Image.fromarray(np.full((60, 80, 3), 220, np.uint8)).save(img)

    prov = LocalVisionTraceProvider(client=FakeClient("not json"))
    prov._cache_on = False
    out = prov.detect_traces(img)
    assert out.value["traces"] == []

    prov = LocalVisionTraceProvider(
        client=FakeClient(
            '{"traces": [{"x": 10, "y": 20, "w": 30, "h": 40,'
            ' "kind": "mark"}], "upside_down": true}'
        )
    )
    prov._cache_on = False
    out = prov.detect_traces(img)
    assert out.value["upside_down"] is True
    assert len(out.value["traces"]) == 1


def test_trace_box_sanitization(tmp_path):
    """Out-of-range / degenerate provider boxes are dropped, not trusted."""
    from core.examdna.student_trace.separator import _provider_trace_boxes
    from document.models import Candidate

    class WeirdProvider:
        name = "weird"

        def detect_traces(self, image):
            return Candidate(
                provider=self.name,
                value={
                    "traces": [
                        {"x": -50, "y": -50, "w": 200, "h": 200},  # clipped
                        {"x": 0, "y": 0, "w": 0, "h": 10},          # degenerate
                        {"x": 0, "y": 0, "w": 2000, "h": 2000},     # whole page
                        "garbage",
                        {"x": 10, "y": 10, "w": 50, "h": 50},
                    ]
                },
            )

    doc = Document(tenant_id="t")
    page = Page(index=0, original=PageImage(uri="x"))
    doc.pages.append(page)
    ctx = _ctx(doc, tmp_path / "work")
    ctx.providers.trace.append(WeirdProvider())
    boxes = _provider_trace_boxes(ctx, page, (1000, 1000))
    assert len(boxes) == 2  # clipped ok + the valid small one
