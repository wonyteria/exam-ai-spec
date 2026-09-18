from __future__ import annotations

import hashlib
import time
from typing import Any, Optional

from document.models import Document, VerificationStatus
from tenancy.db import TenancyDB
from tenancy.models import AuditEvent

from .models import (
    Artifact,
    ArtifactProof,
    ArtifactState,
    ChangeOp,
    CheckRun,
    CheckState,
    IdempotencyRecord,
    Issue,
    IssueState,
    Revision,
    RevisionMode,
    SourceManifest,
    new_id,
    sha256_json,
)
from .policy import CONTENT_CHECKS_V1, restore_policy
from .store import (
    CanonicalStore,
    ConflictError,
    IdempotencyConflictError,
    NotFoundError,
    PreconditionError,
    ValidationError,
)

# Which check kinds each hash-family invalidates (02 §5 dependency table,
# reduced to the check granularity we have today).
_CONTENT_CHECKS = set(CONTENT_CHECKS_V1)
_SOLUTION_CHECKS = {
    "SOLVE_TWO_INDEPENDENT_AGREEMENT",
    "ANSWER_SOLUTION_LOGIC",
    "CURRICULUM_COMPLIANCE",
    "REQUIRED_CONTENT_COVERAGE",
}

# Checks with a real validator in this codebase today. Everything else is
# registered NOT_RUN (runnable but not yet implemented) or UNAVAILABLE
# (missing capability) — both block final; neither shrinks the list.
IMPLEMENTED_CHECKERS = {
    "SCHEMA_REFERENTIAL_INTEGRITY",
    "QUESTION_CHOICE_SCORE_COMPLETENESS",
    "SOURCE_REGION_COVERAGE",
    "BLOCKING_ISSUES_CLOSED",
}


def _content_payload(doc: Document, manifest_digest: Optional[str] = None) -> dict:
    """Meaning-bearing content: questions minus answers/solutions, plus
    metadata scope fields and the source page manifest (02: content_hash
    covers the source manifest, so a page reorder changes content_hash)."""
    return {
        "metadata": {
            "subject": doc.metadata.subject,
            "grade": doc.metadata.grade,
            "school": doc.metadata.school,
            "year": doc.metadata.year,
            "semester": doc.metadata.semester,
            "exam_type": doc.metadata.exam_type,
        },
        "manifest_digest": manifest_digest,
        "pages": [p.model_dump() for p in doc.pages],
        "questions": [
            q.model_dump(exclude={"answer", "solution", "verification"})
            for q in doc.questions
        ],
    }


def _solution_payload(doc: Document) -> dict:
    return {
        "answers": [
            {
                "q": q.id,
                "answer": q.answer.model_dump() if q.answer else None,
                "solution": q.solution.model_dump() if q.solution else None,
                "curriculum": q.curriculum.model_dump(),
            }
            for q in doc.questions
        ]
    }


def _style_payload(doc: Document) -> dict:
    return {
        "brand_id": doc.brand_id,
        "template_id": doc.template_id,
        "display_metadata": {
            "school": doc.metadata.school,
            "year": doc.metadata.year,
            "semester": doc.metadata.semester,
            "exam_type": doc.metadata.exam_type,
        },
    }


def revision_hashes(
    doc: Document, manifest_digest: Optional[str] = None
) -> tuple[str, str, str]:
    return (
        sha256_json(_content_payload(doc, manifest_digest)),
        sha256_json(_style_payload(doc)),
        sha256_json(_solution_payload(doc)),
    )


