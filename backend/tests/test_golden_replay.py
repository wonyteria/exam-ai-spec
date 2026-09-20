from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import jobs.runner as runner
from core.examdna import Providers
from document.models import Document
from jobs.models import Job, JobState
from jobs.runner import run_pipeline
from tests.golden.replay import CacheReplayProvider

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "golden_001"

pytestmark = pytest.mark.skipif(
    not (SAMPLES / "expected.json").exists(), reason="golden fixtures missing"
)


@pytest.fixture()
def replay_providers(monkeypatch):
    """CacheReplayProvider backed by the golden response cache — deterministic,
    offline, no SDK import, and any cache miss raises CacheMiss (A34)."""
    provider = CacheReplayProvider(SAMPLES / "cache")
    providers = Providers(
        ocr=[provider],
        vision=[provider],
        math_ocr=[],
        reasoning=[],
        solver=[provider],
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

    # RESTORE-05: a single replay provider is one evidence source, so ATUs
    # stay UNVERIFIED and content is asserted at the candidate level —
    # the recorded extraction is still checked value-for-value, but it may
    # not silently finalize into the canonical document.
    def candidate_values(q, field):
        return {
            repr(c.value)
            for a in q.atus
            if a.field == field
            for c in a.candidates
        }

    for got, want in zip(result.questions, expected["questions"]):
        assert (got.label or str(got.number)) == str(want["label"] or want["number"])
        for label, text in (want["choices"] or {}).items():
            assert repr(text) in candidate_values(got, f"choice:{label}"), (
                f"q{want['number']} choice {label} missing from candidates"
            )
        if want.get("points") is not None:
            assert repr(want["points"]) in candidate_values(got, "points")
        assert all(
            a.status.value in ("UNVERIFIED", "CONFLICT")
            for a in got.atus
        )
