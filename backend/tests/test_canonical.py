from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canonical.models import (
    ArtifactState,
    ChangeOp,
    CheckState,
    JobV2,
    JobV2State,
)
from canonical.service import MutationService
from canonical.store import (
    CanonicalStore,
    ConflictError,
    IdempotencyConflictError,
    NotFoundError,
    PreconditionError,
    StaleWorkerError,
    ValidationError,
)
from document.models import Document, Question
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
    d.questions.append(Question(number=1, label="1"))
    return d


def _setup(service: MutationService, tenant="tn_1"):
    doc = _doc(tenant)
    rev = service.create_revision(doc, tenant, "alice")
    return doc, rev


# --- revision + CAS ---------------------------------------------------------------


def test_create_revision_and_head(service, cstore):
    doc, rev = _setup(service)
    assert rev.revision_no == 1
    assert cstore.get_document(doc.id).head_revision_id == rev.id
    assert rev.content_hash and rev.style_hash and rev.solution_hash


def test_missing_if_match_is_428(service):
    doc, rev = _setup(service)
    with pytest.raises(PreconditionError):
        service.apply(
            "tn_1",
            "alice",
            doc.id,
            None,
            [ChangeOp(op="SetMetadata", field="grade", value="중2")],
            route="changes",
        )


def test_stale_if_match_is_409(service):
    doc, rev = _setup(service)
    service.apply(
        "tn_1",
        "alice",
        doc.id,
        rev.id,
        [ChangeOp(op="SetMetadata", field="grade", value="중2")],
        route="changes",
    )
    with pytest.raises(ConflictError) as ei:
        service.apply(
            "tn_1",
            "alice",
            doc.id,
            rev.id,  # stale head
            [ChangeOp(op="SetMetadata", field="grade", value="중3")],
            route="changes",
        )
    assert ei.value.code == "REVISION_CONFLICT"
    assert ei.value.details["current_revision_id"] != rev.id


def test_undo_creates_new_revision_not_overwrite(service, cstore):
    doc, rev1 = _setup(service)
    rev2 = service.apply(
        "tn_1",
        "alice",
        doc.id,
        rev1.id,
        [ChangeOp(op="SetMetadata", field="grade", value="중2")],
        route="changes",
    )
    rev3 = service.undo("tn_1", "alice", doc.id, rev2.id, rev1.id, "revert")
    assert rev3.revision_no == 3
    assert rev3.parent_revision_id == rev2.id
    assert rev3.restores_revision_id == rev1.id
    # head now points to rev3; rev1/2 remain immutable snapshots
    assert cstore.get_document(doc.id).head_revision_id == rev3.id
    assert cstore.get_revision(rev1.id).content_json != cstore.get_revision(rev2.id).content_json
    assert cstore.get_revision(rev3.id).content_json == cstore.get_revision(rev1.id).content_json


def test_content_change_invalidates_checks(service, cstore):
    doc, rev1 = _setup(service)
    # pretend a check passed on rev1
    from canonical.models import CheckRun

    cstore.upsert_check(
        CheckRun(
            tenant_id="tn_1",
            revision_id=rev1.id,
            check_kind="SCHEMA_REFERENTIAL_INTEGRITY",
            input_digest=rev1.content_hash,
            state=CheckState.PASSED,
        )
    )
    service.apply(
        "tn_1",
        "alice",
        doc.id,
        rev1.id,
        [ChangeOp(op="SetMetadata", field="grade", value="중2")],
        route="changes",
    )
    old = {
        c.check_kind: c for c in cstore.get_checks(rev1.id)
    }["SCHEMA_REFERENTIAL_INTEGRITY"]
    assert old.applicable is False and old.stale_reason


def test_field_digest_conflict(service):
    doc, rev = _setup(service)
    from canonical.models import sha256_json

    wrong = sha256_json("not-the-current-value")
    with pytest.raises(ConflictError) as ei:
        service.apply(
            "tn_1",
            "alice",
            doc.id,
            rev.id,
            [
                ChangeOp(
                    op="SetMetadata",
                    field="grade",
                    value="중2",
                    expected_old_digest=wrong,
                )
            ],
            route="changes",
        )
    assert ei.value.code == "FIELD_CONFLICT"


