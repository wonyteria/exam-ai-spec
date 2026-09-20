"""RESTORE-18 (spec) — ReconstructionDNA occlusion policy.

Locks: every uncertain region gets an explicit decision;
RESTORE_REFERENCE requires a reference:* bbox covering >=90% of the
occlusion and records proof hashes; occluded print without reference
is REVIEW_REQUIRED and blocks the release gate; no generative
inpainting path exists.
"""
from __future__ import annotations

from core.examdna.reconstruction.engine import decide_region, run
from document.models import Document, Page, PageImage
from document.verification import evaluate_gate


def _page(regions):
    p = Page(index=0, original=PageImage(uri="mem://p0.png", sha256="x"))
    p.uncertain_regions = regions
    return p


def test_non_overlap_region_is_preserved():
    d = decide_region(
        {"kind": "uncertain", "bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
         "overlaps_print": False},
        references=[],
    )
    assert d["decision"] == "PRESERVE_ORIGINAL"


def test_occluded_without_reference_needs_review():
    d = decide_region(
        {"kind": "overlap", "bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
         "overlaps_print": True},
        references=[],
    )
    assert d["decision"] == "REVIEW_REQUIRED"
    assert d["proof"] is None


def test_reference_covering_bbox_restores_with_proof():
    ref = [{
        "reference_bbox": {"x": 0, "y": 0, "w": 12, "h": 12},
        "reference_source": "reference:hwp",
        "raw_output_sha256": "abc123",
    }]
    d = decide_region(
        {"kind": "overlap", "bbox": {"x": 1, "y": 1, "w": 10, "h": 10},
         "overlaps_print": True},
        references=ref,
    )
    assert d["decision"] == "RESTORE_REFERENCE"
    assert d["proof"]["reference_source"] == "reference:hwp"
    assert d["proof"]["occlusion_sha256"]


def test_partial_reference_coverage_not_enough():
    ref = [{
        "reference_bbox": {"x": 100, "y": 100, "w": 10, "h": 10},
        "reference_source": "reference:hwp",
    }]
    d = decide_region(
        {"kind": "overlap", "bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
         "overlaps_print": True},
        references=ref,
    )
    assert d["decision"] == "REVIEW_REQUIRED"


class _Ctx:
    def __init__(self, doc):
        self.document = doc
        self.events = []

    def emit(self, stage, msg, level="info"):
        self.events.append((stage, msg))


def test_run_records_decisions_on_pages():
    doc = Document()
    doc.pages = [_page([
        {"kind": "uncertain", "bbox": {"x": 0, "y": 0, "w": 5, "h": 5},
         "overlaps_print": True},
    ])]
    ctx = _Ctx(doc)
    run(ctx)
    assert doc.pages[0].reconstruction[0]["decision"] == "REVIEW_REQUIRED"


def test_review_required_blocks_gate():
    doc = Document()
    doc.pages = [_page([])]
    doc.pages[0].reconstruction = [
        {"decision": "REVIEW_REQUIRED", "bbox": {}, "kind": "overlap"}
    ]
    report = evaluate_gate(doc, artifact_proof="PASS")
    assert report.reconstruction_pending == 1
    assert not report.passed
