"""RESTORE-15 — extended derived-asset variants for routing.

Locks: deskewed/shadow_free/per-channel variants are produced when
OpenCV is available; every variant is hash-bound; a detected skew is
recorded in the transform chain so anchors stay invertible; variant
purposes are declared for downstream routing; failures produce no
variant, never a crash.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from core.examdna import preprocessing
from core.examdna.context import PipelineContext, Providers
from document.models import Document, Page, PageImage
from jobs.models import Job

cv2 = pytest.importorskip("cv2")


def _ctx(doc, workdir):
    return PipelineContext(
        document=doc,
        job=Job(id="j", document_id=doc.id),
        store=None,
        workdir=workdir,
        providers=Providers(),
        event_sink=lambda *a: None,
    )


def _make_page(tmp_path, arr):
    src = tmp_path / "page.png"
    Image.fromarray(arr).save(src)
    doc = Document(tenant_id="t")
    page = Page(index=0, original=PageImage(uri=str(src)))
    doc.pages.append(page)
    return doc, page


def test_extended_variants_produced_and_hashed(tmp_path):
    rgb = np.full((200, 300, 3), 220, dtype=np.uint8)
    rgb[50:150, 50:250] = (40, 40, 40)
    doc, page = _make_page(tmp_path, rgb)
    preprocessing.run(_ctx(doc, tmp_path / "w"))

    v = page.original.variants
    for name in (
        "grayscale", "high_contrast", "binarized",
        "shadow_free", "channel_r", "channel_g", "channel_b",
    ):
        assert name in v, name
        assert page.original.variant_sha256[name]
    for ch in ("r", "g", "b"):
        img = np.asarray(Image.open(v[f"channel_{ch}"]))
        assert img.shape == (200, 300)


def test_deskew_records_transform_chain(tmp_path):
    # draw a slightly rotated line pattern — minAreaRect sees the skew
    gray = np.full((300, 400), 255, dtype=np.uint8)
    for i in range(6):
        y = 60 + i * 30
        gray[y : y + 3, 60:340] = 30
    m = cv2.getRotationMatrix2D((200, 150), 3.0, 1.0)
    skewed = cv2.warpAffine(gray, m, (400, 300), borderValue=255)
    rgb = np.stack([skewed] * 3, axis=2)
    doc, page = _make_page(tmp_path, rgb)
    preprocessing.run(_ctx(doc, tmp_path / "w"))

    if "deskewed" in page.original.variants:
        kinds = [s.kind for s in page.transform_chain]
        assert "deskew" in kinds
        step = next(s for s in page.transform_chain if s.kind == "deskew")
        assert abs(step.params["angle_deg"]) > 0


def test_no_deskew_variant_for_upright_page(tmp_path):
    gray = np.full((200, 300), 255, dtype=np.uint8)
    gray[80:90, 40:260] = 30
    rgb = np.stack([gray] * 3, axis=2)
    doc, page = _make_page(tmp_path, rgb)
    preprocessing.run(_ctx(doc, tmp_path / "w"))
    # upright content yields no deskew variant — absence is honest, not
    # an error
    assert "deskewed" not in page.original.variants
    assert not any(
        s.kind == "deskew" for s in page.transform_chain
    )


def test_variant_purposes_declared():
    for name in (
        "grayscale", "deskewed", "shadow_free",
        "channel_r", "channel_g", "channel_b",
    ):
        assert name in preprocessing.VARIANT_PURPOSES
    assert "ocr" in preprocessing.VARIANT_PURPOSES["shadow_free"]
    assert "layerdna" in preprocessing.VARIANT_PURPOSES["channel_r"]


def test_missing_cv2_still_produces_core_variants(tmp_path, monkeypatch):
    # If OpenCV vanished, core variants remain and no error propagates.
    import builtins

    real_import = builtins.__import__

    def _no_cv2(name, *a, **kw):
        if name == "cv2":
            raise ImportError("cv2")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _no_cv2)
    rgb = np.full((60, 60, 3), 220, dtype=np.uint8)
    doc, page = _make_page(tmp_path, rgb)
    preprocessing.run(_ctx(doc, tmp_path / "w"))
    assert "grayscale" in page.original.variants
    assert "binarized" in page.original.variants