# --- idempotency ---------------------------------------------------------------------


def test_idempotency_replay_and_conflict(service):
    doc, rev = _setup(service)
    ops = [ChangeOp(op="SetMetadata", field="grade", value="중2")]
    body = {"ops": [o.model_dump() for o in ops]}
    r1 = service.apply(
        "tn_1", "alice", doc.id, rev.id, ops,
        route="changes", idempotency_key="k1", request_body=body,
    )
    # same key + same payload -> same revision returned, no new revision
    head = cstore_head = None
    r2 = service.apply(
        "tn_1", "alice", doc.id, r1.id, ops,
        route="changes", idempotency_key="k1", request_body=body,
    )
    assert r2.id == r1.id
    # same key + different payload -> 409 IDEMPOTENCY_CONFLICT
    ops2 = [ChangeOp(op="SetMetadata", field="grade", value="중3")]
    with pytest.raises(IdempotencyConflictError):
        service.apply(
            "tn_1", "alice", doc.id, r1.id, ops2,
            route="changes", idempotency_key="k1",
            request_body={"ops": [o.model_dump() for o in ops2]},
        )


# --- checks / eligibility -----------------------------------------------------------


def test_unrun_checks_block_final(service, cstore):
    doc, rev = _setup(service)
    elig = service.compute_eligibility(doc.id, "tn_1")
    assert elig["content_ready"] is False
    assert all(f["final_eligible"] is False for f in elig["formats"].values())
    states = {c["check_kind"]: c["state"] for c in elig["content_checks"]}
    assert states["SCHEMA_REFERENTIAL_INTEGRITY"] == "NOT_RUN"


def test_failed_check_creates_blocking_issue(service, cstore):
    doc, rev = _setup(service)
    # doc has one question with no ATUs -> SOURCE_REGION_COVERAGE fails
    checks = service.run_checks(rev.id)
    by_kind = {c.check_kind: c for c in checks}
    assert by_kind["SCHEMA_REFERENTIAL_INTEGRITY"].state == CheckState.PASSED
    assert by_kind["SOURCE_REGION_COVERAGE"].state == CheckState.FAILED
    blocking = cstore.list_issues(rev.id, blocking_only=True)
    assert any(i.kind == "SOURCE_REGION_COVERAGE" for i in blocking)


def test_final_export_requires_proof_binding(service, cstore, tmp_path):
    doc, rev = _setup(service)
    svc = service
    art = svc.register_draft_artifact(
        "tn_1", doc.id, rev.id, "hwpx", "local://x", "sha", 10
    )
    # DRAFT artifact cannot be exported as final
    with pytest.raises(ValidationError):
        svc.export_final("tn_1", doc.id, rev.id, [art.id])

    # record a partial proof -> still not eligible
    svc.record_proof(art.id, {"FORMAT_OPEN_VALIDITY": "PASSED"}, "w1")
    with pytest.raises(ValidationError):
        svc.export_final("tn_1", doc.id, rev.id, [art.id])

    # force all content checks PASSED + all required artifact checks
    from canonical.models import CheckRun
    from canonical.policy import restore_policy

    policy = restore_policy()
    for kind in policy.required_content_checks:
        cstore.upsert_check(
            CheckRun(
                tenant_id="tn_1",
                revision_id=rev.id,
                check_kind=kind,
                input_digest=rev.content_hash,
                state=CheckState.PASSED,
            )
        )
    # clear blocking issues created by earlier failed run
    for i in cstore.list_issues(rev.id, blocking_only=True):
        from canonical.models import IssueState

        cstore.set_issue_state(i.id, IssueState.RESOLVED)

    svc.record_proof(
        art.id,
        {k: "PASSED" for k in policy.required_artifact_checks_by_format["hwpx"]},
        "w1",
    )
    art = cstore.get_artifact(art.id)
    assert art.state == ArtifactState.FINAL_ELIGIBLE
    out = svc.export_final("tn_1", doc.id, rev.id, [art.id])
    assert out[0].state == ArtifactState.FINAL

    # exporting against an old revision after head moved is rejected
    rev2 = svc.apply(
        "tn_1", "alice", doc.id, rev.id,
        [ChangeOp(op="SetMetadata", field="grade", value="중2")],
        route="changes",
    )
    with pytest.raises(ConflictError):
        svc.export_final("tn_1", doc.id, rev.id, [art.id])


