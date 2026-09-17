from __future__ import annotations

import shutil
from pathlib import Path

from document.models import Document
from jobs.models import Job, JobState
from jobs.runner import run_pipeline


def test_full_pipeline_skeleton(store, sample_png):
    doc = Document()
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))

    uploads = store.job_dir(job.id) / "uploads"
    uploads.mkdir(parents=True)
    shutil.copy(sample_png, uploads / "page1.png")

    run_pipeline(store, job.id)

    finished = store.get_job(job.id)
    assert finished.state == JobState.NEEDS_REVIEW
    assert finished.error is None

    result = store.load_document(doc.id)
    assert len(result.pages) == 1
    assert "grayscale" in result.pages[0].original.variants
    assert result.verification.status == "NEEDS_REVIEW"
    assert result.verification.gate is not None
    assert result.verification.gate["document_empty"] is True

    exports = store.export_dir(doc.id)
    assert (exports / "exam.hwpx").exists()
    assert (exports / "preview.html").exists()


def test_hwpx_is_valid_zip(store, sample_png):
    import zipfile

    doc = Document()
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))
    uploads = store.job_dir(job.id) / "uploads"
    uploads.mkdir(parents=True)
    shutil.copy(sample_png, uploads / "page1.png")
    run_pipeline(store, job.id)

    hwpx = store.export_dir(doc.id) / "exam.hwpx"
    with zipfile.ZipFile(hwpx) as zf:
        names = set(zf.namelist())
        assert "Contents/section0.xml" in names
        assert "Contents/header.xml" in names
        assert "Contents/content.hpf" in names
        assert zf.read("mimetype") == b"application/hwp+zip"
