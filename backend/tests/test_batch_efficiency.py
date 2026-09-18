"""Tests for the cost-efficient paths: page-level extraction and batch solving.

The whole point is fewer provider calls — these tests pin that behavior down.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import jobs.runner as runner
from core.examdna import Providers
from core.examdna.context import PipelineContext
from core.examdna.verification import solving
from document.models import (
    Candidate,
    Choice,
    Document,
    Question,
    TextSpan,
)
from jobs.models import Job, JobState
from jobs.runner import run_pipeline


def _mc_question(number: int, label: str | None = None) -> Question:
    return Question(
        number=number,
        label=label or str(number),
        body=[TextSpan(text="문제")],
        choices=[
            Choice(label=l, body=[TextSpan(text=t)])
            for l, t in [("①", "1"), ("②", "2"), ("③", "3")]
        ],
    )


def _ctx(store, questions, solver, tmp_path):
    doc = Document()
    doc.questions = questions
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))
    return PipelineContext(
        document=doc,
        job=job,
        store=store,
        workdir=tmp_path,
        providers=Providers(solver=[solver]),
    )


class BatchSolver:
    """solve_batch answers each problem; per-call answers can differ."""

    name = "batch-solver"

    def __init__(self, answers: dict[str, object] | list[dict[str, object]]):
        # answers: one mapping (same both runs) or [run1, run2] mappings
        self.answer_sets = answers if isinstance(answers, list) else [answers, answers]
        self.calls = 0
        self.problems_seen: list[dict] = []

    def solve_batch(self, problems):
        run = min(self.calls, len(self.answer_sets) - 1)
        self.calls += 1
        self.problems_seen = problems
        answers = self.answer_sets[run]
        return [
            Candidate(
                provider=self.name,
                confidence=0.9,
                value=[
                    {
                        "number": p["number"],
                        "solved": p["number"] in answers,
                        "answer": answers.get(p["number"]),
                        "steps": ["step"],
                    }
                    for p in problems
                    if p["number"] in answers
                ],
            )
        ]


def test_batch_solve_consensus(store, tmp_path):
    solver = BatchSolver({"1": "②", "2": "③"})
    qs = [_mc_question(1), _mc_question(2)]
    solving.run(_ctx(store, qs, solver, tmp_path))

    assert solver.calls == 2  # two consensus runs, not 2 per question
    assert [q.answer.value for q in qs] == ["②", "③"]
    assert all(not q.verification.logic_flags for q in qs)


def test_batch_disagreement_flags_ambiguous(store, tmp_path):
    solver = BatchSolver([{"1": "②"}, {"1": "③"}])
    qs = [_mc_question(1)]
    solving.run(_ctx(store, qs, solver, tmp_path))

    assert qs[0].answer is None
    assert qs[0].verification.logic_flags[0].kind == "ambiguous_answer"


def test_batch_missing_falls_back_to_single_solve(store, tmp_path):
    class FallbackSolver(BatchSolver):
        def __init__(self):
            super().__init__({"1": "②"})
            self.single_calls = 0

        def solve(self, problem):
            self.single_calls += 1
            return Candidate(
                provider=self.name,
                confidence=0.9,
                value={"solved": True, "answer": "③", "steps": []},
            )

    solver = FallbackSolver()
    qs = [_mc_question(1), _mc_question(2)]
    solving.run(_ctx(store, qs, solver, tmp_path))

    assert solver.single_calls == 2  # only q2 missing -> 2 consensus single solves
    assert qs[0].answer.value == "②"
    assert qs[1].answer.value == "③"


def test_shared_stem_parent_excluded_and_included(store, tmp_path):
    parent = Question(number=1, label="논술형 1", body=[TextSpan(text="공통 지문")])
    sub = _mc_question(2, label="1-1")
    sub.parent_id = parent.id
    solver = BatchSolver({"1-1": "①"})
    solving.run(_ctx(store, [parent, sub], solver, tmp_path))

    (problem,) = solver.problems_seen
    assert problem["number"] == "1-1"
    assert problem["shared_stem"]["body"] == ["공통 지문"]
    assert parent.answer is None
    assert not parent.verification.logic_flags


class PageExtractVision:
    """One call per page returns regions AND full extraction."""

    name = "page-vision"

    def __init__(self):
        self.extract_calls = 0

    def extract_page(self, image: Path):
        self.extract_calls += 1
        return [
            Candidate(
                provider=self.name,
                confidence=0.9,
                value=[
                    {
                        "label": "1",
                        "bbox": {"ymin": 100, "xmin": 100, "ymax": 500, "xmax": 900},
                        "type": "multiple_choice",
                        "points": 4,
                        "body": "다음 중 $x^2=4$의 해는?",
                        "choices": {"①": "-2", "②": "2"},
                        "equations": ["x^2=4"],
                    }
                ],
            )
        ]

    def describe(self, image, region=None):
        return []


class CountingOCR:
    name = "counting-ocr"

    def __init__(self):
        self.calls = 0

    def recognize_text(self, image: Path, region=None):
        self.calls += 1
        return []


def test_page_extraction_skips_per_question_ocr(
    store, sample_png, tmp_path, monkeypatch
):
    vision = PageExtractVision()
    ocr = CountingOCR()
    monkeypatch.setattr(
        runner,
        "default_providers",
        lambda: Providers(
            ocr=[ocr], vision=[vision], math_ocr=[], reasoning=[], solver=[]
        ),
    )

    doc = Document()
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))
    uploads = store.job_dir(job.id) / "uploads"
    uploads.mkdir(parents=True)
    shutil.copy(sample_png, uploads / "page1.png")
    run_pipeline(store, job.id)

    assert store.get_job(job.id).state in (JobState.COMPLETED, JobState.NEEDS_REVIEW)
    assert vision.extract_calls == 1  # one call covers the whole page
    assert ocr.calls == 0  # adequate fields -> no per-question retry
    (q,) = store.load_document(doc.id).questions
    assert q.body[0].text == "다음 중 $x^2=4$의 해는?"
    assert [c.label for c in q.choices] == ["①", "②"]