# --- durable jobs -----------------------------------------------------------------------


def test_job_claim_heartbeat_commit(cstore):
    job = cstore.create_job(JobV2(tenant_id="tn_1", document_id="d1"))
    claimed = cstore.claim_job("w1")
    assert claimed is not None and claimed.id == job.id
    assert claimed.lease_token and claimed.attempt_count == 1
    cstore.heartbeat(job.id, claimed.lease_token)
    ev = cstore.commit_job_stage(job.id, claimed.lease_token, "extract")
    assert ev.seq == 1
    # wrong token -> fenced out
    with pytest.raises(StaleWorkerError):
        cstore.commit_job_stage(job.id, "lease_bad", "extract")
    cstore.finish_job(job.id, claimed.lease_token, JobV2State.SUCCEEDED)
    assert cstore.get_job(job.id).state == JobV2State.SUCCEEDED


def test_stale_worker_cannot_commit_after_lease_loss(cstore):
    job = cstore.create_job(JobV2(tenant_id="tn_1", document_id="d1"))
    c1 = cstore.claim_job("w1")
    # simulate lease expiry then reclaim by another worker
    with cstore._lock, cstore._conn:
        cstore._conn.execute(
            "UPDATE jobs SET lease_expires_at=? WHERE id=?",
            (time.time() - 1, job.id),
        )
    c2 = cstore.claim_job("w2")
    assert c2 is not None and c2.lease_token != c1.lease_token
    with pytest.raises(StaleWorkerError):
        cstore.commit_job_stage(job.id, c1.lease_token, "extract")
    with pytest.raises(StaleWorkerError):
        cstore.finish_job(job.id, c1.lease_token, JobV2State.SUCCEEDED)
    cstore.finish_job(job.id, c2.lease_token, JobV2State.SUCCEEDED)


def test_cancel_vs_commit_race(cstore):
    job = cstore.create_job(JobV2(tenant_id="tn_1", document_id="d1"))
    c = cstore.claim_job("w1")
    cstore.request_cancel(job.id)
    # late output after cancel cannot become success
    with pytest.raises(ConflictError) as ei:
        cstore.finish_job(job.id, c.lease_token, JobV2State.SUCCEEDED)
    assert ei.value.code == "ALREADY_CANCELLED"
    # the lease-owning worker can still close the job as CANCELLED
    cstore.finish_job(job.id, c.lease_token, JobV2State.CANCELLED)
    assert cstore.get_job(job.id).state == JobV2State.CANCELLED


def test_cancel_after_complete_is_409(cstore):
    job = cstore.create_job(JobV2(tenant_id="tn_1", document_id="d1"))
    c = cstore.claim_job("w1")
    cstore.finish_job(job.id, c.lease_token, JobV2State.SUCCEEDED)
    with pytest.raises(ConflictError) as ei:
        cstore.request_cancel(job.id)
    assert ei.value.code == "ALREADY_COMPLETED"


def test_lease_recovery(cstore):
    job = cstore.create_job(JobV2(tenant_id="tn_1", document_id="d1"))
    cstore.claim_job("w1")
    with cstore._lock, cstore._conn:
        cstore._conn.execute(
            "UPDATE jobs SET lease_expires_at=? WHERE id=?",
            (time.time() - 1, job.id),
        )
    assert cstore.recover_expired_leases() == 1
    assert cstore.get_job(job.id).state == JobV2State.RETRY_SCHEDULED


def test_events_seq_and_replay(cstore):
    job = cstore.create_job(JobV2(tenant_id="tn_1", document_id="d1"))
    c = cstore.claim_job("w1")
    cstore.commit_job_stage(job.id, c.lease_token, "a")
    cstore.commit_job_stage(job.id, c.lease_token, "b")
    cstore.commit_job_stage(job.id, c.lease_token, "c")
    events = cstore.events_since(job.id, 0)
    assert [e.seq for e in events] == [1, 2, 3]
    replay = cstore.events_since(job.id, 1)
    assert [e.seq for e in replay] == [2, 3]
    assert cstore.max_event_seq(job.id) == 3
