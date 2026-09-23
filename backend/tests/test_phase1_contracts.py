"""Phase 1: typed stage contracts, capability preflight, source hashing,
fail-closed transitions, and context-group isolation."""
from __future__ import annotations

import json

import pytest

from core.examdna import executor
from core.examdna.context import PipelineContext, Providers
from core.examdna.context_groups import (
    build_context_groups,
    run_units,
)
from core.examdna.pipeline import STAGES
from core.examdna.preflight import run_preflight
from core.examdna.source_integrity import run as source_integrity
from core.examdna.stage_contract import (
    StageContract,
    StageRecord,
    StageStatus,
)
from document.models import Document, Page, PageImage, Question, TextSpan
from jobs.models import Job, JobState


# --- stage status / transitions ------------------------------------------


def test_illegal_transition_rejected():
    rec = StageRecord(name="x")
    with pytest.raises(RuntimeError):
        rec.transition(StageStatus.SUCCEEDED)  # PENDING -> SUCCEEDED illegal


def test_terminal_states_are_final():
    rec = StageRecord(name="x")
    rec.transition(StageStatus.RUNNING)
    rec.transition(StageStatus.SUCCEEDED)
    assert rec.duration_s is not None
    with pytest.raises(RuntimeError):
        rec.transition(StageStatus.FAILED)


def test_all_seven_statuses_reachable():
    assert {s.value for s in StageStatus} == {
        "PENDING", "RUNNING", "SUCCEEDED", "NEEDS_REVIEW",
        "BLOCKED", "FAILED", "CANCELLED",
    }


# --- executor: blocked / failed / cancelled -------------------------------


def _ctx(tmp_path, doc=None):
    doc = doc or Document()
    return PipelineContext(
        document=doc,
        job=Job(id="j1", document_id=doc.id),
        store=None,
        workdir=tmp_path,
        providers=Providers(),
        event_sink=lambda *a: None,
    )


class _Caps:
    def __init__(self, available: set[str]):
        self._available = available

    def has(self, key: str) -> bool:
        return key in self._available


def test_blocked_stage_skips_function(tmp_path, monkeypatch):
    ran = []
    contracts = [
        StageContract("needs_solver", JobState.SOLVING,
                      lambda c: ran.append("solver"), requires=("solver",)),
        StageContract("local_only", JobState.PREPROCESSING,
                      lambda c: ran.append("local")),
    ]
    monkeypatch.setattr(executor, "STAGES", contracts)
    ctx = _ctx(tmp_path)
    ctx.capabilities = _Caps(set())  # nothing available

    records = executor.run_stages(ctx)

    assert ran == ["local"]                      # blocked fn never ran
    assert records[0].status is StageStatus.BLOCKED
    assert records[0].evidence["missing_capabilities"] == ["solver"]
    assert records[1].status is StageStatus.SUCCEEDED
    assert ctx.stage_blocked is True

    lines = (tmp_path / "stage_records.jsonl").read_text().splitlines()
    assert [json.loads(l)["status"] for l in lines] == [
        "BLOCKED", "SUCCEEDED"
    ]


def test_failed_stage_stops_pipeline(tmp_path, monkeypatch):
    ran = []

    def _boom(ctx):
        raise ValueError("corrupt")

    contracts = [
        StageContract("a", JobState.PREPROCESSING, lambda c: ran.append("a")),
        StageContract("b", JobState.PREPROCESSING, _boom),
        StageContract("c", JobState.PREPROCESSING, lambda c: ran.append("c")),
    ]
    monkeypatch.setattr(executor, "STAGES", contracts)

    with pytest.raises(ValueError):
        executor.run_stages(_ctx(tmp_path))

    records = [
        json.loads(l)
        for l in (tmp_path / "stage_records.jsonl").read_text().splitlines()
    ]
    assert ran == ["a"]          # c never ran
    assert [r["status"] for r in records] == ["SUCCEEDED", "FAILED"]
    assert "corrupt" in records[1]["error"]


def test_cancelled_marks_all_remaining(tmp_path, monkeypatch):
    calls = {"n": 0}
    contracts = [
        StageContract(f"s{i}", JobState.PREPROCESSING, lambda c: None)
        for i in range(4)
    ]
    monkeypatch.setattr(executor, "STAGES", contracts)

    def _cancel():
        calls["n"] += 1
        return calls["n"] > 1   # cancel after the first stage

    records = executor.run_stages(_ctx(tmp_path), should_cancel=_cancel)
    assert [r.status for r in records] == [
        StageStatus.SUCCEEDED,
        StageStatus.CANCELLED,
        StageStatus.CANCELLED,
        StageStatus.CANCELLED,
    ]


# --- source integrity ------------------------------------------------------


