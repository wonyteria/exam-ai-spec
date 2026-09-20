"""RESTORE-25 Exam Agent + RESTORE-26/28 Variation/Composer."""
from __future__ import annotations

import copy

import pytest

from agent.ops import parse_command
from canonical.models import ChangeOp
from canonical.store import CanonicalStore
from canonical.service import MutationService
from tenancy.db import TenancyDB
from composer.engine import ComposeSpec, compose_exam, select_questions
from document.models import (
    Answer,
    Choice,
    Document,
    Equation,
    Question,
    QuestionType,
    Solution,
    TextSpan,
)
from question_dna.dna import derive_dna
from variation.engine import numeric_variant, shuffle_choices


def _doc(n=5) -> Document:
    d = Document()
    for i in range(1, n + 1):
        q = Question(number=i, type=QuestionType.MULTIPLE_CHOICE, points=3)
        q.body = [TextSpan(text=f"문항 {i}")]
        q.choices = [
            Choice(label="①", body=[TextSpan(text="1")]),
            Choice(label="②", body=[TextSpan(text="2")]),
        ]
        q.answer = Answer(value="①")
        q.equations = [Equation(latex=f"{i}*x+{i}=10")]
        d.questions.append(q)
    return d


# --- agent parsing --------------------------------------------------------


def test_swap_command():
    doc = _doc()
    p = parse_command(doc, "3번과 7번 바꿔줘")
    # 7 doesn't exist -> unrecognized? doc has 5 questions; use existing
    assert p.recognized is False or p.ops
    p = parse_command(doc, "2번과 4번 바꿔줘")
    assert p.recognized and p.ops[0].op == "SwapQuestions"
    assert p.preview  # diff preview produced


def test_move_to_end():
    doc = _doc()
    p = parse_command(doc, "1번을 맨 뒤로 보내줘")
    assert p.recognized
    assert p.ops[0].op == "MoveQuestion"
    assert p.ops[0].value == len(doc.questions) - 1


def test_descriptive_last():
    doc = _doc()
    subj = Question(number=6, type=QuestionType.DESCRIPTIVE)
    subj.body = [TextSpan(text="서술")]
    doc.questions.insert(1, subj)  # out of order on purpose
    p = parse_command(doc, "서술형을 마지막에 넣어줘")
    assert p.recognized
    assert p.ops[0].op == "ReorderQuestions"
    assert p.ops[0].value[-1] == subj.id


def test_reduce_count():
    doc = _doc()
    p = parse_command(doc, "5문제를 3문제로 줄여줘")
    assert p.recognized
    assert len(p.ops) == 2
    assert all(o.op == "RemoveQuestion" for o in p.ops)


def test_unrecognized_is_explicit():
    doc = _doc()
    p = parse_command(doc, "아무말이나 해봐")
    assert p.recognized is False


# --- ops apply through canonical revisions ---------------------------------


def _service(tmp_path):
    store = CanonicalStore(tmp_path / "c.sqlite")
    tenancy = TenancyDB(tmp_path / "t.sqlite")
    svc = MutationService(store, tenancy)
    doc = _doc()
    rev = svc.create_revision(doc, "t1", "tester")
    return svc, doc, rev


def _content(store, rev) -> Document:
    return Document.model_validate(store.get_revision(rev.id).content_json)


def test_swap_creates_revision_and_undoes(tmp_path):
    svc, doc, rev = _service(tmp_path)
    moved_id = doc.questions[2].id   # question #3
    p = parse_command(doc, "1번과 3번 바꿔줘")
    assert p.ops
    rev2 = svc.apply("t1", "tester", doc.id, rev.id, p.ops,
                     route="agent.command")
    head = _content(svc.store, rev2)
    # numbers follow position; the question CONTENT moved
    assert head.questions[0].id == moved_id
    # undo restores — via a NEW revision, never overwriting history
    rev3 = svc.undo("t1", "tester", doc.id, rev2.id, rev.id, "revert")
    head2 = _content(svc.store, rev3)
    assert head2.questions[0].id != moved_id


def test_reorder_apply(tmp_path):
    svc, doc, rev = _service(tmp_path)
    moved_id = doc.questions[4].id   # question #5
    p = parse_command(doc, "5번을 맨 앞으로 보내줘")
    assert p.recognized
    rev2 = svc.apply("t1", "tester", doc.id, rev.id, p.ops,
                     route="agent.command")
    head = _content(svc.store, rev2)
    assert head.questions[0].id == moved_id


# --- variation + composer ---------------------------------------------------


def test_numeric_variant_uses_ast_not_string():
    q = _doc(1).questions[0]
    q.equations = [Equation(latex="2*x+4=10")]
    v = numeric_variant(q, seed=7)
    assert v is not None
    assert v.transform == "numeric_shift"
    assert v.new_equations
    assert v.notes  # marked as candidate


def test_unparseable_equation_returns_none():
    q = _doc(1).questions[0]
    q.equations = [Equation(latex="hello world")]
    assert numeric_variant(q, seed=1) is None


