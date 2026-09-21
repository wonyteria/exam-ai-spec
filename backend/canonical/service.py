from __future__ import annotations

import hashlib
import json
import re
import time
from difflib import SequenceMatcher
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
    PageRole,
    Revision,
    RevisionMode,
    SourceManifest,
    new_id,
    canonical_json,
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
    "MATH_FIGURE_SEMANTIC_CONSISTENCY",
    "BLOCKING_ISSUES_CLOSED",
    "APPROVED_EDIT_CONFORMANCE",
    "ORIGINAL_SOURCE_FIDELITY",
    "REQUIRED_CONTENT_COVERAGE",
    "CURRICULUM_COMPLIANCE",
}

# Checks that need a live solver provider (WP04). Without providers they
# stay NOT_RUN — never marked PASSED by default (fail-closed).
PROVIDER_CHECKERS = {
    "SOLVE_TWO_INDEPENDENT_AGREEMENT",
    "ANSWER_SOLUTION_LOGIC",
}

_CIRCLED_DIGITS = {
    "①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5",
    "⑥": "6", "⑦": "7", "⑧": "8", "⑨": "9", "⑩": "10",
}


def _norm_answer(value: Any) -> str:
    s = str(value).strip().rstrip(".")
    s = _CIRCLED_DIGITS.get(s, s)
    # Unit decorations don't change the value: '76°', '76도', '5cm' all
    # record the same answer as '76' / '5'.
    s = re.sub(
        r"(?<=[\d.])(㎠|㎝|㎢|cm²|cm³|cm|mm|km|m|°|도|개|자리)$", "", s.strip()
    )
    return s.strip()


def _answers_match(recorded: Any, solver: Any) -> bool:
    """Agreement between a recorded answer and a solver answer. Exact
    after normalization for choices/numbers; for descriptive answers the
    solver may return a full sentence, so the normalized recorded key
    only needs to be contained — but numeric keys never use containment
    ('7' must not match inside '76')."""
    a, b = _norm_answer(recorded), _norm_answer(solver)
    if not a or not b:
        return False
    if a == b:
        return True
    key = re.sub(r"[^\w가-힣]", "", a)
    hay = re.sub(r"[^\w가-힣]", "", b)
    if not key or key.isdigit():
        return False
    return len(key) >= 2 and key in hay


def _audit_field_match(field: str, audit_text: str) -> bool:
    """A materialized field counts as present when it is contained in the
    audit text, or when >=80% of its characters match somewhere in it —
    OCR noise tolerance without accepting unrelated text."""
    if field in audit_text:
        return True
    matched = sum(
        b.size
        for b in SequenceMatcher(None, field, audit_text).get_matching_blocks()
    )
    return matched / max(1, len(field)) >= 0.8


def _audit_candidate_text(value: Any) -> str:
    """Flatten an auditor candidate into comparable text. Raw OCR
    providers return line strings; structured extractors (e.g. Gemini)
    return dicts — their leaf values are joined, with number/points
    emitted in the printed forms ('7.', '3점') the audit looks for."""
    if isinstance(value, dict):
        parts: list[str] = []
        for k, v in value.items():
            if k == "number" and v not in (None, ""):
                parts.append(f"{v}.")
            elif k == "points" and v not in (None, ""):
                parts.append(f"{v}점")
            else:
                parts.append(_audit_candidate_text(v))
        return " ".join(p for p in parts if p)
    if isinstance(value, (list, tuple)):
        return " ".join(_audit_candidate_text(v) for v in value)
    return str(value)


_CONTENT_Q_EXCLUDE = frozenset({"answer", "solution", "verification"})


def _content_payload(content: dict, manifest_digest: Optional[str] = None) -> dict:
    """Meaning-bearing content: questions minus answers/solutions, plus
    metadata scope fields and the source page manifest (02: content_hash
    covers the source manifest, so a page reorder changes content_hash).

    Operates on the stored content dict — the exact representation that
    was hashed at write time. Re-validating into models before hashing
    would inject serializer defaults (e.g. generated figure ids) and
    produce a digest over a different representation than the one that
    was recorded."""
    meta = content.get("metadata") or {}
    return {
        "metadata": {
            "subject": meta.get("subject"),
            "grade": meta.get("grade"),
            "school": meta.get("school"),
            "year": meta.get("year"),
            "semester": meta.get("semester"),
            "exam_type": meta.get("exam_type"),
        },
        "manifest_digest": manifest_digest,
        "pages": content.get("pages") or [],
        "questions": [
            {k: v for k, v in q.items() if k not in _CONTENT_Q_EXCLUDE}
            for q in content.get("questions") or []
        ],
    }


def _solution_payload(content: dict) -> dict:
    return {
        "answers": [
            {
                "q": q.get("id"),
                "answer": q.get("answer"),
                "solution": q.get("solution"),
                "curriculum": q.get("curriculum"),
            }
            for q in content.get("questions") or []
        ]
    }