def _page_doc(tmp_path, content: bytes = b"page-bytes"):
    img = tmp_path / "p0.png"
    img.write_bytes(content)
    doc = Document()
    doc.pages.append(Page(index=0, original=PageImage(uri=str(img))))
    return doc


def test_source_hash_mismatch_fails(tmp_path):
    doc = _page_doc(tmp_path)
    doc.pages[0].sha256 = "0" * 64  # wrong recorded hash
    with pytest.raises(RuntimeError, match="hash mismatch"):
        source_integrity(_ctx(tmp_path, doc))


def test_source_hash_binds_when_missing(tmp_path):
    import hashlib

    doc = _page_doc(tmp_path)
    source_integrity(_ctx(tmp_path, doc))
    assert doc.pages[0].sha256 == hashlib.sha256(b"page-bytes").hexdigest()


def test_empty_document_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="no pages"):
        source_integrity(_ctx(tmp_path, Document()))


# --- context groups / unit isolation --------------------------------------


def _q(number: int, label: str | None = None, parent_id=None) -> Question:
    q = Question(number=number, label=label or str(number),
                 body=[TextSpan(text="t")])
    q.parent_id = parent_id
    return q


def test_shared_stem_is_one_group():
    doc = Document()
    parent = _q(1, "논술형 1")
    a, b = _q(2, "1-1", parent.id), _q(3, "1-2", parent.id)
    solo = _q(4)
    doc.questions = [parent, a, b, solo]

    groups = build_context_groups(doc)
    shared = [g for g in groups if g.reason.startswith("shared_stem")]
    singles = [g for g in groups if g.reason == "singleton"]
    assert len(shared) == 1
    assert set(shared[0].question_ids) == {a.id, b.id}
    assert {g.question_ids[0] for g in singles} == {solo.id}


def test_run_units_isolates_failure():
    doc = Document()
    doc.questions = [_q(i) for i in range(1, 4)]
    groups = build_context_groups(doc)

    def _fn(g):
        if g.question_ids[0] == doc.questions[1].id:
            raise TimeoutError("model hung")
        return {"ok": True}

    results = run_units(groups, _fn)
    assert [r.status for r in results] == [
        "SUCCEEDED", "FAILED", "SUCCEEDED"
    ]
    assert "TimeoutError" in results[1].error


# --- preflight --------------------------------------------------------------


def test_preflight_empty_providers(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    report = run_preflight(Providers())
    assert report.has("solver") is False
    assert report.has("ocr_audit") is False


def test_preflight_external_solver_counts_as_configured():
    class FakeExternal:
        name = "openai"
        model = "gpt-x"
        # no _client.base_url -> treated as configured, never probed

    report = run_preflight(Providers(solver=[FakeExternal()]))
    assert report.has("solver") is True
    slot = report.capabilities["solver"]["slots"][0]
    assert slot["endpoint"]["available"] is None  # not probed


def test_pipeline_has_preflight_and_integrity_stages():
    names = [c.name for c in STAGES]
    assert names[0] == "capability_preflight"
    # integrity check runs before any consumer stage, right after pages exist
    assert names.index("source_integrity") == names.index("preprocessing") + 1
    assert names.index("source_integrity") < names.index("segmentation")
    contract = {c.name: c for c in STAGES}
    assert "solver" in contract["solving"].requires
    assert "ocr_audit" in contract["source_verification"].requires


# --- solving runs per context group ---------------------------------------


def test_solving_isolates_per_group(store, tmp_path):
    """A group that crashes the solver is recorded; sibling groups still
    get solved — the whole stage does not die."""
    from core.examdna.verification import solving
    from document.models import Candidate, Choice

    class GroupSolver:
        name = "group-solver"

        def solve_batch(self, problems, run=0):
            if problems[0]["number"] == "2":
                raise TimeoutError("group hung")
            return [
                Candidate(
                    provider=self.name,
                    value=[
                        {
                            "number": p["number"],
                            "solved": True,
                            "answer": "①",
                            "steps": ["s"],
                        }
                        for p in problems
                    ],
                )
            ]

    qs = []
    for n in (1, 2, 3):
        q = _q(n)
        q.choices = [Choice(label="①", body=[TextSpan(text="x")])]
        qs.append(q)
    doc = Document()
    doc.questions = qs
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))
    ctx = PipelineContext(
        document=doc, job=job, store=store, workdir=tmp_path,
        providers=Providers(solver=[GroupSolver()]),
        event_sink=lambda *a: None,
    )
    solving.run(ctx)

    assert qs[0].answer and qs[0].answer.value == "①"
    assert qs[2].answer and qs[2].answer.value == "①"
    assert not qs[1].answer
    assert qs[1].verification.logic_flags[0].kind == "unsolvable_question"
    assert ctx.stage_metrics["solving"]["unit_failures"] == 2  # both runs
