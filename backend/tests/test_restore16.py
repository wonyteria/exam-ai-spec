"""RESTORE-16 — EvidenceDNA bundles + native-PDF source observer.

Locks: candidates are classified into SOURCE / OBSERVATION /
CONSISTENCY / HUMAN; every settled ATU records its bundle; the
consensus policy itself is unchanged (provider-key independence); a
DIGITAL page's native text layer feeds question items as a
"native_pdf" source observer.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from document.evidence import (
    EvidenceClass,
    bundle_for,
    classify_candidate,
)
from document.models import (
    ATU,
    ATUKind,
    Candidate,
    Document,
    Page,
    PageImage,
    PdfPageInventory,
    VerificationStatus,
)


def _cand(provider):
    return Candidate(provider=provider, value="v", confidence=0.9)


def test_evidence_classes():
    assert classify_candidate(_cand("paddleocr")) is EvidenceClass.OBSERVATION
    assert classify_candidate(_cand("reference:hwp")) is EvidenceClass.SOURCE
    assert classify_candidate(_cand("native_pdf")) is EvidenceClass.SOURCE
    assert classify_candidate(_cand("pdf_text")) is EvidenceClass.SOURCE
    assert classify_candidate(_cand("math_checker")) is EvidenceClass.CONSISTENCY
    assert classify_candidate(_cand("human")) is EvidenceClass.HUMAN
    assert classify_candidate(_cand("")) is EvidenceClass.OBSERVATION


def test_bundle_counts_classes():
    b = bundle_for(
        [_cand("paddleocr"), _cand("native_pdf"), _cand("human"), _cand("openai")]
    )
    assert b.observation == 2
    assert b.source == 1
    assert b.human == 1
    assert b.consistency == 0
    assert set(b.classes_present()) == {
        EvidenceClass.OBSERVATION,
        EvidenceClass.SOURCE,
        EvidenceClass.HUMAN,
    }


def test_atu_records_evidence_bundle(tmp_path):
    from core.examdna.context import PipelineContext, Providers
    from core.examdna.source_truth import consensus
    from document.models import Question, QuestionType
    from jobs.models import Job

    doc = Document(tenant_id="t")
    q = Question(number=1, type=QuestionType.MULTIPLE_CHOICE)
    atu = ATU(kind=ATUKind.POINTS, field="points")
    atu.candidates = [
        Candidate(provider="paddleocr", value=3, confidence=0.9),
        Candidate(provider="native_pdf", value=3, confidence=1.0),
    ]
    q.atus.append(atu)
    doc.questions.append(q)

    ctx = PipelineContext(
        document=doc,
        job=Job(id="j", document_id=doc.id),
        store=None,
        workdir=tmp_path,
        providers=Providers(),
        event_sink=lambda *a: None,
    )
    consensus.run(ctx)
    assert atu.status == VerificationStatus.AUTO_VERIFIED
    assert atu.evidence == {
        "source": 1,
        "observation": 1,
        "consistency": 0,
        "human": 0,
    }


def test_native_pdf_items_segment_digital_page(tmp_path):
    from core.examdna.recognition.runner import _native_pdf_items
    from document.models import BBox

    # page 595x842 pt (A4) rendered at scale 2 → 1190x1684 px
    inv = PdfPageInventory(
        page_index=0,
        width_pt=595.0,
        height_pt=842.0,
        text_chars=100,
        pdf_class="DIGITAL",
        native_fragments=[
            {"text": "1. 다음을 계산하시오", "bbox_pt": [50, 700, 300, 720]},
            {"text": "① 3", "bbox_pt": [60, 670, 150, 690]},
            {"text": "② 4", "bbox_pt": [60, 640, 150, 660]},
        ],
    )
    page = Page(
        index=0,
        original=PageImage(uri="x"),
        width=1190.0,
        height=1684.0,
        inventory=inv,
    )
    items = _native_pdf_items(page)
    assert len(items) == 1
    assert items[0]["label"] == "1"
    assert items[0]["choices"] == {"①": "3", "②": "4"}


def test_native_pdf_skips_scanned_and_geometryless(tmp_path):
    from core.examdna.recognition.runner import _native_pdf_items
    from document.models import BBox

    scanned = PdfPageInventory(
        page_index=0, pdf_class="SCANNED", text_chars=0,
        native_fragments=[{"text": "x", "bbox_pt": [0, 0, 10, 10]}],
    )
    page = Page(index=0, original=PageImage(uri="x"),
                width=100, height=100, inventory=scanned)
    assert _native_pdf_items(page) == []
    # DIGITAL but no raster geometry — honest empty
    inv = PdfPageInventory(
        page_index=0, pdf_class="DIGITAL", width_pt=595, height_pt=842,
        text_chars=50,
        native_fragments=[{"text": "1. q", "bbox_pt": [0, 0, 10, 10]}],
    )
    page2 = Page(index=0, original=PageImage(uri="x"), inventory=inv)
    assert _native_pdf_items(page2) == []