def _style_payload(content: dict) -> dict:
    meta = content.get("metadata") or {}
    return {
        "brand_id": content.get("brand_id"),
        "template_id": content.get("template_id"),
        "display_metadata": {
            "title": meta.get("title"),
            "school": meta.get("school"),
            "year": meta.get("year"),
            "semester": meta.get("semester"),
            "exam_type": meta.get("exam_type"),
        },
    }


def revision_hashes(
    content: dict, manifest_digest: Optional[str] = None
) -> tuple[str, str, str]:
    return (
        sha256_json(_content_payload(content, manifest_digest)),
        sha256_json(_style_payload(content)),
        sha256_json(_solution_payload(content)),
    )


def _stored_content(doc: Document) -> dict:
    """The canonical stored form of a document: validate the dump so raw
    dicts assigned via SetField become typed sub-models with defaults
    populated, then round-trip through canonical_json — the exact bytes
    the store persists (its NaN literal keeps non-finite values visible
    to the math/figure validator, unlike a mode='json' dump which would
    silently coerce them to null)."""
    validated = Document.model_validate(doc.model_dump())
    return json.loads(canonical_json(validated.model_dump()))


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
        self._normalize_math(doc)
        content = _stored_content(doc)
        c_hash, s_hash, sol_hash = revision_hashes(
            content, manifest.digest if manifest else None
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
            content_json=content,
            content_hash=c_hash,
            style_hash=s_hash,
            solution_hash=sol_hash,
            created_by=actor,
            change_summary=ops_summary or [],
        )
        self.store.insert_revision(rev, expected_head=rec.head_revision_id)
        self._seed_checks(rev)
        return rev

    @staticmethod
    def _normalize_math(doc: Document) -> None:
        """Derive `hwp_formula` (HWP equation script) from `latex` for every
        equation object that has LaTeX but no formula yet. Parse failures
        are left unset — MATH_FIGURE_SEMANTIC_CONSISTENCY flags them as
        issues rather than silently emitting broken script."""
        from document.math_ast import latex_to_hwp
        from document.models import Equation

        for q in doc.questions:
            for i, eq in enumerate(q.equations):
                # SetField may have assigned raw dicts — coerce to real
                # Equation objects so the snapshot holds typed objects.
                if isinstance(eq, dict):
                    eq = Equation.model_validate(eq)
                    q.equations[i] = eq
                if eq.latex and not eq.hwp_formula:
                    try:
                        eq.hwp_formula = latex_to_hwp(eq.latex)["script"]
                    except Exception:
                        pass  # checker flags the invalid equation

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
        self._normalize_math(doc)

        head_manifest = (
            self.store.get_manifest(head.manifest_id) if head.manifest_id else None
        )
        pre = _stored_content(doc)
        c_hash, s_hash, sol_hash = revision_hashes(
            pre, head_manifest.digest if head_manifest else None
        )
        if (c_hash, s_hash, sol_hash) == (
            head.content_hash,
            head.style_hash,
            head.solution_hash,
        ):
            # WP06: a no-op change set must not mint an empty revision —
            # the history only records real state transitions.
            raise ValidationError("no-op change set: nothing changed")

        # An intentional edit discards prior final status: VERIFIED_FINAL
        # and past answers must be re-earned by the post-edit checks.
        # The flip does not enter any hash payload, but it must land in
        # the stored snapshot — so content is dumped after it.
        if doc.verification.status == "VERIFIED_FINAL":
            doc.verification.status = "NEEDS_REVIEW"
        content = _stored_content(doc)
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
            content_json=content,
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
        content = _stored_content(doc)
        c_hash, s_hash, sol_hash = revision_hashes(
            content, target_manifest.digest if target_manifest else None
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
            content_json=content,
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

    def redo(
        self,
        tenant_id: str,
        actor: str,
        doc_id: str,
        if_match: Optional[str],
    ) -> Revision:
        """Redo = restore the pre-undo head. Only valid when the current
        head is an undo-produced revision (it carries restores_revision_id
        and its parent is the state that was undone). Otherwise there is
        nothing to redo — fail closed rather than invent a target."""
        rec = self._require_active_document(doc_id, tenant_id)
        expected = self._require_if_match(rec, if_match)
        head = self.store.get_revision(expected)
        if head is None or not head.restores_revision_id:
            raise ConflictError(
                "NOTHING_TO_REDO",
                "current head is not an undo revision",
            )
        if not head.parent_revision_id:
            raise ConflictError("NOTHING_TO_REDO", "undo revision has no parent")
        return self.undo(
            tenant_id,
            actor,
            doc_id,
            if_match,
            restores_revision_id=head.parent_revision_id,
            reason="redo",
        )

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

    def set_page_role(
        self,
        tenant_id: str,
        actor: str,
        doc_id: str,
        if_match: Optional[str],
        source_page_id: str,
        role: str,
    ) -> Revision:
        """User-confirmed page role (AT-061). An answer/score page is never
        silently dropped or treated as a question page — the confirmed role
        is recorded on the source page and bound to a new revision so the
        manifest's semantic page set stays auditable."""
        valid = {r.value for r in PageRole}
        if role not in valid:
            raise ValidationError(
                "unknown page_role",
                {"received": role, "allowed": sorted(valid)},
            )
        rec = self._require_active_document(doc_id, tenant_id)
        expected = self._require_if_match(rec, if_match)
        sp = self.store.get_source_page(source_page_id)
        if sp is None or sp.document_id != doc_id or sp.tenant_id != tenant_id:
            raise NotFoundError("source page not found")
        updated = self.store.set_source_page_role(source_page_id, role, "USER")
        head = self.store.get_revision(expected)
        assert head is not None
        doc = Document.model_validate(head.content_json)
        for p in doc.pages:
            if p.source_page_id == source_page_id:
                p.page_role = role
                p.role_source = "USER"
        rev = self.create_revision(
            doc,
            tenant_id,
            actor,
            mode=RevisionMode.EDIT,
            ops_summary=[
                {
                    "op": "set_page_role",
                    "source_page_id": source_page_id,
                    "role": role,
                }
            ],
            manifest_id=head.manifest_id,
        )
        self.tenancy.audit(
            AuditEvent(
                tenant_id=tenant_id,
                user_id=actor,
                action="document.set_page_role",
                object_type="source_page",
                object_id=source_page_id,
                detail={
                    "document_id": doc_id,
                    "role": role,
                    "revision_id": rev.id,
                },
            )
        )
        return rev

    # -- op application ---------------------------------------------------------

    def _apply_ops(self, doc: Document, ops: list[ChangeOp]) -> list[dict]:
        if not ops:
            raise ValidationError("empty change set")
        summary: list[dict] = []
        for op in ops:
            if op.op == "ResolveATU":
                q, atu = self._find_atu(doc, op.target_id)
                self._check_old_digest(atu.value, op.expected_old_digest)
                atu.value = op.value
                atu.status = VerificationStatus.HUMAN_VERIFIED
                self._sync_resolved_atu(doc, q, atu)
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
                    if op.field == "number":
                        # Confirming the printed number of a masked/
                        # ambiguous anchor ("?mark1") is a LABEL fix:
                        # `number` is the positional sequence assigned at
                        # segmentation (dense 1..N, including "2-1"
                        # subquestions), so it must not be overwritten —
                        # every printed number would collide with it.
                        try:
                            new_num = int(str(op.value).strip())
                        except (TypeError, ValueError):
                            raise ValidationError(
                                "question number must be an integer"
                            )
                        if new_num <= 0:
                            raise ValidationError("question number must be > 0")
                        new_label = str(new_num)
                        if any(
                            x.id != q.id and x.label == new_label
                            for x in doc.questions
                        ):
                            raise ConflictError(
                                "NUMBER_EXISTS",
                                f"question {new_label} already exists",
                            )
                        q.label = new_label
                        summary.append(
                            {"op": op.op, "question": op.target_id,
                             "field": "number", "value": new_num}
                        )
                        if op.propagate:
                            summary.extend(self._propagate(doc, q, op))
                        continue
                    value = op.value
                    if op.field == "type":
                        from document.models import QuestionType

                        value = QuestionType(str(value))
                    setattr(q, op.field, value)
                summary.append({"op": op.op, "question": op.target_id, "field": op.field})
                if op.propagate:
                    summary.extend(self._propagate(doc, q, op))
            elif op.op == "SetBody":
                from document.models import TextSpan

                q = self._find_question(doc, op.target_id)
                self._check_old_digest(q.body, op.expected_old_digest)
                q.body = [TextSpan(text=str(op.value))]
                summary.append({"op": "SetBody", "question": op.target_id})
                if op.propagate:
                    summary.extend(self._propagate(doc, q, op))
            elif op.op == "SetChoice":
                from document.models import Choice, TextSpan

                q = self._find_question(doc, op.target_id)
                label = str(op.field or "")
                if not label:
                    raise ValidationError("SetChoice requires field=choice label")
                choice = next(
                    (c for c in q.choices if c.label == label), None
                )
                if choice is None:
                    choice = Choice(label=label)
                    q.choices.append(choice)
                self._check_old_digest(choice.body, op.expected_old_digest)
                choice.body = [TextSpan(text=str(op.value))]
                summary.append(
                    {"op": "SetChoice", "question": op.target_id, "choice": label}
                )
            elif op.op == "SetEquation":
                q = self._find_question(doc, op.target_id)
                try:
                    idx = int(op.field)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    raise ValidationError("SetEquation requires field=index")
                if not 0 <= idx < len(q.equations):
                    raise ValidationError(f"equation index {idx} out of range")
                self._check_old_digest(
                    q.equations[idx].latex, op.expected_old_digest
                )
                q.equations[idx].latex = str(op.value)
                summary.append(
                    {"op": "SetEquation", "question": op.target_id, "index": idx}
                )
            elif op.op == "SetSolution":
                from document.models import Solution, TextSpan

                q = self._find_question(doc, op.target_id)
                v = op.value
                if isinstance(v, dict):
                    steps = [
                        str(s) for s in (v.get("steps") or []) if str(s).strip()
                    ]
                    concepts = [str(c) for c in (v.get("concepts") or [])]
                else:
                    steps = [s for s in str(v).splitlines() if s.strip()]
                    concepts = []
                self._check_old_digest(q.solution, op.expected_old_digest)
                q.solution = Solution(
                    steps=[TextSpan(text=s) for s in steps],
                    concepts=concepts,
                )
                summary.append({"op": "SetSolution", "question": op.target_id})
            elif op.op == "AddQuestion":
                # Missing-question recovery path (WP06): a new question is
                # appended and re-sorted — never merged into an existing
                # number/label (that would silently corrupt the target).
                v = op.value if isinstance(op.value, dict) else {"number": op.value}
                num = v.get("number")
                label = str(v.get("label") or num or "")
                if num is None or not label:
                    raise ValidationError("AddQuestion requires value.number")
                if any(
                    str(q.number) == str(num) or (label and q.label == label)
                    for q in doc.questions
                ):
                    raise ConflictError(
                        "QUESTION_EXISTS",
                        f"question {label!r} already exists — refusing to merge",
                    )
                from document.models import Question

                q = Question(number=int(num), label=label)
                doc.questions.append(q)
                doc.questions.sort(key=lambda x: x.number)
                summary.append({"op": "AddQuestion", "question": q.id, "label": label})
            elif op.op == "RemoveQuestion":
                q = self._find_question(doc, op.target_id)
                doc.questions = [x for x in doc.questions if x.id != q.id]
                summary.append({"op": "RemoveQuestion", "question": op.target_id})
            elif op.op == "SwapQuestions":
                a = self._find_question(doc, op.target_id)
                b = self._find_question(doc, op.value)
                ia = next(i for i, x in enumerate(doc.questions) if x.id == a.id)
                ib = next(i for i, x in enumerate(doc.questions) if x.id == b.id)
                doc.questions[ia], doc.questions[ib] = (
                    doc.questions[ib],
                    doc.questions[ia],
                )
                a.number, b.number = b.number, a.number
                summary.append(
                    {"op": "SwapQuestions", "a": a.id, "b": b.id}
                )
            elif op.op == "MoveQuestion":
                q = self._find_question(doc, op.target_id)
                rest = [x for x in doc.questions if x.id != q.id]
                try:
                    pos = int(op.value)
                except (TypeError, ValueError):
                    raise ValidationError(
                        "MoveQuestion requires value=target index"
                    )
                pos = max(0, min(pos, len(rest)))
                rest.insert(pos, q)
                doc.questions = rest
                summary.append(
                    {"op": "MoveQuestion", "question": q.id, "to": pos}
                )
            elif op.op == "ReorderQuestions":
                order = op.value if isinstance(op.value, list) else []
                if not order:
                    raise ValidationError(
                        "ReorderQuestions requires value=ordered id list"
                    )
                wanted = [self._find_question(doc, t) for t in order]
                if len({q.id for q in wanted}) != len(wanted):
                    raise ValidationError("duplicate id in reorder list")
                remaining = [
                    q for q in doc.questions
                    if q.id not in {w.id for w in wanted}
                ]
                doc.questions = wanted + remaining
                summary.append(
                    {
                        "op": "ReorderQuestions",
                        "order": [q.id for q in wanted],
                    }
                )
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
                    return q, atu
        raise NotFoundError(f"atu {atu_id} not found")

    def _sync_resolved_atu(self, doc: Document, q, atu) -> None:
        """Propagate a human-resolved ATU into the derived field it backs.

        `_materialize` (consensus) runs once at pipeline time and only
        consumes already-verified ATUs — without this, resolving a
        CONFLICT/UNVERIFIED body/choice ATU in review would never reach
        `q.body`, so renderers and completeness checks would see an empty
        question forever. Merge semantics: a span/choice/equation/figure
        that already carries this ATU id is updated in place; otherwise
        the resolved value is appended, preserving manual SetBody/SetChoice
        edits that do not reference the ATU.
        """
        from document.models import Choice, Equation, QuestionType, TextSpan

        field = atu.field
        if field is None or atu.value is None:
            return
        if field == "number":
            new_label = str(atu.value)
            if any(x.id != q.id and x.label == new_label for x in doc.questions):
                raise ConflictError(
                    "NUMBER_EXISTS", f"question {new_label} already exists"
                )
            q.label = new_label
        elif field == "body":
            span = next((s for s in q.body if atu.id in s.atu_ids), None)
            if span is not None:
                span.text = str(atu.value)
            else:
                q.body.append(TextSpan(text=str(atu.value), atu_ids=[atu.id]))
        elif field == "points":
            try:
                q.points = int(atu.value)
            except (TypeError, ValueError):
                pass
        elif field == "type":
            try:
                q.type = QuestionType(str(atu.value))
            except ValueError:
                pass
        elif field == "figure":
            from core.examdna.source_truth.consensus import _materialize_figure

            fig = _materialize_figure(atu, q)
            fig.atu_ids = [atu.id]
            for i, existing in enumerate(q.figures):
                if atu.id in existing.atu_ids:
                    q.figures[i] = fig
                    break
            else:
                q.figures.append(fig)
        elif field.startswith("choice:"):
            label = field.split(":", 1)[1]
            choice = next((c for c in q.choices if c.label == label), None)
            if choice is None:
                q.choices.append(
                    Choice(
                        label=label,
                        body=[TextSpan(text=str(atu.value), atu_ids=[atu.id])],
                    )
                )
                q.choices.sort(key=lambda c: c.label)
            else:
                span = next(
                    (s for s in choice.body if atu.id in s.atu_ids), None
                )
                if span is not None:
                    span.text = str(atu.value)
                else:
                    choice.body.append(
                        TextSpan(text=str(atu.value), atu_ids=[atu.id])
                    )
        elif field.startswith("equation:"):
            eq = next((e for e in q.equations if atu.id in e.atu_ids), None)
            if eq is not None:
                eq.latex = str(atu.value)
            else:
                q.equations.append(
                    Equation(
                        latex=str(atu.value),
                        source=atu.source,
                        atu_ids=[atu.id],
                    )
                )

    def _find_question(self, doc: Document, qid: Optional[str]):
        """Resolve an op target. Exact id wins; a number/label that maps to
        more than one question is a conflict — never a silent edit of the
        wrong question (WP06: label collision must not modify others)."""
        if qid is None:
            raise NotFoundError("op target_id is required")
        target = str(qid)
        by_id = [q for q in doc.questions if q.id == target]
        if by_id:
            return by_id[0]
        matches = {
            q.id: q
            for q in doc.questions
            if str(q.number) == target or q.label == target
        }
        if len(matches) > 1:
            raise ConflictError(
                "AMBIGUOUS_TARGET",
                f"target {target!r} matches multiple questions "
                f"({sorted(matches)}) — refusing to edit",
            )
        if matches:
            return next(iter(matches.values()))
        raise NotFoundError(f"question {qid} not found")

    def _propagate(self, doc: Document, parent, op: ChangeOp) -> list[dict]:
        """Apply the same field/value to direct children of a shared-stem
        parent (parent_id == parent.id). Opt-in via op.propagate — the
        summary records every propagated target for audit."""
        from document.models import TextSpan

        out: list[dict] = []
        for child in doc.questions:
            if child.parent_id != parent.id:
                continue
            if op.op == "SetBody":
                child.body = [TextSpan(text=str(op.value))]
            elif op.op == "SetField" and op.field == "figure":
                if child.figures:
                    child.figures[0].topology["description"] = str(op.value)
            else:
                continue  # only shared-stem fields propagate
            out.append({"op": "propagate", "question": child.id, "field": op.field})
        return out

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

    def run_checks(
        self,
        revision_id: str,
        providers: Optional[Any] = None,
        objects: Optional[Any] = None,
    ) -> list[CheckRun]:
        """Execute the implemented validators for a revision; unimplemented
        required checks stay NOT_RUN (fail-closed). Solver-backed checks
        run only when a solver provider is supplied — two independent runs
        (run=0 vs run=1 prompts differ, so a cache hit can never pass as a
        second opinion)."""
        rev = self.store.get_revision(revision_id)
        if rev is None:
            raise NotFoundError("revision not found")
        rec = self.store.get_document(rev.document_id)
        doc = Document.model_validate(rev.content_json)
        now = time.time()
        results: list[CheckRun] = []

        solvers = [
            s
            for s in getattr(providers, "solver", []) or []
            if hasattr(s, "solve_batch")
        ]
        solver_results: Optional[tuple[dict, dict]] = None
        solver_error: Optional[str] = None
        if solvers and doc.questions:
            try:
                solver_results = self._solver_passes(doc, solvers[0])
            except Exception as exc:  # noqa: BLE001
                # Provider outage/quota is unavailable evidence, not a
                # crash — the solver checks record NOT_RUN with the
                # reason so the gate stays fail-closed without 500s.
                solver_error = f"{type(exc).__name__}: {exc}"

        for kind in self.store.get_checks(revision_id):
            if kind.check_kind not in IMPLEMENTED_CHECKERS:
                if kind.check_kind in PROVIDER_CHECKERS:
                    if solver_results is not None:
                        state, summary = self._solver_check(
                            kind.check_kind, doc, solver_results
                        )
                    elif solver_error is not None:
                        state, summary = (
                            CheckState.NOT_RUN,
                            f"solver provider error: {solver_error}",
                        )
                    else:
                        results.append(kind)
                        continue
                else:
                    results.append(kind)
                    continue
            else:
                state, summary = self._run_one(
                    kind.check_kind, doc, rev, providers, objects
                )
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

    def _run_one(
        self,
        kind: str,
        doc: Document,
        rev: Revision,
        providers: Optional[Any] = None,
        objects: Optional[Any] = None,
    ) -> tuple[CheckState, str]:
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
        if kind == "MATH_FIGURE_SEMANTIC_CONSISTENCY":
            return self._check_math_figure(doc)
        if kind == "APPROVED_EDIT_CONFORMANCE":
            # EDIT lineage audit: walk head -> restore baseline. Every
            # mutation revision must carry its approved change set, and
            # every stored snapshot must recompute to its recorded
            # content/style/solution hashes — an unrecorded mutation or
            # a tampered snapshot fails.
            chain: list[Revision] = []
            cur: Optional[Revision] = rev
            baseline_id = rev.restore_baseline_revision_id
            seen: set[str] = set()
            while cur is not None and cur.id not in seen:
                seen.add(cur.id)
                chain.append(cur)
                if (baseline_id and cur.id == baseline_id) or (
                    cur.parent_revision_id is None
                ):
                    break
                cur = self.store.get_revision(cur.parent_revision_id)
            problems: list[str] = []
            for r in chain:
                if r.mode != RevisionMode.EDIT or r.id == baseline_id:
                    # The baseline/pipeline snapshot is audited by the
                    # source-manifest binding, not the edit gate — old
                    # baselines were minted under older serializers and
                    # cannot be re-hashed under the current schema.
                    continue
                try:
                    Document.model_validate(r.content_json)
                except Exception as exc:
                    problems.append(f"rev{r.revision_no} invalid snapshot: {exc}")
                    continue
                rmanifest = (
                    self.store.get_manifest(r.manifest_id)
                    if r.manifest_id
                    else None
                )
                # Hash the stored snapshot as recorded — re-validating it
                # into models first would inject serializer defaults and
                # hash a different representation than the one committed.
                ch, sh, soh = revision_hashes(
                    r.content_json, rmanifest.digest if rmanifest else None
                )
                if (ch, sh, soh) != (
                    r.content_hash,
                    r.style_hash,
                    r.solution_hash,
                ):
                    problems.append(f"rev{r.revision_no} hash mismatch")
                if not r.change_summary:
                    problems.append(
                        f"rev{r.revision_no} has no recorded change set"
                    )
            if problems:
                return CheckState.FAILED, "; ".join(problems[:6])
            return (
                CheckState.PASSED,
                f"{len(chain)} revisions audited, hashes consistent",
            )
        if kind == "ORIGINAL_SOURCE_FIDELITY":
            return self._source_fidelity(doc, providers, objects)
        if kind == "REQUIRED_CONTENT_COVERAGE":
            from document.models import QuestionType

            # Every scored leaf must carry a verified answer AND solution
            # plus evidence for equations/figures/answer space — output
            # modes that hide answers do not exempt content coverage.
            scored = [q for q in doc.questions if q.points]
            if not scored:
                return CheckState.FAILED, "no scored questions"
            missing: list[str] = []
            for q in scored:
                label = q.label or str(q.number)
                if q.answer is None or q.answer.value is None:
                    missing.append(f"{label}:answer")
                if not q.solution or not q.solution.steps:
                    missing.append(f"{label}:solution")
                if (
                    q.type == QuestionType.DESCRIPTIVE
                    and not q.answer_space_lines
                ):
                    missing.append(f"{label}:answer_space")
                for eq in q.equations:
                    if not eq.atu_ids and eq.source is None:
                        missing.append(f"{label}:equation_evidence")
                for fig in q.figures:
                    if not fig.atu_ids and fig.source is None:
                        missing.append(f"{label}:figure_evidence")
            if missing:
                return (
                    CheckState.FAILED,
                    f"{len(missing)} required fields missing: "
                    + ", ".join(missing[:8]),
                )
            return (
                CheckState.PASSED,
                f"{len(scored)} scored leaves fully covered",
            )
        if kind == "CURRICULUM_COMPLIANCE":
            # Declared curriculum policy vs concepts actually used in
            # solution steps — a concept outside the question's declared
            # set is a violation. No declared policy and no concept use
            # is an honestly empty audit, reported as such.
            checked = 0
            declared_total = 0
            violations: list[str] = []
            for q in doc.questions:
                label = q.label or str(q.number)
                allowed = set(q.curriculum.concepts)
                declared_total += len(allowed)
                if q.solution:
                    for c in q.solution.concepts:
                        checked += 1
                        if allowed and c not in allowed:
                            violations.append(f"{label}:{c}")
            if violations:
                return (
                    CheckState.FAILED,
                    f"{len(violations)} concepts outside declared "
                    f"curriculum: {', '.join(violations[:8])}",
                )
            return (
                CheckState.PASSED,
                f"{checked} solution concepts checked against "
                f"{declared_total} declared",
            )
        return CheckState.NOT_RUN, "no validator implemented"

    # -- source fidelity audit ---------------------------------------------------

    @staticmethod
    def _norm_audit(s: str) -> str:
        return re.sub(r"\s+", "", str(s or ""))

    def _source_fidelity(
        self, doc: Document, providers: Optional[Any], objects: Optional[Any]
    ) -> tuple[CheckState, str]:
        """Independent source audit (02_ARCHITECTURE_CONTRACTS §7.1): a
        FRESH OCR run over each question's original source region — not
        the extraction-time response — compared against the materialized
        canonical fields that would ship. Nothing materialized or no
        audit provider means the check honestly cannot run."""
        auditors = [
            p
            for p in getattr(providers, "ocr", []) or []
            if hasattr(p, "recognize_text")
            and not str(getattr(p, "name", "")).startswith("stub")
        ]
        if not auditors or objects is None:
            return (
                CheckState.NOT_RUN,
                "no OCR audit provider or object store",
            )
        auditor = auditors[0]
        compared = 0
        unaudited = 0
        unattested_misses: list[str] = []
        attested_misses = 0
        for q in doc.questions:
            label = q.label or str(q.number)
            atu_by_id = {a.id: a for a in q.atus}

            def attested(atu_ids, cmp_text: str) -> bool:
                """Human-attested fields are outside the audit's scope —
                it verifies *machine* extraction fidelity. A field is
                machine-claimed only when an AUTO_VERIFIED ATU backs the
                exact current value; a human-verified ATU, a missing ATU
                (recorded human edit), or a value that diverges from the
                machine consensus all mean a human authored it."""
                refs = [atu_by_id[i] for i in (atu_ids or []) if i in atu_by_id]
                if not refs:
                    return True
                for a in refs:
                    same = self._norm_audit(a.value) == cmp_text
                    if a.status == VerificationStatus.HUMAN_VERIFIED and same:
                        return True
                    if a.status == VerificationStatus.AUTO_VERIFIED and same:
                        return False
                return True

            fields: list[tuple[str, bool]] = []
            for s in q.body:
                t = self._norm_audit(s.text)
                if len(t) >= 4:
                    fields.append((t, attested(s.atu_ids, t)))
            for c in q.choices:
                t = self._norm_audit(" ".join(x.text for x in c.body))
                if len(t) >= 2:
                    ids = [i for s in c.body for i in s.atu_ids]
                    fields.append((t, attested(ids, t)))
            if str(label).isdigit():
                num_atu = [a.id for a in q.atus if a.field == "number"]
                fields.append(
                    (f"{label}.", attested(num_atu, str(label)))
                )
            if q.points:
                pts_atu = [a.id for a in q.atus if a.field == "points"]
                fields.append(
                    (f"{q.points}점", attested(pts_atu, str(q.points)))
                )
            if not fields:
                unaudited += 1
                continue
            if q.source is None or q.source.page >= len(doc.pages):
                unaudited += 1
                continue
            page = doc.pages[q.source.page]
            try:
                img = objects.open(page.original.uri)
                cands = auditor.recognize_text(img, q.source.bbox)
            except Exception:
                unaudited += 1
                continue
            audit_text = self._norm_audit(
                " ".join(
                    _audit_candidate_text(c.value) for c in cands if c.value
                )
            )
            if not audit_text:
                unaudited += 1
                continue
            compared += 1
            for f, ok_attested in fields:
                if not _audit_field_match(f, audit_text):
                    if ok_attested:
                        attested_misses += 1
                    else:
                        unattested_misses.append(f"{label}: {f[:30]}")
        if compared == 0:
            return (
                CheckState.FAILED,
                "no materialized fields could be audited against source",
            )
        if unattested_misses:
            return (
                CheckState.FAILED,
                f"{len(unattested_misses)} machine-extracted fields absent "
                f"from source audit: " + "; ".join(unattested_misses[:5]),
            )
        return (
            CheckState.PASSED,
            f"{compared} questions audited against original source "
            f"({unaudited} without materialized content"
            + (
                f", {attested_misses} human-attested fields not in source pixels"
                if attested_misses
                else ""
            )
            + ")",
        )

    @staticmethod
    def _check_math_figure(doc: Document) -> tuple[CheckState, str]:
        """Equation AST serializability + figure scene/table/graph
        validity + figure provenance. Invalid content fails — impossible
        or incomplete geometry becomes an issue, never a prettified pass
        (A08/S04)."""
        from document.math_ast import (
            MathParseError,
            UnsupportedMathError,
            parse_latex,
            to_hwp_script,
        )
        from document.scene import validate_graph, validate_scene, validate_table

        errors: list[str] = []
        checked = 0
        for q in doc.questions:
            label = q.label or str(q.number)
            for eq in q.equations:
                checked += 1
                if not eq.latex and not eq.hwp_formula:
                    errors.append(
                        f"q{label}: equation {eq.id} has no latex/hwp_formula"
                    )
                    continue
                if eq.latex:
                    try:
                        to_hwp_script(parse_latex(eq.latex))
                    except (MathParseError, UnsupportedMathError) as exc:
                        errors.append(f"q{label}: equation {eq.id}: {exc}")
            for fig in q.figures:
                checked += 1
                if fig.source is None and not fig.atu_ids:
                    errors.append(
                        f"q{label}: figure {fig.id} has no source evidence"
                    )
                if fig.scene is not None:
                    errors.extend(
                        f"q{label} scene: {e}" for e in validate_scene(fig.scene)
                    )
                if fig.table is not None:
                    errors.extend(
                        f"q{label} table: {e}" for e in validate_table(fig.table)
                    )
                if fig.graph is not None:
                    errors.extend(
                        f"q{label} graph: {e}" for e in validate_graph(fig.graph)
                    )
                if fig.relations and fig.scene is None:
                    errors.append(
                        f"q{label}: {len(fig.relations)} declared relations "
                        "have no scene to bind them"
                    )
        if errors:
            return CheckState.FAILED, "; ".join(errors[:8])
        return CheckState.PASSED, f"{checked} math/figure objects consistent"

    # -- solver-backed verification (WP04) ----------------------------------------

    @staticmethod
    def _spans_text(spans) -> str:
        return "".join(s.text for s in spans)

    def _problem_payload(self, q, stem_by_id: Optional[dict] = None) -> dict:
        payload = {
            "number": q.label or str(q.number),
            "type": q.type.value if hasattr(q.type, "value") else q.type,
            "points": q.points,
            "body": self._spans_text(q.body),
            "choices": {c.label: self._spans_text(c.body) for c in q.choices},
            "equations": [
                eq.latex or eq.hwp_formula or "" for eq in q.equations
            ],
            "figures": [
                {"labels": f.labels, "topology": f.topology} for f in q.figures
            ],
        }
        if q.parent_id and stem_by_id and q.parent_id in stem_by_id:
            # A shared-stem child is unsolvable without its parent's
            # setup — send the stem so the solver sees the same context
            # a student would.
            payload["shared_stem"] = stem_by_id[q.parent_id]
        return payload

    @staticmethod
    def _batch_answers(candidates) -> dict[str, str]:
        """{printed_number: normalized_answer} from a solve_batch result."""
        values = []
        for cand in candidates or []:
            v = getattr(cand, "value", None)
            if isinstance(v, list):
                values.extend(v)
        out: dict[str, str] = {}
        for item in values:
            if not isinstance(item, dict):
                continue
            num = item.get("number")
            if num is None or not item.get("solved"):
                continue
            out[str(num).strip()] = _norm_answer(item.get("answer"))
        return out

    def _solver_passes(self, doc: Document, solver) -> tuple[dict, dict]:
        """Two independent solver passes. run=1 carries a different prompt,
        so the second pass is a real call — never a cache hit replayed as
        an independent opinion (02/A34). Shared-stem parents are excluded:
        their sub-questions are verified individually, and a parent asked
        alone produces a compound answer string that cannot be normalized
        against its leaf entries."""
        parents = {q.parent_id for q in doc.questions if q.parent_id}
        stem_by_id = {
            q.id: self._spans_text(q.body) for q in doc.questions if q.id in parents
        }
        problems = [
            self._problem_payload(q, stem_by_id)
            for q in doc.questions
            if q.id not in parents
        ]
        run0 = self._batch_answers(solver.solve_batch(problems, run=0))
        run1 = self._batch_answers(solver.solve_batch(problems, run=1))
        return run0, run1

    def _solver_check(
        self, kind: str, doc: Document, passes: tuple[dict, dict]
    ) -> tuple[CheckState, str]:
        run0, run1 = passes
        if kind == "SOLVE_TWO_INDEPENDENT_AGREEMENT":
            compared = {
                n for n in run0 if n in run1
            }
            if not compared:
                return (
                    CheckState.FAILED,
                    "no comparable solver results (independent pass missing)",
                )
            disagree = sorted(
                n for n in compared if not _answers_match(run0[n], run1[n])
            )
            if disagree:
                return (
                    CheckState.FAILED,
                    f"independent solver disagreement on: {disagree}",
                )
            return CheckState.PASSED, f"{len(compared)} questions agree across 2 runs"
        if kind == "ANSWER_SOLUTION_LOGIC":
            recorded = {
                (q.label or str(q.number)): _norm_answer(q.answer.value)
                for q in doc.questions
                if q.answer is not None and q.answer.value is not None
            }
            if not recorded:
                return CheckState.FAILED, "no recorded answers to verify"
            compared = {n for n in recorded if n in run0}
            if not compared:
                return (
                    CheckState.FAILED,
                    "recorded answers and solver output share no question ids",
                )
            mismatch = sorted(
                n for n in compared if not _answers_match(recorded[n], run0[n])
            )
            if mismatch:
                return (
                    CheckState.FAILED,
                    f"answer/solution mismatch on: {mismatch}",
                )
            return CheckState.PASSED, f"{len(compared)} recorded answers match solution"
        return CheckState.NOT_RUN, "unknown solver check"

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
