"""WP04 contract tests: OpenAI adapter (fake client, no network), telemetry/
budget enforcement, and solver-backed canonical checks.

Independence contract (02/A34): the two solver passes use different prompts
(run=0 vs run=1), so a cache hit can never masquerade as a second opinion.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canonical.models import CheckState, IssueState
from canonical.service import MutationService
from canonical.store import CanonicalStore
from document.models import Answer, ATU, ATUKind, Candidate, Document, Question
from providers.telemetry import BudgetExceeded, Telemetry
from tenancy.db import TenancyDB


# --- fixtures ----------------------------------------------------------------------


@pytest.fixture()
def cstore(tmp_path):
    s = CanonicalStore(tmp_path / "canonical.db")
    yield s
    s.close()


@pytest.fixture()
def tenancy(tmp_path):
    t = TenancyDB(tmp_path / "tenancy.db")
    yield t
    t.close()


@pytest.fixture()
def service(cstore, tenancy):
    return MutationService(cstore, tenancy)


def _q(number: int, answer: str = "1") -> Question:
    return Question(
        number=number,
        label=str(number),
        answer=Answer(value=answer),
        atus=[ATU(kind=ATUKind.QUESTION_NUMBER, value=str(number))],
    )


def _doc(numbers=(1, 2, 3), answers=None, tenant="tn_1") -> Document:
    d = Document(tenant_id=tenant)
    answers = answers or {}
    for n in numbers:
        d.questions.append(_q(n, answers.get(n, "1")))
    return d


def _rev(service, doc):
    return service.create_revision(doc, doc.tenant_id, "alice")


class RecordingSolver:
    """Stub solver: returns configured answers per independent run."""

    name = "stub-solver"

    def __init__(self, answers_by_run):
        self.answers_by_run = answers_by_run  # {run: {num_str: answer}}
        self.runs: list[int] = []

    def solve_batch(self, problems, run: int = 0):
        self.runs.append(run)
        ans = self.answers_by_run.get(run)
        results = [
            {
                "number": p["number"],
                "solved": ans is not None and p["number"] in ans,
                "answer": (ans or {}).get(p["number"]),
                "steps": ["stub step"],
                "reason": "stub",
            }
            for p in problems
        ]
        return [Candidate(provider=self.name, value=results, confidence=0.9)]


def _providers(solver):
    return SimpleNamespace(solver=[solver])


def _checks_by_kind(checks):
    return {c.check_kind: c for c in checks}


# --- solver-backed checks ------------------------------------------------------------


def test_two_independent_runs_agree(service):
    doc = _doc()
    rev = _rev(service, doc)
    solver = RecordingSolver({0: {"1": "1", "2": "1", "3": "1"},
                              1: {"1": "1", "2": "1", "3": "1"}})
    checks = service.run_checks(rev.id, providers=_providers(solver))
    # two genuinely independent passes were issued
    assert solver.runs == [0, 1]
    by = _checks_by_kind(checks)
    assert by["SOLVE_TWO_INDEPENDENT_AGREEMENT"].state == CheckState.PASSED
    assert by["ANSWER_SOLUTION_LOGIC"].state == CheckState.PASSED


def test_independent_disagreement_fails_and_blocks(service, cstore):
    doc = _doc()
    rev = _rev(service, doc)
    solver = RecordingSolver({0: {"1": "1", "2": "1", "3": "1"},
                              1: {"1": "1", "2": "4", "3": "1"}})
    checks = service.run_checks(rev.id, providers=_providers(solver))
    by = _checks_by_kind(checks)
    assert by["SOLVE_TWO_INDEPENDENT_AGREEMENT"].state == CheckState.FAILED
    assert "2" in by["SOLVE_TWO_INDEPENDENT_AGREEMENT"].result_summary
    blocking = cstore.list_issues(rev.id, blocking_only=True)
    assert any(i.kind == "SOLVE_TWO_INDEPENDENT_AGREEMENT" for i in blocking)


def test_missing_second_run_fails(service):
    doc = _doc()
    rev = _rev(service, doc)
    # run=1 produces nothing (e.g. a budget/timeout cut the second pass)
    solver = RecordingSolver({0: {"1": "1", "2": "1", "3": "1"}})
    checks = service.run_checks(rev.id, providers=_providers(solver))
    by = _checks_by_kind(checks)
    assert by["SOLVE_TWO_INDEPENDENT_AGREEMENT"].state == CheckState.FAILED
    assert "independent" in by["SOLVE_TWO_INDEPENDENT_AGREEMENT"].result_summary


def test_solver_checks_not_run_without_provider(service):
    """Fail-closed: no solver provider -> checks stay NOT_RUN, never PASSED."""
    doc = _doc()
    rev = _rev(service, doc)
    checks = service.run_checks(rev.id)
    by = _checks_by_kind(checks)
    assert by["SOLVE_TWO_INDEPENDENT_AGREEMENT"].state == CheckState.NOT_RUN
    assert by["ANSWER_SOLUTION_LOGIC"].state == CheckState.NOT_RUN


def test_answer_solution_mismatch_detected(service, cstore):
    doc = _doc(answers={2: "4"})  # recorded answer for q2 is wrong
    rev = _rev(service, doc)
    solver = RecordingSolver({0: {"1": "1", "2": "2", "3": "1"}})
    checks = service.run_checks(rev.id, providers=_providers(solver))
    by = _checks_by_kind(checks)
    assert by["ANSWER_SOLUTION_LOGIC"].state == CheckState.FAILED
    assert "'2'" in by["ANSWER_SOLUTION_LOGIC"].result_summary
    blocking = cstore.list_issues(rev.id, blocking_only=True)
    assert any(i.kind == "ANSWER_SOLUTION_LOGIC" for i in blocking)


def test_seeded_baseline_seven_wrong_detected(service):
    """The seeded golden baseline had 7 wrong recorded answers; a correct
    independent solver must flag every one."""
    wrong = {n: str((n % 5) + 1) for n in range(1, 8)}  # recorded (wrong) key
    correct = {str(n): str(((n + 1) % 5) + 1) for n in range(1, 9)}
    doc = _doc(numbers=range(1, 9), answers={n: wrong.get(n, "3") for n in range(1, 9)})
    # make exactly 7 wrong: q8 recorded matches solver
    doc.questions[7].answer.value = correct["8"]
    rev = _rev(service, doc)
    solver = RecordingSolver({0: correct})
    checks = service.run_checks(rev.id, providers=_providers(solver))
    chk = _checks_by_kind(checks)["ANSWER_SOLUTION_LOGIC"]
    assert chk.state == CheckState.FAILED
    mismatched = [n for n in map(str, range(1, 9)) if n in chk.result_summary]
    assert len(mismatched) == 7


def test_circled_digit_normalization(service):
    """Solver returning ③ matches a recorded '3'."""
    doc = _doc(numbers=(1,), answers={1: "3"})
    rev = _rev(service, doc)
    solver = RecordingSolver({0: {"1": "③"}, 1: {"1": "③"}})
    checks = service.run_checks(rev.id, providers=_providers(solver))
    by = _checks_by_kind(checks)
    assert by["ANSWER_SOLUTION_LOGIC"].state == CheckState.PASSED
    assert by["SOLVE_TWO_INDEPENDENT_AGREEMENT"].state == CheckState.PASSED


# --- OpenAI adapter (fake client, no network) -----------------------------------------


class _FakeAPIError(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"api error {status_code}")
        self.status_code = status_code


class _FakeResp:
    def __init__(self, payload, in_tok=11, out_tok=7):
        self.output_text = payload if isinstance(payload, str) else json.dumps(payload)
        self.usage = SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok)


class _FakeResponses:
    """Scripted responses.create — pops outcomes, records kwargs."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