class MutationService:
    """Single funnel for every canonical change (02 §5): authorization has
    already happened at the API layer; this service owns expected-head
    checks, op validation, snapshot/hashes, dependency invalidation,
    audit and the head CAS — all inside store transactions."""

    def __init__(self, store: CanonicalStore, tenancy: TenancyDB):
        self.store = store
        self.tenancy = tenancy

    # -- revision creation -------------------------------------------------

    def create_revision(
        self,
        doc: Document,
        tenant_id: str,
        actor: str,
        mode: RevisionMode = RevisionMode.RESTORE,
        ops_summary: Optional[list[dict]] = None,
        restores_revision_id: Optional[str] = None,
        baseline_revision_id: Optional[str] = None,
        manifest_id: Optional[str] = None,
    ) -> Revision:
        rec = self.store.get_document(doc.id)
        if rec is None:
            rec = self.store.create_document(tenant_id, created_by=actor, doc_id=doc.id)
        parent = self.store.get_head_revision(doc.id)
        if manifest_id is None and parent is not None:
            manifest_id = parent.manifest_id
        manifest = self.store.get_manifest(manifest_id) if manifest_id else None
        c_hash, s_hash, sol_hash = revision_hashes(
            doc, manifest.digest if manifest else None
        )
        rev = Revision(
            document_id=doc.id,
            revision_no=(parent.revision_no + 1) if parent else 1,
            parent_revision_id=parent.id if parent else None,
            mode=mode,
            restore_baseline_revision_id=baseline_revision_id,
            restores_revision_id=restores_revision_id,
            manifest_id=manifest_id,
            metadata_snapshot=doc.metadata.model_dump(),
            template_snapshot={
                "brand_id": doc.brand_id,
                "template_id": doc.template_id,
            },
            content_json=doc.model_dump(),
            content_hash=c_hash,
            style_hash=s_hash,
            solution_hash=sol_hash,
            created_by=actor,
            change_summary=ops_summary or [],
        )
        self.store.insert_revision(rev, expected_head=rec.head_revision_id)
        self._seed_checks(rev)
        return rev

    def _seed_checks(self, rev: Revision) -> None:
        """Register the full required check list for the revision's policy —
        everything starts NOT_RUN so the gate is fail-closed by default."""
        from .policy import edit_policy

        policy = edit_policy() if rev.mode == RevisionMode.EDIT else restore_policy()
        kinds = list(policy.required_content_checks)
        for kind in kinds:
            self.store.upsert_check(
                CheckRun(
                    tenant_id=self.store.get_document(rev.document_id).tenant_id,
                    revision_id=rev.id,
                    check_kind=kind,
                    input_digest=rev.content_hash,
                    policy_version=rev.policy_version,
                    state=CheckState.NOT_RUN,
                )
            )

    # -- mutations -------------------------------------------------------------

    def apply(
        self,
        tenant_id: str,
        actor: str,
        doc_id: str,
        if_match: Optional[str],
        ops: list[ChangeOp],
        route: str,
        idempotency_key: Optional[str] = None,
        request_body: Optional[dict] = None,
        mode: RevisionMode = RevisionMode.EDIT,
    ) -> Revision:
        """Apply typed ops atomically: If-Match CAS, op validation, new
        immutable snapshot, hash recompute, check invalidation, audit."""
        rec = self._require_active_document(doc_id, tenant_id)
        expected = self._require_if_match(rec, if_match)

        replayed = self._idempotent_replay(
            tenant_id, actor, route, idempotency_key, request_body
        )
        if replayed is not None:
            rev = self.store.get_revision(replayed.resource_id or "")
            if rev is not None:
                return rev

        head = self.store.get_revision(expected)
        assert head is not None
        doc = Document.model_validate(head.content_json)
        summary = self._apply_ops(doc, ops)

        head_manifest = (
            self.store.get_manifest(head.manifest_id) if head.manifest_id else None
        )
        c_hash, s_hash, sol_hash = revision_hashes(
            doc, head_manifest.digest if head_manifest else None
        )
        rev = Revision(
            document_id=doc_id,
            revision_no=head.revision_no + 1,
            parent_revision_id=head.id,
            mode=mode,
            restore_baseline_revision_id=(
                head.restore_baseline_revision_id or head.id
            ),
            manifest_id=head.manifest_id,
            metadata_snapshot=doc.metadata.model_dump(),
            template_snapshot={
                "brand_id": doc.brand_id,
                "template_id": doc.template_id,
            },
            content_json=doc.model_dump(),
            content_hash=c_hash,
            style_hash=s_hash,
            solution_hash=sol_hash,
            created_by=actor,
            change_summary=summary,
        )

        # Dependency invalidation: which old-check results no longer apply.
        stale: list[str] = []
        if c_hash != head.content_hash:
            stale += sorted(_CONTENT_CHECKS)
        elif sol_hash != head.solution_hash:
            stale += sorted(_SOLUTION_CHECKS)

        self.store.insert_revision(rev, expected_head=expected)
        self._seed_checks(rev)
        if stale:
            self.store.mark_checks_stale(head.id, stale, "superseded by new revision")

        self.tenancy.audit(
            AuditEvent(
                tenant_id=tenant_id,
                user_id=actor,
                action="document.mutation",
                object_type="document",
                object_id=doc_id,
                detail={
                    "revision_id": rev.id,
                    "revision_no": rev.revision_no,
                    "ops": summary,
                },
            )
        )
        if idempotency_key:
            self.store.idempotency_store(
                IdempotencyRecord(
                    tenant_id=tenant_id,
                    actor=actor,
                    route=route,
                    key=idempotency_key,
                    request_hash=sha256_json(request_body or {}),
                    response_json={"revision_id": rev.id, "revision_no": rev.revision_no},
                    resource_id=rev.id,
                )
            )
        return rev

    def undo(
        self,
        tenant_id: str,
        actor: str,
        doc_id: str,
        if_match: Optional[str],
        restores_revision_id: str,
        reason: str = "",
    ) -> Revision:
        """INV-06: restoring an old snapshot creates a NEW revision — the
        old head is never overwritten."""
        rec = self._require_active_document(doc_id, tenant_id)
        expected = self._require_if_match(rec, if_match)
        target = self.store.get_revision(restores_revision_id)
        if target is None or target.document_id != doc_id:
            raise NotFoundError("revision not found")
        head = self.store.get_revision(expected)
        doc = Document.model_validate(target.content_json)
        target_manifest = (
            self.store.get_manifest(target.manifest_id)
            if target.manifest_id
            else None
        )
        c_hash, s_hash, sol_hash = revision_hashes(
            doc, target_manifest.digest if target_manifest else None
        )
        rev = Revision(
            document_id=doc_id,
            revision_no=head.revision_no + 1,
            parent_revision_id=head.id,
            mode=RevisionMode.UNDO,
            restores_revision_id=restores_revision_id,
            manifest_id=target.manifest_id,
            metadata_snapshot=doc.metadata.model_dump(),
            template_snapshot={
                "brand_id": doc.brand_id,
                "template_id": doc.template_id,
            },
            content_json=doc.model_dump(),
            content_hash=c_hash,
            style_hash=s_hash,
            solution_hash=sol_hash,
            created_by=actor,
            change_summary=[{"op": "undo", "restores": restores_revision_id, "reason": reason}],
        )
        self.store.insert_revision(rev, expected_head=expected)
        self._seed_checks(rev)
        self.store.mark_checks_stale(
            head.id, sorted(_CONTENT_CHECKS), "superseded by undo revision"
        )
        self.tenancy.audit(
            AuditEvent(
                tenant_id=tenant_id,
                user_id=actor,
                action="document.undo",
                object_type="document",
                object_id=doc_id,
                detail={"revision_id": rev.id, "restores": restores_revision_id},
            )
        )
        return rev

    # -- page order / manifest ---------------------------------------------------

    def confirm_page_order(
        self,
        tenant_id: str,
        actor: str,
        doc_id: str,
        if_match: Optional[str],
        page_ids_ordered: list[str],
        missing_page_expectation: Optional[str] = None,
    ) -> tuple[SourceManifest, Revision]:
        """Confirm or change the exam page order. Creates a new manifest
        (digest covers the order) and a new revision bound to it, so any
        rendered output traces to the confirmed page set."""
        rec = self._require_active_document(doc_id, tenant_id)
        expected = self._require_if_match(rec, if_match)
        head = self.store.get_revision(expected)
        assert head is not None
        doc = Document.model_validate(head.content_json)

        pages_by_id = {p.source_page_id: p for p in doc.pages if p.source_page_id}
        if sorted(page_ids_ordered) != sorted(pages_by_id):
            raise ValidationError(
                "page_ids_ordered must be a permutation of the document's "
                "source pages",
                {
                    "expected": sorted(pages_by_id),
                    "received": sorted(page_ids_ordered),
                },
            )
        manifest = self.store.create_manifest(
            SourceManifest(
                tenant_id=tenant_id,
                document_id=doc_id,
                page_ids_ordered=page_ids_ordered,
                missing_page_expectation=missing_page_expectation,
                confirmed_by=actor,
                confirmed_at=time.time(),
            )
        )
        # Reorder the document's pages to match the confirmed order.
        doc.pages = [pages_by_id[pid] for pid in page_ids_ordered]
        for i, p in enumerate(doc.pages):
            p.index = i
        rev = self.create_revision(
            doc,
            tenant_id,
            actor,
            mode=RevisionMode.EDIT,
            ops_summary=[
                {
                    "op": "confirm_page_order",
                    "manifest_id": manifest.id,
                    "pages": len(page_ids_ordered),
                }
            ],
            manifest_id=manifest.id,
        )
        self.tenancy.audit(
            AuditEvent(
                tenant_id=tenant_id,
                user_id=actor,
                action="document.confirm_page_order",
                object_type="document",
                object_id=doc_id,
                detail={
                    "manifest_id": manifest.id,
                    "digest": manifest.digest,
                    "revision_id": rev.id,
                },
            )
        )
        return manifest, rev

    # -- op application ---------------------------------------------------------

    def _apply_ops(self, doc: Document, ops: list[ChangeOp]) -> list[dict]:
        if not ops:
            raise ValidationError("empty change set")
        summary: list[dict] = []
        for op in ops:
            if op.op == "ResolveATU":
                atu = self._find_atu(doc, op.target_id)
                self._check_old_digest(atu.value, op.expected_old_digest)
                atu.value = op.value
                atu.status = VerificationStatus.HUMAN_VERIFIED
                summary.append({"op": "ResolveATU", "atu_id": op.target_id})
            elif op.op == "SetMetadata":
                if op.field not in type(doc.metadata).model_fields:
                    raise ValidationError(f"unknown metadata field {op.field}")
                old = getattr(doc.metadata, op.field)
                self._check_old_digest(old, op.expected_old_digest)
                setattr(doc.metadata, op.field, op.value)
                summary.append({"op": "SetMetadata", "field": op.field})
            elif op.op in ("SetAnswer", "SetPoints", "SetField"):
                q = self._find_question(doc, op.target_id)
                if op.op == "SetPoints":
                    self._check_old_digest(q.points, op.expected_old_digest)
                    q.points = int(op.value)
                elif op.op == "SetAnswer":
                    from document.models import Answer

                    self._check_old_digest(
                        q.answer.value if q.answer else None, op.expected_old_digest
                    )
                    q.answer = Answer(value=op.value)
                else:
                    if op.field in {"body", "choices", "source", "atus", "id"}:
                        raise ValidationError(f"field {op.field} is not directly settable")
                    if not hasattr(q, op.field or ""):
                        raise ValidationError(f"unknown question field {op.field}")
                    self._check_old_digest(getattr(q, op.field), op.expected_old_digest)
                    setattr(q, op.field, op.value)
                summary.append({"op": op.op, "question": op.target_id, "field": op.field})
            elif op.op == "SetStyle":
                if op.field not in {"brand_id", "template_id"}:
                    raise ValidationError(f"unknown style field {op.field}")
                self._check_old_digest(getattr(doc, op.field), op.expected_old_digest)
                setattr(doc, op.field, op.value)
                summary.append({"op": "SetStyle", "field": op.field})
            else:
                raise ValidationError(f"unsupported op {op.op}")
        return summary

    def _find_atu(self, doc: Document, atu_id: Optional[str]):
        for q in doc.questions:
            for atu in q.atus:
                if atu.id == atu_id:
                    return atu
        raise NotFoundError(f"atu {atu_id} not found")

    def _find_question(self, doc: Document, qid: Optional[str]):
        for q in doc.questions:
            if q.id == qid or str(q.number) == str(qid) or q.label == str(qid):
                return q
        raise NotFoundError(f"question {qid} not found")

    def _check_old_digest(self, current: Any, expected: Optional[str]) -> None:
        if expected is not None and sha256_json(current) != expected:
            raise ConflictError(
                "FIELD_CONFLICT",
                "field changed since your snapshot",
            )

    # -- guards -----------------------------------------------------------------

    def _require_active_document(self, doc_id: str, tenant_id: str):
        rec = self.store.get_document(doc_id)
        if rec is None or rec.tenant_id != tenant_id:
            raise NotFoundError("document not found")
        from .models import LifecycleState

        if rec.lifecycle_state != LifecycleState.ACTIVE:
            raise ConflictError(
                "LIFECYCLE_CONFLICT",
                f"document is {rec.lifecycle_state.value}",
            )
        return rec

    def _require_if_match(self, rec, if_match: Optional[str]) -> str:
        if not if_match:
            raise PreconditionError(
                "If-Match header with current revision id is required"
            )
        expected = if_match.strip().strip('"')
        if expected.startswith("rev:"):
            expected = expected[4:]
        if expected != rec.head_revision_id:
            raise ConflictError(
                "REVISION_CONFLICT",
                "document head does not match If-Match",
                {"current_revision_id": rec.head_revision_id},
            )
        return expected

    def _idempotent_replay(
        self,
        tenant_id: str,
        actor: str,
        route: str,
        key: Optional[str],
        body: Optional[dict],
    ) -> Optional[IdempotencyRecord]:
        if not key:
            return None
        existing = self.store.idempotency_lookup(tenant_id, actor, route, key)
        if existing is None:
            return None
        if existing.request_hash != sha256_json(body or {}):
            raise IdempotencyConflictError(
                "IDEMPOTENCY_CONFLICT",
                "same Idempotency-Key with a different payload",
            )
        return existing

    # -- checks ----------------------------------------------------------------

    def run_checks(self, revision_id: str) -> list[CheckRun]:
        """Execute the implemented validators for a revision; unimplemented
        required checks stay NOT_RUN (fail-closed)."""
        rev = self.store.get_revision(revision_id)
        if rev is None:
            raise NotFoundError("revision not found")
        rec = self.store.get_document(rev.document_id)
        doc = Document.model_validate(rev.content_json)
        now = time.time()
        results: list[CheckRun] = []

        for kind in self.store.get_checks(revision_id):
            if kind.check_kind not in IMPLEMENTED_CHECKERS:
                results.append(kind)
                continue
            state, summary = self._run_one(kind.check_kind, doc, rev)
            kind.state = state
            kind.result_summary = summary
            kind.applicable = True
            kind.stale_reason = None
            kind.started_at = kind.started_at or now
            kind.finished_at = now
            self.store.upsert_check(kind)
            if state == CheckState.FAILED:
                self._flag_check_issue(rev, kind.check_kind, summary)
            results.append(kind)

        # aggregate check: other required checks all PASSED + no blocking issues
        agg = next(
            (c for c in results if c.check_kind == "BLOCKING_ISSUES_CLOSED"), None
        )
        if agg is not None:
            others_ok = all(
                c.state == CheckState.PASSED
                for c in results
                if c.check_kind != "BLOCKING_ISSUES_CLOSED" and c.applicable
            )
            open_blocking = self.store.list_issues(
                revision_id, state=IssueState.OPEN, blocking_only=True
            )
            if others_ok and not open_blocking:
                agg.state = CheckState.PASSED
                agg.result_summary = "all required checks passed, no blocking issues"
            else:
                agg.state = CheckState.FAILED
                agg.result_summary = (
                    f"{len(open_blocking)} blocking issues open or checks not passed"
                )
            self.store.upsert_check(agg)
        return self.store.get_checks(revision_id)

    def _run_one(self, kind: str, doc: Document, rev: Revision) -> tuple[CheckState, str]:
        if kind == "SCHEMA_REFERENTIAL_INTEGRITY":
            try:
                Document.model_validate(rev.content_json)
            except Exception as exc:
                return CheckState.FAILED, f"content does not validate: {exc}"
            ids = [q.id for q in doc.questions]
            if len(ids) != len(set(ids)):
                return CheckState.FAILED, "duplicate question ids"
            atu_ids = [a.id for a in doc.all_atus()]
            if len(atu_ids) != len(set(atu_ids)):
                return CheckState.FAILED, "duplicate atu ids"
            return CheckState.PASSED, f"{len(doc.questions)} questions, schema valid"
        if kind == "QUESTION_CHOICE_SCORE_COMPLETENESS":
            if not doc.questions:
                return CheckState.FAILED, "no questions extracted"
            numbers = [
                int(q.label)
                for q in doc.questions
                if (q.label or "").isdigit()
            ]
            if numbers:
                gaps = sorted(set(range(min(numbers), max(numbers) + 1)) - set(numbers))
                if gaps:
                    return CheckState.FAILED, f"missing question numbers: {gaps}"
            empty = [
                q.number
                for q in doc.questions
                if not q.body and not q.equations and not q.figures and not q.choices
            ]
            if empty:
                return CheckState.FAILED, f"questions without content: {empty}"
            return CheckState.PASSED, f"{len(doc.questions)} questions complete"
        if kind == "SOURCE_REGION_COVERAGE":
            # Contract: fields with zero ATU/FieldEvidence have no provenance
            # and must fail — extraction is not self-verifying.
            if not doc.questions:
                return CheckState.FAILED, "no questions"
            no_atu = [q.number for q in doc.questions if not q.atus]
            if no_atu:
                return (
                    CheckState.FAILED,
                    f"questions without field evidence: {no_atu}",
                )
            return CheckState.PASSED, "all questions have field evidence"
        return CheckState.NOT_RUN, "no validator implemented"

    def _flag_check_issue(self, rev: Revision, kind: str, summary: str) -> None:
        existing = [
            i
            for i in self.store.list_issues(rev.id, state=IssueState.OPEN)
            if i.kind == kind
        ]
        if existing:
            return
        self.store.create_issue(
            Issue(
                revision_id=rev.id,
                kind=kind,
                severity="critical",
                blocking=True,
                reason=summary,
                actor="system",
            )
        )

    # -- eligibility / artifacts --------------------------------------------------

    def compute_eligibility(
        self, doc_id: str, tenant_id: str, revision_id: Optional[str] = None
    ) -> dict:
        rec = self._require_active_document(doc_id, tenant_id)
        rev = (
            self.store.get_revision(revision_id)
            if revision_id
            else self.store.get_head_revision(doc_id)
        )
        if rev is None or rev.document_id != doc_id:
            raise NotFoundError("revision not found")

        policy = restore_policy()
        checks = {c.check_kind: c for c in self.store.get_checks(rev.id)}
        required = (
            policy.required_content_checks
            if rev.mode != RevisionMode.EDIT
            else policy.required_content_checks + ["APPROVED_EDIT_CONFORMANCE"]
        )
        content = []
        content_ready = True
        for kind in required:
            c = checks.get(kind)
            state = c.state.value if c else CheckState.NOT_RUN.value
            applicable = c.applicable if c else True
            ok = applicable and state == CheckState.PASSED.value
            if not ok:
                content_ready = False
            content.append(
                {
                    "check_kind": kind,
                    "state": state,
                    "applicable": applicable,
                    "stale_reason": c.stale_reason if c else None,
                    "method": c.method if c else None,
                    "result_summary": c.result_summary if c else "",
                }
            )
        blocking = self.store.list_issues(rev.id, state=IssueState.OPEN, blocking_only=True)

        formats: dict[str, dict] = {}
        for fmt, art_checks in policy.required_artifact_checks_by_format.items():
            artifacts = [
                a
                for a in self.store.list_artifacts(doc_id, rev.id)
                if a.format == fmt
            ]
            fmt_checks = []
            fmt_ok = content_ready and not blocking
            for kind in art_checks:
                passed = False
                state = "NOT_RUN"
                for a in artifacts:
                    proof = self.store.get_proof_for_artifact(a.id)
                    if (
                        proof
                        and proof.artifact_sha256 == a.artifact_sha256
                        and proof.checks.get(kind) == "PASSED"
                    ):
                        passed = True
                        state = "PASSED"
                        break
                if not passed:
                    fmt_ok = False
                fmt_checks.append({"check_kind": kind, "state": state})
            formats[fmt] = {
                "checks": fmt_checks,
                "final_eligible": fmt_ok,
                "artifacts": [
                    {"id": a.id, "state": a.state.value, "sha256": a.artifact_sha256}
                    for a in artifacts
                ],
            }

        return {
            "document_id": doc_id,
            "revision_id": rev.id,
            "revision_no": rev.revision_no,
            "mode": rev.mode.value,
            "policy_digest": policy.digest,
            "content_ready": content_ready and not blocking,
            "content_checks": content,
            "blocking_issues": [i.model_dump() for i in blocking],
            "formats": formats,
        }

    def register_draft_artifact(
        self,
        tenant_id: str,
        doc_id: str,
        revision_id: str,
        fmt: str,
        blob_key: str,
        artifact_sha256: str,
        byte_size: int,
        output_mode: str = "STUDENT_WITH_ENDNOTES",
    ) -> Artifact:
        rec = self._require_active_document(doc_id, tenant_id)
        rev = self.store.get_revision(revision_id)
        if rev is None or rev.document_id != doc_id:
            raise NotFoundError("revision not found")
        return self.store.create_artifact(
            Artifact(
                tenant_id=tenant_id,
                document_id=doc_id,
                revision_id=revision_id,
                format=fmt,
                output_mode=output_mode,
                content_hash=rev.content_hash,
                style_hash=rev.style_hash,
                solution_hash=rev.solution_hash,
                artifact_sha256=artifact_sha256,
                blob_key=blob_key,
                byte_size=byte_size,
                state=ArtifactState.DRAFT,
            )
        )

    def record_proof(
        self,
        artifact_id: str,
        checks: dict[str, str],
        worker_identity: str = "",
    ) -> ArtifactProof:
        """Bind a proof to the artifact's exact bytes. If every required
        artifact check PASSED and the content gate is closed, the artifact
        becomes FINAL_ELIGIBLE — otherwise it stays DRAFT."""
        art = self.store.get_artifact(artifact_id)
        if art is None:
            raise NotFoundError("artifact not found")
        rev = self.store.get_revision(art.revision_id)
        policy = restore_policy(art.output_mode)
        proof = self.store.create_proof(
            ArtifactProof(
                artifact_id=art.id,
                artifact_sha256=art.artifact_sha256,
                revision_id=art.revision_id,
                policy_digest=policy.digest,
                checks=checks,
                worker_identity=worker_identity,
            )
        )
        required = policy.required_artifact_checks_by_format.get(art.format, [])
        all_passed = all(checks.get(k) == "PASSED" for k in required)
        elig = self.compute_eligibility(art.document_id, art.tenant_id, art.revision_id)
        content_ready = elig["content_ready"]
        if all_passed and content_ready:
            self.store.set_artifact_state(art.id, ArtifactState.FINAL_ELIGIBLE)
        return proof

    def export_final(
        self,
        tenant_id: str,
        doc_id: str,
        revision_id: str,
        artifact_ids: list[str],
    ) -> list[Artifact]:
        """Promote verified artifacts to FINAL. Every artifact must be
        FINAL_ELIGIBLE, belong to the requested revision, and carry a proof
        bound to its exact bytes — stale or unproven artifacts are rejected."""
        rec = self._require_active_document(doc_id, tenant_id)
        if rec.head_revision_id != revision_id:
            raise ConflictError(
                "REVISION_CONFLICT",
                "requested revision is not the current head",
                {"current_revision_id": rec.head_revision_id},
            )
        out: list[Artifact] = []
        for aid in artifact_ids:
            art = self.store.get_artifact(aid)
            if art is None or art.document_id != doc_id or art.tenant_id != tenant_id:
                raise NotFoundError(f"artifact {aid} not found")
            if art.revision_id != revision_id:
                raise ConflictError(
                    "REVISION_CONFLICT",
                    f"artifact {aid} belongs to another revision",
                )
            proof = self.store.get_proof_for_artifact(art.id)
            if (
                proof is None
                or proof.artifact_sha256 != art.artifact_sha256
                or art.state != ArtifactState.FINAL_ELIGIBLE
            ):
                raise ValidationError(
                    f"artifact {aid} is not final-eligible "
                    f"(state={art.state.value}, proof={'bound' if proof else 'missing'})"
                )
            out.append(art)
        for art in out:
            self.store.set_artifact_state(art.id, ArtifactState.FINAL)
            art.state = ArtifactState.FINAL
        self.tenancy.audit(
            AuditEvent(
                tenant_id=tenant_id,
                action="document.export_final",
                object_type="document",
                object_id=doc_id,
                detail={"revision_id": revision_id, "artifacts": artifact_ids},
            )
        )
        return out
