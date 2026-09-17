from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import jobs.runner as runner
from core.examdna import Providers
from document.models import Candidate, Document
from jobs.models import Job, JobState
from jobs.runner import run_pipeline


class FakeVision:
    name = "fake-vision"

    def detect_regions(self, image: Path):
        return [
            Candidate(
                provider=self.name,
                confidence=0.9,
                value={
                    "number": 6,
                    "bbox": {"ymin": 100, "xmin": 100, "ymax": 500, "xmax": 900},
                },
            )
        ]

    def describe(self, image, region=None):
        return []


class FakeOCR:
    name = "fake-ocr"

    def recognize_text(self, image: Path, region=None):
        return [
            Candidate(
                provider=self.name,
                confidence=0.95,
                meta={"structured": True},
                value={
                    "number": 6,
                    "type": "multiple_choice",
                    "points": 4,
                    "body": "다음 중 $x^2=4$의 해는?",
                    "choices": {"①": "-2", "②": "0", "③": "2", "④": "4"},
                    "equations": ["x^2=4"],
                },
            )
        ]


class FakeSolver:
    name = "fake-solver"

    def solve(self, problem):
        return Candidate(
            provider=self.name,
            confidence=0.9,
            value={"solved": True, "answer": "②", "steps": ["x=±2", "보기 중 ②"]},
        )


@pytest.fixture()
def fake_providers(monkeypatch):
    providers = Providers(
        ocr=[FakeOCR()],
        vision=[FakeVision()],
        math_ocr=[],
        reasoning=[],
        solver=[FakeSolver()],
    )
    monkeypatch.setattr(runner, "default_providers", lambda: providers)


def test_recognition_to_verified_final(store, sample_png, fake_providers):
    doc = Document()
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))
    uploads = store.job_dir(job.id) / "uploads"
    uploads.mkdir(parents=True)
    shutil.copy(sample_png, uploads / "page1.png")

    run_pipeline(store, job.id)

    finished = store.get_job(job.id)
    assert finished.state == JobState.COMPLETED, finished.error

    result = store.load_document(doc.id)
    assert result.verification.status == "VERIFIED_FINAL"

    (q,) = result.questions
    assert q.number == 1  # positional index; printed number lives in label
    assert q.label == "6"
    assert q.points == 4
    assert q.body[0].text == "다음 중 $x^2=4$의 해는?"
    assert [c.label for c in q.choices] == ["①", "②", "③", "④"]
    assert q.choices[1].body[0].text == "0"
    assert q.equations[0].latex == "x^2=4"
    assert q.answer.value == "②"
    assert q.solution.steps[0].text == "x=±2"

    bbox = q.source.bbox
    assert bbox is not None
    assert bbox.x == pytest.approx(48)  # 80px detected - 4% padding
    assert bbox.w == pytest.approx(704)


def test_low_confidence_candidate_stays_unverified(store, sample_png, monkeypatch):
    class LowConfOCR(FakeOCR):
        def recognize_text(self, image, region=None):
            cand = super().recognize_text(image, region)[0]
            cand.confidence = 0.5
            return [cand]

    monkeypatch.setattr(
        runner,
        "default_providers",
        lambda: Providers(
            ocr=[LowConfOCR()], vision=[FakeVision()], math_ocr=[], reasoning=[], solver=[]
        ),
    )

    doc = Document()
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))
    uploads = store.job_dir(job.id) / "uploads"
    uploads.mkdir(parents=True)
    shutil.copy(sample_png, uploads / "page1.png")
    run_pipeline(store, job.id)

    result = store.load_document(doc.id)
    assert result.verification.status == "NEEDS_REVIEW"
    assert result.verification.gate["unverified"] > 0
    assert result.questions[0].body == []