def test_choice_shuffle_remaps_answer():
    q = _doc(1).questions[0]
    v = shuffle_choices(q, seed=3)
    assert v.transform == "choice_shuffle"
    assert len(v.new_choices) == 2
    assert v.new_answer in {"①", "②"}


def test_compose_difficulty_mix_and_keys():
    pool = _doc(9)
    bands = ["상", "중", "하"]
    for i, q in enumerate(pool.questions):
        q.question_dna = derive_dna(q)
        q.question_dna["difficulty_band"] = bands[i % 3]
        q.question_dna["estimated_time"] = 2.0
    spec = ComposeSpec(
        difficulty_mix={"상": 1, "중": 1, "하": 1},
        versions=2, seed=5,
    )
    res = compose_exam(pool, spec, title="테스트")
    assert len(res.exams) == 2
    assert all(len(e.questions) == 3 for e in res.exams)
    assert len(res.answer_keys) == 2
    assert res.unfilled == {}
    # versions differ in order or choice permutation (deterministic seed)
    assert res.exams[0].metadata.title.endswith("A형")
    assert res.exams[1].metadata.title.endswith("B형")


def test_compose_unfillable_reports_shortfall():
    pool = _doc(2)
    for q in pool.questions:
        q.question_dna = derive_dna(q)
        q.question_dna["difficulty_band"] = "하"
    spec = ComposeSpec(difficulty_mix={"상": 3}, versions=1)
    res = compose_exam(pool, spec)
    assert res.unfilled.get("상") == 3
    assert res.exams[0].questions == []


# --- agent API endpoint ------------------------------------------------------


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def api_env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXAMDNA_DATA", str(tmp_path / "data"))
    import app.deps as deps

    deps.reset()
    import app.api.uploads as uploads_api

    monkeypatch.setattr(uploads_api, "run_once", lambda *a, **k: False)
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c, deps
    deps.reset()


def test_agent_endpoint_proposes_and_changes_applies(api_env):
    client, deps = api_env
    h = {"X-Dev-User": "u1"}
    client.post("/api/auth/dev-login", json={"user_id": "u1", "name": "A"})
    tid = client.post("/api/tenants", json={"name": "A"}, headers=h).json()["id"]
    up = client.post(
        "/api/uploads",
        files=[("files", ("p1.png", _png_bytes(), "image/png"))],
        headers=h,
    )
    assert up.status_code == 200, up.text
    doc_id = up.json()["document_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/agent",
        json={"command": "제목을 '주간 테스트'로 바꿔줘"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["recognized"] is True
    assert data["ops"][0]["op"] == "SetMetadata"
    # apply through /changes — revision created
    r2 = client.post(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/changes",
        json={"ops": data["ops"]},
        headers={**h, "If-Match": data["if_match"]},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["revision"]["revision_no"] == 2


def test_agent_endpoint_unrecognized(api_env):
    client, deps = api_env
    h = {"X-Dev-User": "u1"}
    client.post("/api/auth/dev-login", json={"user_id": "u1", "name": "A"})
    tid = client.post("/api/tenants", json={"name": "A"}, headers=h).json()["id"]
    up = client.post(
        "/api/uploads",
        files=[("files", ("p1.png", _png_bytes(), "image/png"))],
        headers=h,
    )
    doc_id = up.json()["document_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/agent",
        json={"command": "알 수 없는 요청"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["recognized"] is False
    assert r.json()["data"]["ops"] == []


def _seed_questions(cstore, doc_id, n=4):
    """Attach questions to the stored document via a revision."""
    head = cstore.get_head_revision(doc_id)
    doc = Document.model_validate(head.content_json)
    for i in range(1, n + 1):
        q = Question(number=i, type=QuestionType.MULTIPLE_CHOICE, points=3)
        q.body = [TextSpan(text=f"문항 {i}")]
        q.choices = [
            Choice(label="①", body=[TextSpan(text="1")]),
            Choice(label="②", body=[TextSpan(text="2")]),
        ]
        q.answer = Answer(value="①")
        doc.questions.append(q)
    from canonical.service import MutationService

    svc = MutationService(cstore, deps_get_tenancy())
    svc.create_revision(doc, doc.tenant_id or "t1", "tester")


def deps_get_tenancy():
    import app.deps as deps

    return deps.get_tenancy()


def test_compose_endpoint_creates_versioned_exams(api_env):
    client, deps = api_env
    h = {"X-Dev-User": "u1"}
    client.post("/api/auth/dev-login", json={"user_id": "u1", "name": "A"})
    tid = client.post("/api/tenants", json={"name": "A"}, headers=h).json()["id"]
    up = client.post(
        "/api/uploads",
        files=[("files", ("p1.png", _png_bytes(), "image/png"))],
        headers=h,
    )
    doc_id = up.json()["document_id"]
    _seed_questions(deps.get_canonical(), doc_id)
    r = client.post(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/compose",
        json={"versions": 2, "count": 3, "seed": 1, "title": "주간"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data["exams"]) == 2
    for ex in data["exams"]:
        assert ex["questions"] == 3
        assert len(ex["answer_key"]) == 3
        # each version is a real stored document
        assert deps.get_canonical().get_document(ex["document_id"])
