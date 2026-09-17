from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import jobs.runner as runner
import providers.gemini.provider as gp
from core.examdna import Providers
from document.models import Document
from jobs.models import Job, JobState
from jobs.runner import run_pipeline
from providers.gemini.provider import GeminiProvider

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "golden_001"

pytestmark = pytest.mark.skipif(
    not (SAMPLES / "expected.json").exists(), reason="golden fixtures missing"
)


@pytest.fixture()
def replay_providers(monkeypatch):
    """Real GeminiProvider backed by the golden response cache — deterministic,
    offline, and any cache miss fails loudly (fixture drift detection)."""
    monkeypatch.setattr(gp, "CACHE_DIR", SAMPLES / "cache")
    monkeypatch.setattr(gp, "MIN_INTERVAL", 0.0)
    monkeypatch.setenv("GEMINI_API_KEY", "golden-replay")
    providers = Providers(
        ocr=[GeminiProvider("gemini-3.1-flash-lite")],
        vision=[GeminiProvider("gemini-3.1-flash-lite")],
        math_ocr=[],
        reasoning=[],
        solver=[GeminiProvider("gemini-3.1-flash-lite")],
    )
    monkeypatch.setattr(runner, "default_providers", lambda: providers)


def test_golden_replay(store, replay_providers):
    doc = Document()
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))
    uploads = store.job_dir(job.id) / "uploads"
    uploads.mkdir(parents=True)
    for img in sorted(SAMPLES.glob("page*.jpg")):
        shutil.copy(img, uploads / img.name)

    run_pipeline(store, job.id)

    finished = store.get_job(job.id)
    assert finished.state in (JobState.COMPLETED, JobState.NEEDS_REVIEW), finished.error

    expected = json.loads((SAMPLES / "expected.json").read_text(encoding="utf-8"))
    result = store.load_document(doc.id)
    assert result.verification.status == expected["expected_status"]
    assert len(result.questions) == len(expected["questions"])

    for got, want in zip(result.questions, expected["questions"]):
        assert (got.label or str(got.number)) == str(want["label"] or want["number"])
        assert [c.label for c in got.choices] == list((want["choices"] or {}).keys())
        if want["answer"] is not None:
            assert got.answer is not None
            assert got.answer.value == want["answer"]
