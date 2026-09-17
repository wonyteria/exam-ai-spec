from __future__ import annotations

import json
import shutil
from pathlib import Path

from document.models import Document
from jobs.models import Job
from jobs.runner import run_pipeline
from tests.golden.harness import compare_golden

EXPECTED = (
    Path(__file__).parent / "golden" / "sample_001" / "expected.json"
)


def test_golden_sample_001_baseline(store, sample_png):
    """Golden harness runs end-to-end; expected data is still human-pending."""
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))

    doc = Document()
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))
    uploads = store.job_dir(job.id) / "uploads"
    uploads.mkdir(parents=True)
    shutil.copy(sample_png, uploads / "page1.png")
    run_pipeline(store, job.id)

    actual = store.load_document(doc.id)
    report = compare_golden(expected, actual)

    assert len(report["questions"]) == 5
    assert {q["number"] for q in report["questions"]} == {6, 7, 8, 9, 10}
    if expected["status"] == "PENDING_HUMAN_CONFIRMATION":
        assert report["missing"] == 5
    else:
        assert not report["regression"]