class _FakeClient:
    def __init__(self, outcomes):
        self.responses = _FakeResponses(outcomes)


def _solve_payload(number="1", answer="2"):
    return {"results": [{"number": number, "solved": True,
                         "answer": answer, "steps": ["s"], "reason": "r"}]}


def _openai(outcomes, telemetry=None):
    from providers.openai.provider import OpenAIProvider

    client = _FakeClient(outcomes)
    prov = OpenAIProvider(model="test-model", client=client, telemetry=telemetry)
    return prov, client


def test_openai_strict_schema_and_solve_batch():
    prov, client = _openai([_FakeResp(_solve_payload())])
    out = prov.solve_batch([{"number": "1", "body": "x"}])
    kwargs = client.responses.calls[0]
    fmt = kwargs["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert kwargs["model"] == "test-model"
    assert out[0].value[0]["answer"] == "2"


def test_openai_run_prompts_differ_independence():
    """run=0 and run=1 must produce different prompts — a second pass is a
    real inference, never the same cache key."""
    prov, client = _openai([_FakeResp(_solve_payload()), _FakeResp(_solve_payload())])
    problems = [{"number": "1", "body": "x"}]
    prov.solve_batch(problems, run=0)
    prov.solve_batch(problems, run=1)
    c0 = client.responses.calls[0]["input"][0]["content"]
    c1 = client.responses.calls[1]["input"][0]["content"]
    assert c0 != c1


def test_openai_retries_429_then_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr("providers.openai.provider.time.sleep", lambda *a: None)
    tel = Telemetry()
    prov, client = _openai(
        [_FakeAPIError(429), _FakeAPIError(503), _FakeResp(_solve_payload())],
        telemetry=tel,
    )
    out = prov.solve_batch([{"number": "1"}])
    assert out[0].value[0]["solved"] is True
    assert len(client.responses.calls) == 3
    rec = tel.records[-1]
    assert rec.outcome == "retry" and rec.attempts == 3
    assert rec.input_tokens == 11 and rec.output_tokens == 7


def test_openai_non_retryable_error_recorded():
    tel = Telemetry()
    prov, _ = _openai([_FakeAPIError(400)], telemetry=tel)
    out = prov.solve_batch([{"number": "1"}])
    assert out[0].value == []  # contained — unsolved candidate
    assert tel.records[-1].outcome == "error"
    assert tel.records[-1].error_class == "_FakeAPIError"


def test_openai_json_error_contained():
    tel = Telemetry()
    prov, _ = _openai([_FakeResp("this is not json")], telemetry=tel)
    out = prov.solve_batch([{"number": "1"}])
    assert out[0].value == []


def test_openai_budget_enforced():
    tel = Telemetry(max_calls=1)
    prov, _ = _openai([_FakeResp(_solve_payload()), _FakeResp(_solve_payload())],
                    telemetry=tel)
    first = prov.solve_batch([{"number": "1"}])
    assert first[0].value[0]["solved"] is True
    second = prov.solve_batch([{"number": "1"}])
    assert second[0].value == []  # budget exceeded -> unsolved, not a pass
    assert any(r.outcome == "budget_exceeded" for r in tel.records)


def test_openai_telemetry_records_call_metadata():
    tel = Telemetry()
    prov, _ = _openai([_FakeResp(_solve_payload())], telemetry=tel)
    prov.solve_batch([{"number": "1"}])
    rec = tel.records[-1]
    assert rec.provider == "openai" and rec.model == "test-model"
    assert rec.method == "solve_batch"
    assert len(rec.prompt_sha256) == 64 and len(rec.input_sha256) == 64
    assert rec.outcome == "ok" and rec.attempts == 1


# --- same-field candidate merge (WP04) -----------------------------------------------


def test_same_field_candidates_merge_and_conflict():
    """Two providers' values for one field become candidates on a single
    ATU — disagreement flags CONFLICT, agreement does not."""
    from core.examdna.recognition.runner import _ingest_fields
    from document.models import VerificationStatus

    q = Question(number=1, label="1")
    _ingest_fields(q, "p1", {"label": "1", "body": "가", "choices": {"1": "a"}})
    _ingest_fields(q, "p2", {"label": "1", "body": "나", "choices": {"1": "a"}})
    body = next(a for a in q.atus if a.field == "body")
    assert len(body.candidates) == 2  # merged into one ATU
    assert body.status == VerificationStatus.CONFLICT
    choice = next(a for a in q.atus if a.field == "choice:1")
    assert len(choice.candidates) == 2
    assert choice.status != VerificationStatus.CONFLICT


# --- cache replay vs fresh inference separation ----------------------------------------


def test_cache_replay_is_not_an_independent_run():
    """A Gemini-style cache hit is logged outcome='cache'; solver agreement
    requires two distinct run prompts, which cache replay cannot produce."""
    tel = Telemetry()
    from providers.telemetry import CallRecord

    tel.record(CallRecord(
        ts=0, provider="gemini", model="m", method="solve",
        prompt_sha256="x", input_sha256="y", outcome="cache",
    ))
    assert tel.records[0].outcome == "cache"
    # cache outcomes do not consume the call budget
    assert tel._calls_made == 0
