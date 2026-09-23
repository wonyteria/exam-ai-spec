"""RESTORE-15 variant routing — same-space variants as OCR fallback.

`deskewed` lives in a rotated coordinate space and is deliberately NOT
routed; same-pixel-space variants (shadow_free, high_contrast) are
retried when the clean image fails to yield adequate extraction.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from core.examdna import PipelineContext, Providers
from core.examdna.recognition import runner as recognition_runner
from document.models import (
    ATUKind, BBox, Candidate, Document, Page, PageImage, Question,
    SourceRef,
)


class VariantAwareOCR:
    """Reads only the shadow_free variant — simulates an engine whose
    output improves on the cleaned input."""
    name = "variant-ocr"

    def recognize_text(self, image: Path, region=None):
        if "shadow_free" not in str(image):
            return []
        return [
            Candidate(
                provider=self.name,
                confidence=0.9,
                meta={"structured": True},
                value={"number": 3, "body": "cleaned reading"},
            )
        ]


class CleanOnlyOCR:
    name = "clean-ocr"

    def recognize_text(self, image: Path, region=None):
        return [
            Candidate(
                provider=self.name,
                confidence=0.9,
                meta={"structured": True},
                value={"number": 3, "body": "primary reading"},
            )
        ]


def _ctx(tmp_path: Path, ocr) -> PipelineContext:
    clean = tmp_path / "page_clean.png"
    Image.new("L", (64, 64), 200).save(clean)
    shadow = tmp_path / "page_shadow_free.png"
    Image.new("L", (64, 64), 220).save(shadow)
    deskew = tmp_path / "page_deskewed.png"
    Image.new("L", (64, 64), 220).save(deskew)

    doc = Document()
    page = Page(index=0, original=PageImage(uri=str(clean)), width=64,
                height=64)
    page.clean_uri = str(clean)
    page.original.variants = {
        "shadow_free": str(shadow),
        "deskewed": str(deskew),  # different space — must not be routed
    }
    doc.pages.append(page)
    q = Question(number=1, source=SourceRef(page=0, bbox=BBox(x=0, y=0, w=10, h=10)))
    doc.questions.append(q)

    return PipelineContext(
        document=doc, job=None, store=None, workdir=tmp_path,
        providers=Providers(ocr=[ocr]), event_sink=lambda *a: None,
    )


def test_inadequate_extraction_falls_back_to_same_space_variant(tmp_path):
    ctx = _ctx(tmp_path, VariantAwareOCR())
    recognition_runner.run(ctx)

    (q,) = ctx.document.questions
    bodies = [a for a in q.atus if a.field == "body"]
    assert bodies, "variant fallback should have produced a body ATU"
    cand = bodies[0].candidates[0]
    assert cand.value == "cleaned reading"
    assert cand.meta.get("variant") == "shadow_free"


def test_adequate_primary_skips_variants(tmp_path):
    ctx = _ctx(tmp_path, CleanOnlyOCR())
    recognition_runner.run(ctx)

    (q,) = ctx.document.questions
    assert all(
        "variant" not in c.meta
        for a in q.atus for c in a.candidates
    )


def test_deskewed_variant_never_routed(tmp_path):
    seen = []

    class SpyOCR(CleanOnlyOCR):
        name = "spy-ocr"

        def recognize_text(self, image, region=None):
            seen.append(str(image))
            return []  # stay inadequate so every variant is tried

    ctx = _ctx(tmp_path, SpyOCR())
    recognition_runner.run(ctx)

    names = [Path(p).name for p in seen]
    assert names and not any("deskewed" in n for n in names)
    assert any("shadow_free" in n for n in names)
