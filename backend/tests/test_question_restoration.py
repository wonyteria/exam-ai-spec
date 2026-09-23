"""Question-centric restoration: status model, constraint corrections,
question-scoped NL edits, best-effort export — plus the regression cases
from the restoration directive (choice-label dup, missing minus handling,
symbol loss, sub-number dup, handwriting overlap, print preservation,
cross-question edit isolation)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from document.models import (
    ATU,
    ATUKind,
    Candidate,
    Choice,
    Document,
    FieldIssue,
    LogicFlag,
    Question,
    QuestionStatus,
    TextSpan,
    VerificationStatus,
)
from document.restoration import (
    refresh_document_status,
    refresh_question_status,
    status_counts,
)
from core.examdna.correction import (
    handwriting_overlap_issue,
    renumber_duplicate_subnumbers,
    run_corrections,
)
from agent.question_ops import parse_question_edit


def _q(**kw) -> Question:
    return Question(**kw)


def _atu(kind, field, value, status=VerificationStatus.AUTO_VERIFIED,
         providers=("a", "b")) -> ATU:
    atu = ATU(kind=kind, field=field, status=status)
    for p in providers:
        atu.candidates.append(
            Candidate(provider=p, value=value, confidence=0.9, meta={}))
    atu.value = value
    return atu


def _choice_atu(label, value, status=VerificationStatus.AUTO_VERIFIED,
                providers=("a", "b")) -> ATU:
    return _atu(ATUKind.CHOICE, f"choice:{label}", value, status, providers)


def _mc_question(labels=("①", "②", "③"), texts=("1", "2", "3")) -> Question:
    q = _q(number=1, label="1")
    for label, text in zip(labels, texts):
        q.choices.append(Choice(label=label, body=[TextSpan(text=text)]))
        q.atus.append(_choice_atu(label, text))
    q.atus.append(_atu(ATUKind.TEXT_TOKEN, "body", "본문"))
    q.body = [TextSpan(text="본문")]
    refresh_question_status(q)
    return q


# --- constraint corrections --------------------------------------------------


def test_duplicate_choice_labels_are_renumbered():
    q = _mc_question(labels=("①", "①", "③"))
    q.restoration.status = QuestionStatus.NEEDS_USER_REVIEW  # reset
    run_corrections(q)
    assert [c.label for c in q.choices] == ["①", "②", "③"]
    assert any(c.rule == "choice_label_dedup"
               for c in q.restoration.corrections)


def test_bogee_consonant_syllable_misread_fixed():
    """ㄱ/ㄴ/ㄷ 보기 항목이 가/나/다로 읽힌 경우 — 심원중 gold 비교 발견."""
    q = _q(number=4, label="4")
    q.body = [TextSpan(
        text="옳은 것만을 <보기>에서 고른 것은? <보기> "
             "가. 첫째 나. 둘째 다. 셋째")]
    for label, text in zip("①②③④⑤",
                           ("가", "나", "다", "가, 다", "가, 나, 다")):
        q.choices.append(Choice(label=label, body=[TextSpan(text=text)]))
    run_corrections(q)
    texts = [c.body[0].text for c in q.choices]
    assert texts == ["ㄱ", "ㄴ", "ㄷ", "ㄱ, ㄷ", "ㄱ, ㄴ, ㄷ"]
    assert "ㄱ. 첫째" in q.body[0].text
    assert any(c.rule == "bogee_consonant"
               for c in q.restoration.corrections)


def test_bogee_consonant_needs_evidence():
    """<보기>/자음 마커 증거가 없으면 '가'를 자음으로 바꾸지 않는다."""
    q = _q(number=1, label="1")
    q.body = [TextSpan(text="다음 중 가장 큰 것은?")]
    q.choices.append(Choice(label="①", body=[TextSpan(text="가")]))
    run_corrections(q)
    assert q.choices[0].body[0].text == "가"
    assert not any(c.rule == "bogee_consonant"
                   for c in q.restoration.corrections)


def test_bogee_consonant_never_touches_sentence_endings():
    """'이다.' 같은 어미는 보기 헤더 뒤에서도 변환하지 않는다."""
    q = _q(number=4, label="4")
    q.body = [TextSpan(
        text="<보기> 가. 두 삼각형은 서로 합동이다. 나. 둘째")]
    run_corrections(q)
    assert "합동이다." in q.body[0].text
    assert "ㄱ. 두 삼각형" in q.body[0].text
    assert "ㄴ. 둘째" in q.body[0].text


def test_out_of_order_choice_labels_fixed():
    q = _mc_question(labels=("②", "①", "③"))
    run_corrections(q)
    assert [c.label for c in q.choices] == ["①", "②", "③"]
    assert any(c.rule == "choice_order" for c in q.restoration.corrections)


def test_digit_labels_normalized_to_circled():
    q = _mc_question(labels=("1.", "2.", "3."))
    run_corrections(q)
    assert [c.label for c in q.choices] == ["①", "②", "③"]


def test_line_join_merges_wrapped_sentence():
    q = _q(number=1, label="1")
    q.body = [
        TextSpan(text="다음 함수 f(x)="),
        TextSpan(text="x^2+1 일 때 극값을 구하시오"),
    ]
    run_corrections(q)
    assert len(q.body) == 1
    assert "x^2+1" in q.body[0].text
    assert any(c.rule == "line_join" for c in q.restoration.corrections)


def test_ocr_typo_numeric_context_fixed():
    q = _q(number=1, label="1")
    q.body = [TextSpan(text="2O3개의 물체가 있다")]
    run_corrections(q)
    assert q.body[0].text == "203개의 물체가 있다"


def test_ocr_typo_does_not_touch_plain_korean():
    """Regression: '인쇄 내용 삭제/훼손' — corrections must not rewrite
    ordinary prose."""
    q = _q(number=1, label="1")
    q.body = [TextSpan(text="오른쪽 그림과 같은 직각삼각형에서")]
    run_corrections(q)
    assert q.body[0].text == "오른쪽 그림과 같은 직각삼각형에서"
    assert not q.restoration.corrections


def test_unit_symbol_normalization():
    q = _q(number=1, label="1")
    q.body = [TextSpan(text="⊿ABC에서 <ABC의 크기는 85˚이고 10㎝이다")]
    run_corrections(q)
    assert q.body[0].text == "△ABC에서 ∠ABC의 크기는 85°이고 10cm이다"


def test_unicode_minus_normalized():
    q = _q(number=1, label="1")
    q.choices = [Choice(label="①", body=[TextSpan(text="−35")])]
    run_corrections(q)
    assert q.choices[0].body[0].text == "-35"


def test_sign_disagreement_is_review_not_autofix():
    """Missing-minus candidates that disagree on sign are a meaning
    change — flagged, never picked."""
    q = _mc_question()
    atu = _choice_atu("②", "35", status=VerificationStatus.CONFLICT)
    atu.candidates = [
        Candidate(provider="a", value="35", confidence=0.9, meta={}),
        Candidate(provider="b", value="-35", confidence=0.9, meta={}),
    ]
    q.atus[1] = atu
    run_corrections(q)
    refresh_question_status(q)
    reasons = {i.reason for i in q.restoration.issues}
    assert "sign_ambiguity" in reasons or "conflict" in reasons
    assert q.restoration.status == QuestionStatus.NEEDS_USER_REVIEW


def test_subnumber_duplicates_renumbered():
    doc = Document()
    a = _q(number=3, label="2-1")
    b = _q(number=4, label="2-1")
    doc.questions.extend([a, b])
    applied = renumber_duplicate_subnumbers(doc)
    assert [q.label for q in doc.questions] == ["2-1", "2-2"]
    assert applied and b.restoration.corrections


def test_handwriting_overlap_is_flagged_not_deleted():
    from document.models import BBox, SourceRef

    from document.models import Page, PageImage

    doc = Document()
    doc.pages.append(
        Page(
            index=0,
            width=1000,
            height=1400,
            original=PageImage(uri="p.png", sha256="x"),
            uncertain_regions=[
                {"bbox_px": {"x": 10, "y": 10, "w": 200, "h": 100}}
            ],
        )
    )
    q = _q(number=1, label="1")
    q.source = SourceRef(page=0, bbox=BBox(x=0, y=0, w=300, h=300))
    issue = handwriting_overlap_issue(doc, q)
    assert issue is not None
    assert issue.reason == "print_handwriting_overlap"


# --- status derivation --------------------------------------------------------


def test_clean_question_is_auto_restored():
    q = _mc_question()
    assert q.restoration.status == QuestionStatus.AUTO_RESTORED
    assert q.restoration.confidence == 1.0


def test_corrected_question_is_auto_corrected():
    q = _mc_question(labels=("①", "①", "③"))
    run_corrections(q)
    refresh_question_status(q)
    assert q.restoration.status == QuestionStatus.AUTO_CORRECTED


def test_unverified_atu_is_needs_review():
    q = _mc_question()
    q.atus[0].status = VerificationStatus.UNVERIFIED
    q.atus[0].candidates = q.atus[0].candidates[:1]
    refresh_question_status(q)
    assert q.restoration.status == QuestionStatus.NEEDS_USER_REVIEW
    assert any(i.reason == "unverified" for i in q.restoration.issues)


def test_empty_question_is_blocked():
    q = _q(number=7, label="7")
    assert refresh_question_status(q) == QuestionStatus.BLOCKED


def test_logic_flag_forces_review():
    q = _mc_question()
    q.verification.logic_flags.append(
        LogicFlag(kind="invalid_figure", detail="도형 숫자 불일치"))
    refresh_question_status(q)
    assert q.restoration.status == QuestionStatus.NEEDS_USER_REVIEW


def test_user_confirmed_is_sticky():
    q = _mc_question()
    q.restoration.status = QuestionStatus.USER_CONFIRMED
    assert refresh_question_status(q) == QuestionStatus.USER_CONFIRMED


def test_resolving_atu_clears_issue():
    q = _mc_question()
    q.atus[0].status = VerificationStatus.UNVERIFIED
    q.atus[0].candidates = q.atus[0].candidates[:1]
    refresh_question_status(q)
    assert q.restoration.status == QuestionStatus.NEEDS_USER_REVIEW
    # Human resolves the ATU -> issue list rebuild drops it.
    q.atus[0].status = VerificationStatus.HUMAN_VERIFIED
    q.restoration.status = QuestionStatus.USER_EDITED
    refresh_question_status(q)
    assert q.restoration.status == QuestionStatus.USER_EDITED
    assert not any(i.reason == "unverified" for i in q.restoration.issues)


def test_document_status_aggregation():
    doc = Document()
    doc.verification.status = "NEEDS_REVIEW"
    doc.questions = [_mc_question()]
    doc.questions[0].restoration.status = QuestionStatus.AUTO_RESTORED
    assert refresh_document_status(doc) == "READY_FOR_FINAL_EXPORT"
    doc.questions[0].restoration.status = QuestionStatus.NEEDS_USER_REVIEW
    assert refresh_document_status(doc) == "NEEDS_USER_REVIEW"
    doc.questions[0].restoration.status = QuestionStatus.BLOCKED
    assert refresh_document_status(doc) == "RESTORED_BEST_EFFORT"


def test_status_counts():
    doc = Document()
    doc.questions = [_mc_question(), _q(number=2, label="2")]
    doc.questions[0].restoration.status = QuestionStatus.AUTO_RESTORED
    doc.questions[1].restoration.status = QuestionStatus.BLOCKED
    counts = status_counts(doc)
    assert counts["AUTO_RESTORED"] == 1
    assert counts["BLOCKED"] == 1
    assert counts["total"] == 2


# --- question-scoped NL edit parsing --------------------------------------------


def test_parse_choice_edit():
    q = _mc_question()
    plan = parse_question_edit(q, "①번 보기를 -35로 수정해")
    assert plan.recognized and plan.ops
    op = plan.ops[0]
    assert op.op == "SetChoice" and op.field == "①" and op.value == "-35"
    assert op.target_id == q.id


def test_parse_multi_value_choice():
    q = _mc_question()
    plan = parse_question_edit(q, "⑤번을 9cm, 10cm, 15cm로 수정해")
    assert plan.recognized
    assert plan.ops[0].op == "SetChoice" and plan.ops[0].field == "⑤"
    assert plan.ops[0].value == "9cm, 10cm, 15cm"


def test_parse_figure_label_edit():
    q = _mc_question()
    plan = parse_question_edit(q, "이 도형의 오른쪽 길이를 10cm로 수정해")
    assert plan.recognized
    op = plan.ops[0]
    assert op.op == "SetField" and op.field == "figure_label"
    assert op.value == {"name": "오른쪽", "label": "10cm"}


def test_parse_rewrite_intent():
    q = _mc_question()
    plan = parse_question_edit(q, "문장만 자연스럽게 정리해")
    assert plan.recognized and plan.rewrite and not plan.ops


def test_parse_points_and_answer():
    q = _mc_question()
    assert parse_question_edit(q, "배점을 5점으로 수정해").ops[0].op == "SetPoints"
    plan = parse_question_edit(q, "정답을 3번으로 수정해")
    assert plan.ops[0].op == "SetAnswer"


def test_parse_confirm():
    q = _mc_question()
    plan = parse_question_edit(q, "이 문항 확인 완료")
    assert plan.ops[0].op == "SetQuestionStatus"
    assert plan.ops[0].value == "USER_CONFIRMED"


def test_wrong_question_number_is_clarification_not_edit():
    """'11번 …' 지시를 5번 문항에 적용 요청 → 수정하지 않고 확인 요청."""
    q = _mc_question()
    q.label = "5"
    plan = parse_question_edit(q, "11번 ①번 보기를 -35로 수정해")
    assert not plan.recognized
    assert plan.needs_clarification


def test_unrecognized_instruction_asks_clarification():
    q = _mc_question()
    plan = parse_question_edit(q, "알아서 잘 해줘")
    assert not plan.recognized and plan.needs_clarification


# --- canonical isolation --------------------------------------------------------


def test_edit_one_question_never_touches_another():
    """Regression: '한 문항 수정이 다른 문항에 영향' — SetChoice on q1
    must leave q2 byte-identical, and only q1 becomes USER_EDITED."""
    from canonical.models import ChangeOp
    from canonical.service import MutationService
    from canonical.store import CanonicalStore
    from tenancy.db import TenancyDB

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cstore = CanonicalStore(Path(td) / "c.db")
        service = MutationService(cstore, TenancyDB(Path(td) / "t.db"))
        doc = Document(tenant_id="tn")
        doc.questions = [_mc_question(), _mc_question()]
        doc.questions[0].id = "q1"
        doc.questions[1].id = "q2"
        doc.questions[1].number = 2
        doc.questions[1].label = "2"
        rev = service.create_revision(doc, "tn", "alice")

        service.apply("tn", "alice", doc.id, rev.id, [
            ChangeOp(op="SetChoice", target_id="q1", field="①",
                     value="-35"),
            ], route="test")
        head = cstore.get_head_revision(doc.id)
        after = Document.model_validate(head.content_json)
        q1 = next(q for q in after.questions if q.id == "q1")
        q2 = next(q for q in after.questions if q.id == "q2")
        assert q1.choices[0].body[0].text == "-35"
        assert q1.restoration.status == QuestionStatus.USER_EDITED
        # q2 untouched — same content, still AUTO_RESTORED
        assert q2.choices[0].body[0].text == "1"
        assert q2.restoration.status == QuestionStatus.AUTO_RESTORED
        cstore.close()


def test_set_question_status_op():
    from canonical.models import ChangeOp
    from canonical.service import MutationService
    from canonical.store import CanonicalStore, ValidationError
    from tenancy.db import TenancyDB

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cstore = CanonicalStore(Path(td) / "c.db")
        service = MutationService(cstore, TenancyDB(Path(td) / "t.db"))
        doc = Document(tenant_id="tn")
        doc.questions = [_mc_question()]
        rev = service.create_revision(doc, "tn", "alice")
        service.apply("tn", "alice", doc.id, rev.id, [
            ChangeOp(op="SetQuestionStatus",
                     target_id=doc.questions[0].id,
                     value="USER_CONFIRMED"),
            ], route="test")
        head = cstore.get_head_revision(doc.id)
        after = Document.model_validate(head.content_json)
        assert (after.questions[0].restoration.status
                == QuestionStatus.USER_CONFIRMED)
        rev2 = service.apply("tn", "alice", doc.id, head.id, [
            ChangeOp(op="SetQuestionStatus",
                     target_id=doc.questions[0].id,
                     value="USER_EDITED"),
            ], route="test")
        with pytest.raises(ValidationError):
            service.apply("tn", "alice", doc.id, rev2.id, [
                ChangeOp(op="SetQuestionStatus",
                         target_id=doc.questions[0].id,
                         value="AUTO_RESTORED"),
                ], route="test")
        cstore.close()


# --- local model routing --------------------------------------------------------


def test_router_prefers_long_for_descriptive():
    from providers.local.router import LocalLLMRouter

    class Fake:
        def __init__(self, model):
            self.model = model
            self.calls = []

        def solve(self, problem, run=0):
            self.calls.append(problem)
            return Candidate(provider=f"llm/{self.model}",
                             value={"solved": True}, confidence=0.8)

        def solve_batch(self, problems, run=0):
            self.calls.extend(problems)
            return [Candidate(provider=f"llm/{self.model}",
                              value=[{}] * len(problems), confidence=0.8)]

    large, long = Fake("local-large"), Fake("local-long")
    router = LocalLLMRouter(large, long)
    mc = {"number": "1", "type": "multiple_choice", "body": "짧은 문제"}
    desc = {"number": "2-1", "type": "descriptive", "body": "서술하시오"}
    assert router.solve(mc).meta["routed_model"] == "local-large"
    assert router.solve(desc).meta["routed_model"] == "local-long"
    assert large.calls == [mc] and long.calls == [desc]

    large.calls.clear(); long.calls.clear()
    cands = router.solve_batch([mc, desc])
    assert {c.provider for c in cands} == {"llm/local-large", "llm/local-long"}
    assert large.calls == [mc] and long.calls == [desc]


def test_router_without_long_uses_large():
    from providers.local.router import LocalLLMRouter

    class Fake:
        model = "local-large"

        def solve(self, problem, run=0):
            return Candidate(provider="llm", value={"solved": True},
                             confidence=0.8)

    router = LocalLLMRouter(Fake())
    cand = router.solve({"type": "descriptive", "body": "서술"})
    assert cand.provider == "llm"


def test_local_small_never_solver():
    """local-small is auxiliary only — routing only ever picks between
    the two configured solver models, never an auxiliary one."""
    from providers.local.router import LocalLLMRouter

    class Fake:
        def __init__(self, model):
            self.model = model

        def solve(self, problem, run=0):
            return Candidate(provider=f"llm/{self.model}",
                             value={"solved": True}, confidence=0.8)

    router = LocalLLMRouter(Fake("local-large"), Fake("local-long"))
    for problem in (
        {"type": "descriptive", "body": "서술" * 500},
        {"type": "multiple_choice", "body": "짧음"},
    ):
        cand = router.solve(problem)
        assert "small" not in cand.meta["routed_model"]
        assert cand.meta["routed_model"] in ("local-large", "local-long")


# --- API: question-centric endpoints -------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EXAMDNA_DATA", str(tmp_path / "data"))
    import app.deps as deps

    deps.reset()
    import app.api.uploads as uploads_api

    monkeypatch.setattr(uploads_api, "run_once", lambda *a, **k: False)
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
    deps.reset()


def _h(user: str, tenant: str | None = None) -> dict[str, str]:
    headers = {"x-dev-user": user}
    if tenant:
        headers["x-dev-tenant"] = tenant
    return headers


def _seed_doc(client, user="alice"):
    tenant = client.post(
        "/api/tenants", json={"name": "학원"}, headers=_h(user)
    ).json()["id"]
    from app.deps import get_store

    doc = Document(tenant_id=tenant)
    doc.verification.status = "NEEDS_REVIEW"
    good = _mc_question()
    good.id = "q_ok"
    bad = _mc_question()
    bad.id = "q_bad"
    bad.number, bad.label = 11, "11"
    bad.atus[1].status = VerificationStatus.UNVERIFIED
    bad.atus[1].candidates = bad.atus[1].candidates[:1]
    refresh_question_status(bad)
    doc.questions = [good, bad]
    refresh_document_status(doc)
    get_store().save_document(doc)
    return tenant, doc


def test_restoration_summary_lists_only_problem_questions(client):
    tenant, doc = _seed_doc(client)
    res = client.get(
        f"/api/documents/{doc.id}/restoration", headers=_h("alice", tenant))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["restoration_status"] == "NEEDS_USER_REVIEW"
    assert body["counts"]["NEEDS_USER_REVIEW"] == 1
    assert body["counts"]["AUTO_RESTORED"] == 1
    # Only the problem question is listed
    assert [q["id"] for q in body["review_questions"]] == ["q_bad"]
    assert body["review_questions"][0]["issues"]


def test_question_detail_has_fields_and_crop(client):
    tenant, doc = _seed_doc(client)
    res = client.get(
        f"/api/documents/{doc.id}/questions/q_bad",
        headers=_h("alice", tenant))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["label"] == "11"
    assert body["status"] == "NEEDS_USER_REVIEW"
    assert body["issues"][0]["field"] == "choice:②"
    assert body["choices"] and body["atus"]


def test_question_edit_preview_does_not_mutate(client):
    tenant, doc = _seed_doc(client)
    res = client.post(
        f"/api/documents/{doc.id}/questions/q_bad/edit",
        json={"instruction": "②번 보기를 -35로 수정해", "apply": False},
        headers=_h("alice", tenant))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] and not body["applied"]
    assert body["preview"]["after"]["choices"][1]["body"] == ["-35"]
    # Original untouched
    detail = client.get(
        f"/api/documents/{doc.id}/questions/q_bad",
        headers=_h("alice", tenant)).json()
    assert detail["choices"][1]["body"] == ["2"]


def test_question_edit_apply_scopes_to_target(client):
    tenant, doc = _seed_doc(client)
    res = client.post(
        f"/api/documents/{doc.id}/questions/q_bad/edit",
        json={"instruction": "②번 보기를 -35로 수정해", "apply": True},
        headers=_h("alice", tenant))
    assert res.status_code == 200, res.text
    assert res.json()["applied"] is True
    detail = client.get(
        f"/api/documents/{doc.id}/questions/q_bad",
        headers=_h("alice", tenant)).json()
    assert detail["choices"][1]["body"] == ["-35"]
    # USER_EDITED (still has no other unresolved issues left)
    assert detail["status"] in ("USER_EDITED", "NEEDS_USER_REVIEW")
    # q_ok is untouched
    ok = client.get(
        f"/api/documents/{doc.id}/questions/q_ok",
        headers=_h("alice", tenant)).json()
    assert ok["choices"][1]["body"] == ["2"]
    assert ok["status"] == "AUTO_RESTORED"


def test_question_edit_ambiguous_is_not_applied(client):
    tenant, doc = _seed_doc(client)
    res = client.post(
        f"/api/documents/{doc.id}/questions/q_bad/edit",
        json={"instruction": "3번 보기를 -35로 수정해", "apply": True},
        headers=_h("alice", tenant))
    # "3번" inside an 11-question context: choice edit to label ③.
    # And a wrong-question-number instruction is clarification-only:
    res2 = client.post(
        f"/api/documents/{doc.id}/questions/q_bad/edit",
        json={"instruction": "7번 문제를 수정해", "apply": True},
        headers=_h("alice", tenant))
    assert res2.json()["ok"] is False
    assert res2.json()["needs_clarification"] is True


def test_question_confirm_marks_user_confirmed(client):
    tenant, doc = _seed_doc(client)
    res = client.post(
        f"/api/documents/{doc.id}/questions/q_bad/confirm",
        headers=_h("alice", tenant))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "USER_CONFIRMED"
    detail = client.get(
        f"/api/documents/{doc.id}/questions/q_bad",
        headers=_h("alice", tenant)).json()
    assert detail["status"] == "USER_CONFIRMED"


def test_best_effort_export_allowed_with_review_items(client):
    tenant, doc = _seed_doc(client)
    res = client.post(
        f"/api/documents/{doc.id}/restoration/export",
        json={"format": "json"},
        headers=_h("alice", tenant))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["restoration_status"] == "NEEDS_USER_REVIEW"
    assert body["counts"]["NEEDS_USER_REVIEW"] == 1
    assert body["final"] is False
    dl = client.get(
        f"/api/documents/{doc.id}/restoration/files/{body['file']}",
        headers=_h("alice", tenant))
    assert dl.status_code == 200
    assert dl.headers["x-restoration-status"] == "NEEDS_USER_REVIEW"
    # Legacy strict export is still gated
    res = client.post(
        f"/api/documents/{doc.id}/exports",
        json={"format": "hwpx"},
        headers=_h("alice", tenant))
    assert res.status_code == 422


def test_restoration_export_hwpx_and_pdf(client):
    tenant, doc = _seed_doc(client)
    for fmt in ("hwpx", "pdf", "docx"):
        res = client.post(
            f"/api/documents/{doc.id}/restoration/export",
            json={"format": fmt},
            headers=_h("alice", tenant))
        assert res.status_code == 200, f"{fmt}: {res.text}"
        assert res.json()["file"].endswith(f".{fmt}")


# --- Tesseract second-observer adapter --------------------------------------

_TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop"
    "\twidth\theight\tconf\ttext\n"
    "5\t1\t1\t1\t1\t1\t60\t60\t30\t30\t95\t1.\n"
    "5\t1\t1\t1\t1\t2\t95\t60\t200\t30\t90\t다음\t중\n"
    "5\t1\t1\t1\t2\t1\t60\t120\t30\t30\t90\t①\n"
    "5\t1\t1\t1\t2\t2\t100\t120\t40\t30\t88\t3\n"
    "5\t1\t2\t1\t1\t1\t60\t400\t30\t30\t92\t2.\n"
    "5\t1\t2\t1\t1\t2\t95\t400\t300\t30\t91\t두\t점\n"
)


def test_tesseract_tsv_groups_words_into_lines(tmp_path):
    from unittest.mock import patch

    from PIL import Image

    from providers.ocr.tesseract import TesseractOCRProvider

    img = tmp_path / "p.png"
    Image.new("RGB", (200, 200), "white").save(img)
    provider = TesseractOCRProvider(binary="tesseract")
    with patch.object(provider, "_run", return_value=_TSV):
        cands = provider.recognize_text(img)
    assert len(cands) == 3  # three TSV lines
    assert cands[0].value.startswith("1.")
    assert cands[0].meta["bbox_px"][1] == 60
    # per-question region crop offsets bbox_px back into page space
    from document.models import BBox

    with patch.object(provider, "_run", return_value=_TSV):
        cropped = provider.recognize_text(img, BBox(x=100, y=100, w=50, h=50))
    assert cropped[0].meta["bbox_px"][0] == 60 + 100


def test_tesseract_page_extractor_is_second_observer(tmp_path):
    from unittest.mock import patch

    from providers.vision.tesseract_page import TesseractPageExtractor

    img = tmp_path / "p.png"
    img.write_bytes(b"png")
    ex = TesseractPageExtractor()
    with patch.object(
        ex._ocr, "recognize_text", return_value=[]
    ) as m:
        out = ex.extract_page(img)
    assert m.called
    assert out and out[0].provider == "tesseract-page"
    # distinct engine family -> distinct consensus source key
    from core.examdna.source_truth.consensus import _source_key

    assert _source_key("tesseract-page") != _source_key("local-vision-page:x")


def test_tesseract_opt_in_only(monkeypatch):
    import providers.vision as pv
    import providers.ocr as po

    monkeypatch.delenv("EXAMDNA_TESSERACT", raising=False)
    names = [type(p).__name__ for p in pv.get_page_extractors()]
    assert "TesseractPageExtractor" not in names
    names = [type(p).__name__ for p in po.get_providers()]
    assert "TesseractOCRProvider" not in names
