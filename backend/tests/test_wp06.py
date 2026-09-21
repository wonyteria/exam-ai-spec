"""WP06 contract tests: typed review resolution -> canonical mutation,
AI edit-plan translation + atomic apply, edit invalidation
(VERIFIED_FINAL discard), label-conflict safety, no-op/invalid ops,
history/undo/redo, shared-stem propagation, missing-question recovery.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canonical.models import ChangeOp, CheckState
from canonical.service import MutationService
from canonical.store import (
    CanonicalStore,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from core.examdna.editing import ops_to_change_ops
from document.models import (
    ATU,
    ATUKind,
    Answer,
    Choice,
    Document,
    Equation,
    Question,
    TextSpan,
    VerificationStatus,
)
from tenancy.db import TenancyDB


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


def _doc(tenant="tn_1") -> Document:
    d = Document(tenant_id=tenant)
    for n in (1, 2, 3):
        q = Question(
            number=n,
            label=str(n),
            body=[TextSpan(text=f"문제 {n} 본문")],
            choices=[Choice(label="①", body=[TextSpan(text="보기")])],
            answer=Answer(value="1"),
            atus=[
                ATU(
                    kind=ATUKind.TEXT_TOKEN,
                    field="body",
                    value=f"본문{n}?",
                )
            ],
        )
        d.questions.append(q)
    return d


def _setup(service, tenant="tn_1"):
    doc = _doc(tenant)
    rev = service.create_revision(doc, tenant, "alice")
    return doc, rev


def _content(cstore, rev):
    return Document.model_validate(cstore.get_revision(rev.id).content_json)


# --- typed review resolution ---------------------------------------------------


def test_resolve_atu_confirmed_value_in_revision(service, cstore):
    doc, rev = _setup(service)
    atu = doc.questions[0].atus[0]
    rev2 = service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="ResolveATU", target_id=atu.id, value="확정 본문")],
        route="review.resolve",
    )
    d2 = _content(cstore, rev2)
    resolved = d2.questions[0].atus[0]
    assert resolved.value == "확정 본문"
    assert resolved.status.value == "HUMAN_VERIFIED"
    # the stored snapshot carries the confirmed value — preview/output
    # read the same canonical content (확정값 = 실제 출력)
    assert rev2.revision_no == 2


# --- AI edit plan -> canonical -----------------------------------------------------


def test_ops_to_change_ops_translation():
    ops = [
        {"question": "1", "field": "body", "value": "새 본문"},
        {"question": "2", "field": "choice", "choice": "②", "value": "새 보기"},
        {"question": "3", "field": "points", "value": 5},
        {"question": "1", "field": "answer", "value": "3"},
        {"question": "2", "field": "equation", "index": 0, "value": "x^2"},
        {"question": "9", "field": "teleport", "value": "x"},  # unsupported
        {"field": "body", "value": "x"},  # no target
    ]
    change_ops, skipped = ops_to_change_ops(ops)
    assert len(change_ops) == 5
    assert len(skipped) == 2
    assert change_ops[0].op == "SetBody"
    assert change_ops[1].op == "SetChoice" and change_ops[1].field == "②"
    assert change_ops[4].op == "SetEquation" and change_ops[4].field == "0"


def test_edit_plan_atomicity_no_partial_mutation(service, cstore):
    """A plan mixing a valid op with a bad target fails entirely — the
    revision count must not move (atomicity, no partial mutation)."""
    doc, rev = _setup(service)
    with pytest.raises(NotFoundError):
        service.apply(
            "tn_1", "alice", doc.id, rev.id,
            [
                ChangeOp(op="SetAnswer", target_id="1", value="2"),
                ChangeOp(op="SetAnswer", target_id="ghost", value="3"),
            ],
            route="edits",
        )
    assert cstore.get_document(doc.id).head_revision_id == rev.id


def test_edit_ops_applied(service, cstore):
    doc, rev = _setup(service)
    rev2 = service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [
            ChangeOp(op="SetBody", target_id="1", value="수정된 본문"),
            ChangeOp(op="SetChoice", target_id="2", field="①", value="수정된 보기"),
            ChangeOp(op="SetAnswer", target_id="3", value="4"),
        ],
        route="edits",
    )
    d2 = _content(cstore, rev2)
    assert d2.questions[0].body[0].text == "수정된 본문"
    assert d2.questions[1].choices[0].body[0].text == "수정된 보기"
    assert d2.questions[2].answer.value == "4"


def test_set_equation_index(service, cstore):
    doc, rev = _setup(service)
    doc.questions[0].equations.append(Equation(latex="x+1"))
    rev = service.create_revision(doc, "tn_1", "alice")
    rev2 = service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="SetEquation", target_id="1", field="0", value="x^2=4")],
        route="edits",
    )
    d2 = _content(cstore, rev2)
    assert d2.questions[0].equations[0].latex == "x^2=4"
    with pytest.raises(ValidationError):
        service.apply(
            "tn_1", "alice", doc.id, rev2.id,
            [ChangeOp(op="SetEquation", target_id="1", field="9", value="z")],
            route="edits",
        )


# --- edit invalidation --------------------------------------------------------------


def test_edit_discards_verified_final(service, cstore):
    doc = _doc()
    doc.verification.status = "VERIFIED_FINAL"
    rev = service.create_revision(doc, "tn_1", "alice")
    rev2 = service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="SetAnswer", target_id="1", value="2")],
        route="edits",
    )
    d2 = _content(cstore, rev2)
    assert d2.verification.status == "NEEDS_REVIEW"


def test_answer_edit_invalidates_solver_checks(service, cstore):
    doc, rev = _setup(service)
    from canonical.models import CheckRun

    cstore.upsert_check(
        CheckRun(
            tenant_id="tn_1", revision_id=rev.id,
            check_kind="ANSWER_SOLUTION_LOGIC",
            input_digest=rev.solution_hash, state=CheckState.PASSED,
        )
    )
    service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="SetAnswer", target_id="1", value="5")],
        route="edits",
    )
    old = {
        c.check_kind: c for c in cstore.get_checks(rev.id)
    }["ANSWER_SOLUTION_LOGIC"]
    assert old.applicable is False and old.stale_reason


# --- label-conflict safety ------------------------------------------------------------


def test_label_conflict_does_not_touch_wrong_question(service):
    """q2 has number=2, q5 has label='2' — target '2' is ambiguous and must
    fail closed rather than silently editing either one."""
    doc = _doc()
    doc.questions[2].label = "2"  # q3's label now collides with q2's number
    rev = service.create_revision(doc, "tn_1", "alice")
    with pytest.raises(ConflictError) as ei:
        service.apply(
            "tn_1", "alice", doc.id, rev.id,
            [ChangeOp(op="SetAnswer", target_id="2", value="9")],
            route="edits",
        )
    assert ei.value.code == "AMBIGUOUS_TARGET"


# --- concurrency / no-op / invalid ------------------------------------------------------


def test_concurrent_tabs_second_apply_409(service):
    doc, rev = _setup(service)
    service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="SetMetadata", field="grade", value="중2")],
        route="changes",
    )
    # second tab still holds the old If-Match -> 409
    with pytest.raises(ConflictError) as ei:
        service.apply(
            "tn_1", "bob", doc.id, rev.id,
            [ChangeOp(op="SetMetadata", field="grade", value="중3")],
            route="changes",
        )
    assert ei.value.code == "REVISION_CONFLICT"


def test_noop_ops_rejected(service):
    doc, rev = _setup(service)
    current_grade = doc.metadata.grade  # ""
    with pytest.raises(ValidationError) as ei:
        service.apply(
            "tn_1", "alice", doc.id, rev.id,
            [ChangeOp(op="SetMetadata", field="grade", value=current_grade)],
            route="changes",
        )
    assert "no-op" in str(ei.value)
    assert service.store.get_document(doc.id).head_revision_id == rev.id


def test_invalid_op_rejected(service):
    doc, rev = _setup(service)
    with pytest.raises(ValidationError):
        service.apply(
            "tn_1", "alice", doc.id, rev.id,
            [ChangeOp(op="SetField", target_id="1", field="id", value="hack")],
            route="changes",
        )
    with pytest.raises(ValidationError):
        service.apply(
            "tn_1", "alice", doc.id, rev.id,
            [ChangeOp(op="SetField", target_id="1", field="body", value="x")],
            route="changes",
        )


# --- history / undo / redo --------------------------------------------------------------


def test_history_persists_across_reload(cstore, tenancy):
    svc = MutationService(cstore, tenancy)
    doc, rev = _setup(svc)
    rev2 = svc.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="SetAnswer", target_id="1", value="2")],
        route="edits",
    )
    # "reload": a fresh service over the same store sees the full history
    svc2 = MutationService(cstore, tenancy)
    revs = cstore.list_revisions(doc.id)
    assert [r.revision_no for r in revs] == [1, 2]
    rev3 = svc2.undo("tn_1", "alice", doc.id, rev2.id, rev.id, "revert")
    assert rev3.restores_revision_id == rev.id


def test_undo_then_redo(service, cstore):
    doc, rev = _setup(service)
    rev2 = service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="SetAnswer", target_id="1", value="2")],
        route="edits",
    )
    rev3 = service.undo("tn_1", "alice", doc.id, rev2.id, rev.id, "revert")
    assert _content(cstore, rev3).questions[0].answer.value == "1"
    rev4 = service.redo("tn_1", "alice", doc.id, rev3.id)
    assert _content(cstore, rev4).questions[0].answer.value == "2"
    assert rev4.mode.value == "UNDO"


def test_redo_on_non_undo_head_409(service):
    doc, rev = _setup(service)
    with pytest.raises(ConflictError) as ei:
        service.redo("tn_1", "alice", doc.id, rev.id)
    assert ei.value.code == "NOTHING_TO_REDO"


# --- shared-stem propagation -------------------------------------------------------------


def test_propagate_setbody_to_children(service, cstore):
    doc = _doc()
    parent = doc.questions[0]
    child = Question(number=4, label="1-1", parent_id=parent.id)
    doc.questions.append(child)
    rev = service.create_revision(doc, "tn_1", "alice")
    # without propagate the child keeps its own body
    rev2 = service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="SetBody", target_id=parent.id, value="공통 지문")],
        route="edits",
    )
    d2 = _content(cstore, rev2)
    assert d2.questions[-1].body == []
    # with propagate the shared stem flows to the child
    rev3 = service.apply(
        "tn_1", "alice", doc.id, rev2.id,
        [
            ChangeOp(
                op="SetBody", target_id=parent.id,
                value="공통 지문 v2", propagate=True,
            )
        ],
        route="edits",
    )
    d3 = _content(cstore, rev3)
    child2 = next(q for q in d3.questions if q.parent_id == parent.id)
    assert child2.body[0].text == "공통 지문 v2"


# --- missing-question recovery -------------------------------------------------------------


def test_add_question_recovery(service, cstore):
    doc, rev = _setup(service)
    rev2 = service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [
            ChangeOp(
                op="AddQuestion",
                value={"number": 4, "label": "4"},
            )
        ],
        route="edits",
    )
    d2 = _content(cstore, rev2)
    assert [q.number for q in d2.questions] == [1, 2, 3, 4]
    # duplicate number/label -> conflict, never a silent merge
    with pytest.raises(ConflictError) as ei:
        service.apply(
            "tn_1", "alice", doc.id, rev2.id,
            [ChangeOp(op="AddQuestion", value={"number": 4, "label": "4"})],
            route="edits",
        )
    assert ei.value.code == "QUESTION_EXISTS"


# --- masked-anchor renumbering -----------------------------------------------------


def test_setfield_number_confirms_ambiguous_label(service, cstore):
    """A '?'-labeled question (masked number anchor) is confirmed to its
    real printed number via SetField number — the review path for
    ?markN items. `number` is the positional sequence (dense 1..N) and
    stays put; the printed number lives on `label`."""
    d = Document(tenant_id="tn_1")
    q = Question(number=99, label="?mark1", body=[TextSpan(text="본문")])
    d.questions.append(q)
    rev = service.create_revision(d, "tn_1", "alice")

    rev2 = service.apply(
        "tn_1", "alice", d.id, rev.id,
        [ChangeOp(op="SetField", target_id="?mark1", field="number", value=4)],
        route="review.renumber",
    )
    d2 = _content(cstore, rev2)
    assert d2.questions[0].label == "4"  # printed number confirmed
    assert d2.questions[0].number == 99  # positional sequence untouched
    assert rev2.revision_no == 2


def test_setfield_number_rejects_collision(service, cstore):
    doc, rev = _setup(service)
    with pytest.raises(ConflictError) as ei:
        service.apply(
            "tn_1", "alice", doc.id, rev.id,
            [ChangeOp(op="SetField", target_id="1", field="number", value=2)],
            route="edits",
        )
    assert ei.value.code == "NUMBER_EXISTS"


def test_setfield_number_rejects_non_integer(service, cstore):
    doc, rev = _setup(service)
    with pytest.raises(ValidationError):
        service.apply(
            "tn_1", "alice", doc.id, rev.id,
            [ChangeOp(op="SetField", target_id="1", field="number", value="네")],
            route="edits",
        )


def test_setfield_number_replaces_descriptive_label(service, cstore):
    """Confirming a printed number overwrites whatever label was there —
    the reviewer is asserting the printed number, so '논술2' -> '7'."""
    d = Document(tenant_id="tn_1")
    q = Question(number=99, label="논술2", body=[TextSpan(text="본문")])
    d.questions.append(q)
    rev = service.create_revision(d, "tn_1", "alice")
    service.apply(
        "tn_1", "alice", d.id, rev.id,
        [ChangeOp(op="SetField", target_id="논술2", field="number", value=7)],
        route="edits",
    )
    d2 = _content(cstore, cstore.get_head_revision(d.id))
    assert d2.questions[0].label == "7"
    assert d2.questions[0].number == 99  # sequence position unchanged


# --- ResolveATU materialization into derived fields --------------------------


def _doc_with_unverified_atu() -> Document:
    d = Document(tenant_id="tn_1")
    q = Question(
        number=1,
        label="?mark1",
        body=[],
        atus=[
            ATU(kind=ATUKind.TEXT_TOKEN, field="body", value=None,
                status=VerificationStatus.CONFLICT),
            ATU(kind=ATUKind.CHOICE, field="choice:①", value=None,
                status=VerificationStatus.UNVERIFIED),
            ATU(kind=ATUKind.QUESTION_NUMBER, field="number", value=None,
                status=VerificationStatus.UNVERIFIED),
        ],
    )
    d.questions.append(q)
    return d


def test_resolve_atu_materializes_body(service, cstore):
    """Resolving a body ATU must reach q.body — materialization only ran
    at pipeline time, so without sync the renderer sees an empty body."""
    d = _doc_with_unverified_atu()
    rev = service.create_revision(d, "tn_1", "alice")
    atu = d.questions[0].atus[0]
    rev2 = service.apply(
        "tn_1", "alice", d.id, rev.id,
        [ChangeOp(op="ResolveATU", target_id=atu.id, value="확정된 본문")],
        route="review.resolve",
    )
    d2 = _content(cstore, rev2)
    q = d2.questions[0]
    assert [s.text for s in q.body] == ["확정된 본문"]
    assert atu.id in q.body[0].atu_ids


def test_resolve_atu_updates_span_in_place(service, cstore):
    """Re-resolving the same ATU updates its span, never duplicates."""
    d = _doc_with_unverified_atu()
    rev = service.create_revision(d, "tn_1", "alice")
    atu_id = d.questions[0].atus[0].id
    rev2 = service.apply(
        "tn_1", "alice", d.id, rev.id,
        [ChangeOp(op="ResolveATU", target_id=atu_id, value="첫 확정")],
        route="review.resolve",
    )
    rev3 = service.apply(
        "tn_1", "alice", d.id, rev2.id,
        [ChangeOp(op="ResolveATU", target_id=atu_id, value="재확정")],
        route="review.resolve",
    )
    d3 = _content(cstore, rev3)
    assert [s.text for s in d3.questions[0].body] == ["재확정"]


def test_resolve_atu_materializes_choice_and_number(service, cstore):
    d = _doc_with_unverified_atu()
    rev = service.create_revision(d, "tn_1", "alice")
    choice_atu = d.questions[0].atus[1]
    num_atu = d.questions[0].atus[2]
    rev2 = service.apply(
        "tn_1", "alice", d.id, rev.id,
        [
            ChangeOp(op="ResolveATU", target_id=choice_atu.id, value="보기 내용"),
            ChangeOp(op="ResolveATU", target_id=num_atu.id, value="4"),
        ],
        route="review.resolve",
    )
    d2 = _content(cstore, rev2)
    q = d2.questions[0]
    assert q.label == "4"
    assert q.choices[0].label == "①"
    assert q.choices[0].body[0].text == "보기 내용"


def test_resolve_atu_number_collision_fails_closed(service, cstore):
    """Resolving a number ATU to an existing label must be refused."""
    d = _doc_with_unverified_atu()
    d.questions.append(Question(number=2, label="4"))
    rev = service.create_revision(d, "tn_1", "alice")
    num_atu = d.questions[0].atus[2]
    with pytest.raises(ConflictError) as ei:
        service.apply(
            "tn_1", "alice", d.id, rev.id,
            [ChangeOp(op="ResolveATU", target_id=num_atu.id, value="4")],
            route="review.resolve",
        )
    assert ei.value.code == "NUMBER_EXISTS"
    assert cstore.get_document(d.id).head_revision_id == rev.id


# --- APPROVED_EDIT_CONFORMANCE lineage audit --------------------------------


def test_edit_conformance_passes_clean_lineage(service, cstore):
    doc, rev = _setup(service)
    rev2 = service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="SetPoints", target_id="1", value=5)],
        route="edits",
    )
    state, summary = service._run_one(
        "APPROVED_EDIT_CONFORMANCE", _content(cstore, rev2), rev2
    )
    assert state == CheckState.PASSED
    assert "revisions audited" in summary


def test_edit_conformance_flags_unrecorded_mutation(service, cstore):
    """An EDIT revision with no recorded change set is an unapproved
    mutation — the lineage audit must fail closed."""
    doc, rev = _setup(service)
    rev2 = service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="SetPoints", target_id="1", value=5)],
        route="edits",
    )
    rev2.change_summary = []
    state, _ = service._run_one(
        "APPROVED_EDIT_CONFORMANCE", _content(cstore, rev2), rev2
    )
    assert state == CheckState.FAILED


def test_edit_conformance_flags_tampered_snapshot(service, cstore):
    doc, rev = _setup(service)
    rev2 = service.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="SetPoints", target_id="1", value=5)],
        route="edits",
    )
    rev2.content_hash = "0" * 64  # forged hash on an EDIT revision
    state, summary = service._run_one(
        "APPROVED_EDIT_CONFORMANCE", _content(cstore, rev2), rev2
    )
    assert state == CheckState.FAILED
    assert "hash mismatch" in summary


# --- ORIGINAL_SOURCE_FIDELITY audit -------------------------------------------


class _AuditOCR:
    """Fresh audit-run provider — returns canned text per region."""

    def __init__(self, text: str):
        self._text = text
        self.calls = 0

    def recognize_text(self, image, region=None):
        self.calls += 1
        from document.models import Candidate

        return [Candidate(provider="audit", value=self._text)]


class _Objects:
    def __init__(self, path):
        self._path = path

    def open(self, uri):
        return self._path


def _doc_with_source(tmp_path, atu_status=None) -> Document:
    from document.models import BBox, Page, PageImage, SourceRef

    img = tmp_path / "p0.png"
    img.write_bytes(b"png")
    d = Document(tenant_id="tn_1")
    d.pages.append(Page(index=0, original=PageImage(uri=str(img))))
    body_atu = ATU(
        kind=ATUKind.TEXT_TOKEN, field="body",
        value="직각삼각형의 합동 조건을 고르시오",
        status=atu_status or VerificationStatus.AUTO_VERIFIED,
    )
    q = Question(
        number=1,
        label="1",
        body=[TextSpan(
            text="직각삼각형의 합동 조건을 고르시오", atu_ids=[body_atu.id]
        )],
        source=SourceRef(page=0, bbox=BBox(x=0, y=0, w=100, h=50)),
        atus=[body_atu],
    )
    d.questions.append(q)
    return d


class _Providers:
    def __init__(self, ocr):
        self.ocr = ocr


def test_source_fidelity_passes_on_fresh_audit(service, tmp_path):
    d = _doc_with_source(tmp_path)
    rev = service.create_revision(d, "tn_1", "alice")
    providers = _Providers([_AuditOCR("1. 직각삼각형의 합동 조건을 고르시오")])
    state, summary = service._run_one(
        "ORIGINAL_SOURCE_FIDELITY", d, rev, providers, _Objects(tmp_path / "p0.png")
    )
    assert state == CheckState.PASSED, summary


def test_source_fidelity_fails_on_machine_field_absent(service, tmp_path):
    """AUTO_VERIFIED extraction contradicted by a fresh audit run fails."""
    d = _doc_with_source(tmp_path)  # AUTO_VERIFIED body ATU
    rev = service.create_revision(d, "tn_1", "alice")
    providers = _Providers([_AuditOCR("1. 완전히 다른 문제입니다")])
    state, summary = service._run_one(
        "ORIGINAL_SOURCE_FIDELITY", d, rev, providers, _Objects(tmp_path / "p0.png")
    )
    assert state == CheckState.FAILED
    assert "machine-extracted" in summary


def test_source_fidelity_attested_field_is_not_failure(service, tmp_path):
    """A HUMAN_VERIFIED value absent from source pixels (e.g. occluded
    print confirmed by a reviewer) is an attested exception, not a fail."""
    d = _doc_with_source(tmp_path, atu_status=VerificationStatus.HUMAN_VERIFIED)
    rev = service.create_revision(d, "tn_1", "alice")
    providers = _Providers([_AuditOCR("1. 감춰진 원본 텍스트")])
    state, summary = service._run_one(
        "ORIGINAL_SOURCE_FIDELITY", d, rev, providers, _Objects(tmp_path / "p0.png")
    )
    assert state == CheckState.PASSED, summary
    assert "human-attested" in summary


def test_source_fidelity_not_run_without_provider(service, tmp_path):
    d = _doc_with_source(tmp_path)
    rev = service.create_revision(d, "tn_1", "alice")
    state, _ = service._run_one(
        "ORIGINAL_SOURCE_FIDELITY", d, rev, _Providers([]), _Objects(tmp_path / "p0.png")
    )
    assert state == CheckState.NOT_RUN


def test_source_fidelity_fails_when_nothing_materialized(service, tmp_path):
    d = _doc_with_source(tmp_path)
    d.questions[0].body = []
    d.questions[0].label = "?mark1"  # non-digit label is not audited
    rev = service.create_revision(d, "tn_1", "alice")
    providers = _Providers([_AuditOCR("anything")])
    state, summary = service._run_one(
        "ORIGINAL_SOURCE_FIDELITY", d, rev, providers, _Objects(tmp_path / "p0.png")
    )
    assert state == CheckState.FAILED
    assert "no materialized fields" in summary


# --- REQUIRED_CONTENT_COVERAGE / CURRICULUM_COMPLIANCE ------------------------


def test_content_coverage_fails_without_answers(service, cstore):
    d = _doc(tenant="tn_1")  # scored? _doc has answers but no points/solution
    d.questions[0].points = 3
    rev = service.create_revision(d, "tn_1", "alice")
    state, summary = service._run_one("REQUIRED_CONTENT_COVERAGE", d, rev)
    assert state == CheckState.FAILED
    assert "solution" in summary


def test_content_coverage_passes_fully_covered(service, cstore):
    from document.models import Solution

    d = _doc(tenant="tn_1")
    for q in d.questions:
        q.points = 3
        q.solution = Solution(steps=[TextSpan(text="풀이")])
    rev = service.create_revision(d, "tn_1", "alice")
    state, summary = service._run_one("REQUIRED_CONTENT_COVERAGE", d, rev)
    assert state == CheckState.PASSED, summary


def test_curriculum_flags_undeclared_concept(service, cstore):
    from document.models import Curriculum, Solution

    d = _doc(tenant="tn_1")
    q = d.questions[0]
    q.curriculum = Curriculum(grade="중2", concepts=["합동"])
    q.solution = Solution(steps=[TextSpan(text="x")], concepts=["삼각비"])
    rev = service.create_revision(d, "tn_1", "alice")
    state, summary = service._run_one("CURRICULUM_COMPLIANCE", d, rev)
    assert state == CheckState.FAILED
    assert "삼각비" in summary


def test_curriculum_passes_with_declared_concepts(service, cstore):
    from document.models import Curriculum, Solution

    d = _doc(tenant="tn_1")
    q = d.questions[0]
    q.curriculum = Curriculum(grade="중2", concepts=["합동", "삼각형"])
    q.solution = Solution(steps=[TextSpan(text="x")], concepts=["합동"])
    rev = service.create_revision(d, "tn_1", "alice")
    state, summary = service._run_one("CURRICULUM_COMPLIANCE", d, rev)
    assert state == CheckState.PASSED, summary
