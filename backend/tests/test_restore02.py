"""RESTORE-02 — recognition providers emit candidates, never final values.

Covers: lazy local PaddleOCR adapter (provenance meta, unavailable path),
env-gated factories, and mock providers driving the real pipeline stages
end-to-end without network/model weights.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from document.models import BBox, Candidate


def _img(path: Path, size=(200, 100)) -> Path:
    Image.new("RGB", size, "white").save(path)
    return path


# --- paddle adapter ------------------------------------------------------------


class _FakeEngineV3:
    """Mimics PaddleOCR 3.x predict() output."""

    def predict(self, img):
        return [
            {
                "rec_texts": ["문항 1번", "x + y = 3"],
                "rec_scores": [0.98, 0.87],
                "rec_polys": [
                    [[10, 10], [80, 10], [80, 30], [10, 30]],
                    [[10, 40], [120, 40], [120, 60], [10, 60]],
                ],
            }
        ]


class _FakeEngineV2:
    """Mimics PaddleOCR 2.x ocr() output."""

    def ocr(self, img):
        return [[[[[1, 2], [50, 2], [50, 20], [1, 20]], ("hello", 0.7)]]]


def test_paddle_provider_normalizes_v3(tmp_path):
    from providers.ocr.paddle import PaddleOCRProvider

    img = _img(tmp_path / "p.png")
    p = PaddleOCRProvider(engine=_FakeEngineV3())
    cands = p.recognize_text(img)

    assert [c.value for c in cands] == ["문항 1번", "x + y = 3"]
    assert cands[0].confidence == pytest.approx(0.98)
    meta = cands[0].meta
    assert meta["model"] == "PP-OCRv5"
    assert meta["input_sha256"] == hashlib.sha256(img.read_bytes()).hexdigest()
    assert meta["bbox_px"] == [10.0, 10.0, 80.0, 30.0]
    assert meta["kind"] == "ocr_line"


def test_paddle_provider_normalizes_v2(tmp_path):
    from providers.ocr.paddle import PaddleOCRProvider

    img = _img(tmp_path / "p.png")
    cands = PaddleOCRProvider(engine=_FakeEngineV2()).recognize_text(img)
    assert cands[0].value == "hello"
    assert cands[0].confidence == pytest.approx(0.7)
    assert cands[0].meta["bbox_px"] == [1.0, 2.0, 50.0, 20.0]


def test_paddle_provider_region_crop_offsets_bbox(tmp_path):
    from providers.ocr.paddle import PaddleOCRProvider

    img = _img(tmp_path / "p.png", size=(300, 200))
    p = PaddleOCRProvider(engine=_FakeEngineV3())
    cands = p.recognize_text(img, BBox(x=50, y=60, w=100, h=80))
    # detected box was in crop coords -> offset by region origin
    assert cands[0].meta["bbox_px"] == [60.0, 70.0, 130.0, 90.0]
    assert cands[0].meta["region"] == {"x": 50, "y": 60, "w": 100, "h": 80}


def test_paddle_unavailable_is_explicit(tmp_path):
    pytest.importorskip("PIL")
    try:
        import paddleocr  # noqa: F401

        pytest.skip("paddleocr installed — unavailable path not testable")
    except ImportError:
        pass
    from providers.ocr.paddle import PaddleOCRProvider, PaddleOCRUnavailable

    img = _img(tmp_path / "p.png")
    with pytest.raises(PaddleOCRUnavailable):
        PaddleOCRProvider().recognize_text(img)


def test_factories_default_to_stub_and_opt_in(monkeypatch):
    import providers.ocr as ocr
    import providers.vision as vision

    assert type(ocr.get_provider()).__name__ == "StubOCRProvider"
    assert type(vision.get_provider()).__name__ == "StubVisionProvider"

    monkeypatch.setenv("EXAMDNA_PADDLEOCR", "1")
    monkeypatch.setenv("EXAMDNA_PADDLE_LAYOUT", "1")
    from providers.ocr.paddle import PaddleOCRProvider
    from providers.vision.paddle import PaddleLayoutProvider

    assert isinstance(ocr.get_provider(), PaddleOCRProvider)
    assert isinstance(vision.get_provider(), PaddleLayoutProvider)


# --- mock providers through the real pipeline -------------------------------------


def test_mock_vision_drives_segmentation_and_recognition(tmp_path):
    """A mocked extract_page must produce questions + field ATUs through
    the real segmenter/runner/consensus — proving the candidate path
    end-to-end without any model."""
    from core.examdna import pipeline
    from core.examdna.context import PipelineContext, Providers
    from document.models import Document, Page, PageImage, VerificationStatus
    from jobs.models import Job
    from providers.mock import MockVisionProvider

    img = _img(tmp_path / "p1.png", size=(1000, 1400))
    doc = Document(tenant_id="t")
    doc.pages.append(
        Page(index=0, original=PageImage(uri=str(img)), width=1000, height=1400)
    )

    items = [
        {
            "label": "1",
            "bbox": {"xmin": 50, "ymin": 100, "xmax": 450, "ymax": 400},
            "type": "multiple_choice",
            "points": 4,
            "body": "다음 중 옳은 것은?",
            "choices": {"①": "가", "②": "나"},
        }
    ]
    ctx = PipelineContext(
        document=doc,
        job=Job(id="j", document_id=doc.id),
        store=None,
        workdir=tmp_path / "work",
        providers=Providers(vision=[MockVisionProvider(items=items)]),
        event_sink=lambda *a: None,
    )
    for contract in pipeline.STAGES:
        if contract.name in ("segmentation", "recognition", "source_verification"):
            contract.fn(ctx)

    assert len(doc.questions) == 1
    q = doc.questions[0]
    assert q.label == "1"
    fields = {a.field for a in q.atus}
    assert {"number", "type", "points", "body", "choice:①", "choice:②"} <= fields
    # RESTORE-05: a single source — however confident — never auto-verifies.
    assert all(a.status == VerificationStatus.UNVERIFIED for a in q.atus)
    assert all(a.note == "single_source" for a in q.atus)


def test_mock_ocr_region_calls_are_candidates(tmp_path):
    from providers.mock import MockOCRProvider

    img = _img(tmp_path / "p.png")
    p = MockOCRProvider(lines=[{"text": "가", "confidence": 0.5, "bbox": [0, 0, 5, 5]}])
    cands = p.recognize_text(img, BBox(x=0, y=0, w=50, h=50))
    assert len(cands) == 1
    assert cands[0].confidence == 0.5
    assert cands[0].meta["mock"] is True
