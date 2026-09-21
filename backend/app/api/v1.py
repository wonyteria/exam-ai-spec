from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from canonical.models import (
    ArtifactState,
    ChangeOp,
    IssueState,
    JobV2State,
    RevisionMode,
)
from canonical.policy import restore_policy
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
from jobs.store import Store
from jobs.artifact_bridge import hwp_checks, hwpx_checks, pdf_checks
from renderers.hwp import HWPWorkerUnavailable, WindowsHWPWorker
from renderers.hwpx import render_hwpx
from renderers.pdf import render_pdf
from storage.local import LocalObjectStore
from tenancy.auth import AuthContext, require_auth
from tenancy.db import TenancyDB
from tenancy.models import ROLE_ACTIONS
from document.models import Document

from ..deps import get_canonical, get_object_store, get_store, get_tenancy

router = APIRouter(prefix="/api/v1", tags=["v1"])

_TERMINAL = {
    JobV2State.SUCCEEDED,
    JobV2State.FAILED,
    JobV2State.CANCELLED,
    JobV2State.COMPLETED_REVIEW_HANDOFF,
}


# --- helpers -------------------------------------------------------------------


def _request_id() -> str:
    return uuid.uuid4().hex[:16]


def _err(status: int, code: str, message: str, details: dict | None = None, retryable: bool = False):
    raise HTTPException(
        status,
        {"error": {"code": code, "message": message, "details": details or {}, "retryable": retryable}},
    )


def _tenant_ctx(tenant_id: str, request: Request, action: str) -> AuthContext:
    ctx = require_auth(request)
    db = get_tenancy()
    m = db.get_membership(tenant_id, ctx.user_id)
    if m is None:
        _err(404, "NOT_FOUND", "academy not found")
    if action not in ROLE_ACTIONS[m.role]:
        _err(403, "FORBIDDEN", f"role {m.role.value} cannot {action}")
    ctx.tenant_id = tenant_id
    ctx.role = m.role
    return ctx


def _doc_ctx(
    tenant_id: str, doc_id: str, action: str, request: Request, cstore: CanonicalStore
):
    ctx = _tenant_ctx(tenant_id, request, action)
    rec = cstore.get_document(doc_id)
    if rec is None or rec.tenant_id != tenant_id:
        _err(404, "NOT_FOUND", "document not found")
    return ctx, rec


def _if_match(request: Request) -> str | None:
    v = request.headers.get("if-match")
    return v.strip().strip('"') if v else None


def _idem(request: Request) -> str | None:
    return request.headers.get("idempotency-key")


def _handle(fn):
    """Translate service exceptions into contract error envelopes."""
    try:
        return fn()
    except ConflictError as e:
        _err(409, e.code, str(e), e.details)
    except PreconditionError as e:
        _err(428, "PRECONDITION_REQUIRED", str(e))
    except IdempotencyConflictError as e:
        _err(409, e.code, str(e), e.details)
    except StaleWorkerError as e:
        _err(409, e.code, str(e), e.details)
    except NotFoundError as e:
        _err(404, "NOT_FOUND", str(e))
    except ValidationError as e:
        _err(422, "VALIDATION", str(e), e.details)


def _service(cstore: CanonicalStore) -> MutationService:
    return MutationService(cstore, get_tenancy())


def _revision_out(rev) -> dict:
    return {
        "id": rev.id,
        "document_id": rev.document_id,
        "revision_no": rev.revision_no,
        "mode": rev.mode.value,
        "parent_revision_id": rev.parent_revision_id,
        "restores_revision_id": rev.restores_revision_id,
        "manifest_id": rev.manifest_id,
        "content_hash": rev.content_hash,
        "style_hash": rev.style_hash,
        "solution_hash": rev.solution_hash,
        "created_by": rev.created_by,
        "created_at": rev.created_at,
        "change_summary": rev.change_summary,
    }


# --- documents -----------------------------------------------------------------


@router.get("/tenants/{tenant_id}/documents/{doc_id}")
def v1_get_document(
    tenant_id: str,
    doc_id: str,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    ctx, rec = _doc_ctx(tenant_id, doc_id, "read", request, cstore)
    head = cstore.get_head_revision(doc_id)
    return {
        "data": {
            "id": rec.id,
            "tenant_id": rec.tenant_id,
            "lifecycle_state": rec.lifecycle_state.value,
            "lifecycle_version": rec.lifecycle_version,
            "head_revision": _revision_out(head) if head else None,
        },
        "request_id": _request_id(),
    }


# --- pages / source manifest (WP03) -----------------------------------------------


def _page_out(page, manifest_order: list[str]) -> dict:
    order_pos = (
        manifest_order.index(page.source_page_id)
        if page.source_page_id in manifest_order
        else None
    )
    return {
        "index": page.index,
        "source_page_id": page.source_page_id,
        "source_asset_id": page.source_asset_id,
        "pdf_page_index": page.pdf_page_index,
        "sha256": page.sha256,
        "original_name": page.original_name,
        "width": page.width,
        "height": page.height,
        "manifest_position": order_pos,
        "transform": page.transform,
        "uncertain_regions": page.uncertain_regions,
        "page_role": getattr(page, "page_role", "UNKNOWN"),
        "role_source": getattr(page, "role_source", "AUTO"),
    }


@router.get("/tenants/{tenant_id}/documents/{doc_id}/pages")
def v1_list_pages(
    tenant_id: str,
    doc_id: str,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    """Ordered source pages + the active manifest. Upload order and exam
    order are separate; the manifest is the exam order."""
    _doc_ctx(tenant_id, doc_id, "read", request, cstore)
    head = cstore.get_head_revision(doc_id)
    manifest = (
        cstore.get_manifest(head.manifest_id)
        if head and head.manifest_id
        else cstore.latest_manifest(doc_id)
    )
    doc = (
        Document.model_validate(head.content_json)
        if head
        else Document(tenant_id=tenant_id, id=doc_id)
    )
    order = manifest.page_ids_ordered if manifest else []
    return {
        "data": {
            "manifest": (
                {
                    "id": manifest.id,
                    "page_ids_ordered": order,
                    "digest": manifest.digest,
                    "confirmed_by": manifest.confirmed_by,
                    "confirmed_at": manifest.confirmed_at,
                    "missing_page_expectation": manifest.missing_page_expectation,
                }
                if manifest
                else None
            ),
            "pages": [_page_out(p, order) for p in doc.pages],
        },
        "request_id": _request_id(),
    }


class PageOrderRequest(BaseModel):
    page_ids_ordered: list[str]
    missing_page_expectation: Optional[str] = None


@router.put("/tenants/{tenant_id}/documents/{doc_id}/pages/order")
def v1_confirm_page_order(
    tenant_id: str,
    doc_id: str,
    req: PageOrderRequest,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    """Confirm or change exam page order. If-Match required (CAS); creates
    a new manifest + revision so rendered output binds to the confirmed
    page set."""
    ctx, rec = _doc_ctx(tenant_id, doc_id, "edit", request, cstore)

    def go():
        return _service(cstore).confirm_page_order(
            tenant_id,
            ctx.user_id,
            doc_id,
            _if_match(request),
            req.page_ids_ordered,
            req.missing_page_expectation,
        )

    manifest, rev = _handle(go)
    return {
        "data": {
            "manifest": {
                "id": manifest.id,
                "page_ids_ordered": manifest.page_ids_ordered,
                "digest": manifest.digest,
                "confirmed_by": manifest.confirmed_by,
                "confirmed_at": manifest.confirmed_at,
            },
            "revision": _revision_out(rev),
        },
        "request_id": _request_id(),
    }


class PageRoleRequest(BaseModel):
    page_role: str


@router.patch("/tenants/{tenant_id}/documents/{doc_id}/pages/{source_page_id}/role")
def v1_set_page_role(
    tenant_id: str,
    doc_id: str,
    source_page_id: str,
    req: PageRoleRequest,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    """User-confirmed page role (AT-061). An answer/score page must be
    explicitly designated — never silently a question page or dropped."""
    ctx, rec = _doc_ctx(tenant_id, doc_id, "edit", request, cstore)

    def go():
        return _service(cstore).set_page_role(
            tenant_id,
            ctx.user_id,
            doc_id,
            _if_match(request),
            source_page_id,
            req.page_role,
        )

    rev = _handle(go)
    sp = cstore.get_source_page(source_page_id)
    return {
        "data": {
            "source_page_id": source_page_id,
            "page_role": sp.page_role if sp else req.page_role,
            "role_source": sp.role_source if sp else "USER",
            "revision": _revision_out(rev),
        },
        "request_id": _request_id(),
    }


@router.get("/tenants/{tenant_id}/documents/{doc_id}/revisions")
def v1_list_revisions(
    tenant_id: str,
    doc_id: str,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    _doc_ctx(tenant_id, doc_id, "read", request, cstore)
    revs = cstore.list_revisions(doc_id)
    return {"data": {"revisions": [_revision_out(r) for r in revs]}, "request_id": _request_id()}


@router.get("/tenants/{tenant_id}/documents/{doc_id}/revisions/{revision_id}")
def v1_get_revision(
    tenant_id: str,
    doc_id: str,
    revision_id: str,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    _doc_ctx(tenant_id, doc_id, "read", request, cstore)
    rev = cstore.get_revision(revision_id)
    if rev is None or rev.document_id != doc_id:
        _err(404, "NOT_FOUND", "revision not found")
    out = _revision_out(rev)
    out["content_json"] = rev.content_json
    return {"data": out, "request_id": _request_id()}


class ChangesRequest(BaseModel):
    ops: list[ChangeOp]


@router.post("/tenants/{tenant_id}/documents/{doc_id}/changes")
def v1_changes(
    tenant_id: str,
    doc_id: str,
    req: ChangesRequest,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    ctx, rec = _doc_ctx(tenant_id, doc_id, "edit", request, cstore)

    def go():
        return _service(cstore).apply(
            tenant_id,
            ctx.user_id,
            doc_id,
            _if_match(request),
            req.ops,
            route="changes",
            idempotency_key=_idem(request),
            request_body=req.model_dump(),
        )

    rev = _handle(go)
    return {"data": {"revision": _revision_out(rev)}, "request_id": _request_id()}


class AgentCommandRequest(BaseModel):
    command: str


@router.post("/tenants/{tenant_id}/documents/{doc_id}/agent")
def v1_agent_propose(
    tenant_id: str,
    doc_id: str,
    req: AgentCommandRequest,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    """Exam Agent MVP (RESTORE-25): translate a natural-language command
    into typed ChangeOps + a diff preview. Nothing is applied here —
    the client reviews the proposal and submits it to /changes with
    If-Match, which creates a revision (undo/redo stays available)."""
    from agent.ops import parse_command

    _doc_ctx(tenant_id, doc_id, "edit", request, cstore)
    head = cstore.get_head_revision(doc_id)
    if head is None:
        _err(409, "NO_REVISION", "document has no revision")
    doc = Document.model_validate(head.content_json)
    proposal = parse_command(doc, req.command)
    return {
        "data": {
            "command": proposal.command,
            "recognized": proposal.recognized,
            "explanation": proposal.explanation,
            "preview": proposal.preview,
            "ops": [op.model_dump() for op in proposal.ops],
            "if_match": head.id,
        },
        "request_id": _request_id(),
    }


class ComposeRequest(BaseModel):
    count: Optional[int] = None
    difficulty_mix: dict[str, int] = {}
    units: list[str] = []
    concepts: list[str] = []
    time_budget_min: Optional[float] = None
    versions: int = 1
    seed: Optional[int] = None
    title: str = ""


@router.post("/tenants/{tenant_id}/documents/{doc_id}/compose")
def v1_compose(
    tenant_id: str,
    doc_id: str,
    req: ComposeRequest,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    """Exam Composer (RESTORE-28): build A/B/C-style variant exams from
    this document's question pool. Each version becomes its OWN
    document + revision — the source document is never mutated, and
    per-version answer keys reflect the permuted choices."""
    from composer.engine import ComposeSpec, compose_exam

    ctx, rec = _doc_ctx(tenant_id, doc_id, "edit", request, cstore)
    head = cstore.get_head_revision(doc_id)
    if head is None:
        _err(409, "NO_REVISION", "document has no revision")
    doc = Document.model_validate(head.content_json)
    spec = ComposeSpec(
        count=req.count,
        difficulty_mix=req.difficulty_mix,
        units=req.units,
        concepts=req.concepts,
        time_budget_min=req.time_budget_min,
        versions=max(1, min(req.versions, 5)),
        seed=req.seed,
    )
    result = compose_exam(doc, spec, title=req.title)
    svc = _service(cstore)
    out_docs = []
    for i, new_doc in enumerate(result.exams):
        new_doc.tenant_id = tenant_id
        rev = svc.create_revision(
            new_doc, tenant_id, ctx.user_id, mode=RevisionMode.EDIT,
            ops_summary=[{"op": "ComposeExam", "source": doc_id,
                          "version": i}],
        )
        out_docs.append({
            "document_id": new_doc.id,
            "revision_id": rev.id,
            "questions": len(new_doc.questions),
            "answer_key": result.answer_keys[i],
        })
    return {
        "data": {
            "exams": out_docs,
            "unfilled": result.unfilled,
            "total_estimated_minutes": result.total_estimated_minutes,
        },
        "request_id": _request_id(),
    }


class UndoRequest(BaseModel):
    restores_revision_id: str
    reason: str = ""


@router.post("/tenants/{tenant_id}/documents/{doc_id}/undo")
def v1_undo(
    tenant_id: str,
    doc_id: str,
    req: UndoRequest,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    ctx, rec = _doc_ctx(tenant_id, doc_id, "edit", request, cstore)
    rev = _handle(
        lambda: _service(cstore).undo(
            tenant_id,
            ctx.user_id,
            doc_id,
            _if_match(request),
            req.restores_revision_id,
            req.reason,
        )
    )
    return {"data": {"revision": _revision_out(rev)}, "request_id": _request_id()}


@router.post("/tenants/{tenant_id}/documents/{doc_id}/redo")
def v1_redo(
    tenant_id: str,
    doc_id: str,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    """Redo restores the pre-undo head — only valid directly after an
    undo revision (service enforces; 409 NOTHING_TO_REDO otherwise)."""
    ctx, rec = _doc_ctx(tenant_id, doc_id, "edit", request, cstore)
    rev = _handle(
        lambda: _service(cstore).redo(
            tenant_id, ctx.user_id, doc_id, _if_match(request)
        )
    )
    return {"data": {"revision": _revision_out(rev)}, "request_id": _request_id()}


class EditPlanRequest(BaseModel):
    instruction: str
    strict: bool = False  # reject the whole plan if any op is unmappable


@router.post("/tenants/{tenant_id}/documents/{doc_id}/edits")
def v1_edit(
    tenant_id: str,
    doc_id: str,
    req: EditPlanRequest,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    """AI edit plan (WP06): the provider proposes ops; the server
    re-validates targets/fields and applies the surviving set atomically
    through MutationService under If-Match CAS — a bad plan can never
    produce a partial mutation."""
    ctx, rec = _doc_ctx(tenant_id, doc_id, "edit", request, cstore)
    head = cstore.get_head_revision(doc_id)
    if head is None:
        _err(404, "NOT_FOUND", "no revision")
    from document.models import Document
    from core.examdna.editing import ops_to_change_ops, summarize

    doc = Document.model_validate(head.content_json)
    planner = _edit_planner()
    if planner is None:
        _err(503, "NO_EDIT_PROVIDER", "no provider with edit_ops is configured")
    raw_ops = planner.edit_ops(summarize(doc), req.instruction)
    change_ops, skipped = ops_to_change_ops(raw_ops or [])
    if not change_ops:
        _err(
            422,
            "EMPTY_EDIT_PLAN",
            "edit plan produced no applicable ops",
            {"skipped": skipped},
        )
    if req.strict and skipped:
        _err(
            422,
            "EDIT_PLAN_REJECTED",
            "plan contained unmappable ops (strict mode)",
            {"skipped": skipped},
        )
    rev = _handle(
        lambda: _service(cstore).apply(
            tenant_id,
            ctx.user_id,
            doc_id,
            _if_match(request),
            change_ops,
            route="edits",
            idempotency_key=_idem(request),
            request_body=req.model_dump(),
        )
    )
    return {
        "data": {
            "revision": _revision_out(rev),
            "applied": len(change_ops),
            "skipped": skipped,
        },
        "request_id": _request_id(),
    }


def _edit_planner():
    """First configured reasoning provider that can propose edit ops."""
    try:
        from jobs.runner import default_providers

        for p in default_providers().reasoning:
            if hasattr(p, "edit_ops"):
                return p
    except Exception:
        pass
    return None


# --- issues ----------------------------------------------------------------------


@router.get("/tenants/{tenant_id}/documents/{doc_id}/issues")
def v1_issues(
    tenant_id: str,
    doc_id: str,
    request: Request,
    state: str | None = None,
    blocking_only: bool = False,
    revision_id: str | None = None,
    cstore: CanonicalStore = Depends(get_canonical),
):
    _, rec = _doc_ctx(tenant_id, doc_id, "read", request, cstore)
    rev = (
        cstore.get_revision(revision_id)
        if revision_id
        else cstore.get_head_revision(doc_id)
    )
    if rev is None:
        _err(404, "NOT_FOUND", "revision not found")
    st = IssueState(state) if state else None
    issues = cstore.list_issues(rev.id, state=st, blocking_only=blocking_only)
    return {
        "data": {"issues": [i.model_dump() for i in issues]},
        "request_id": _request_id(),
    }


class ResolveIssueRequest(BaseModel):
    atu_id: str
    value: str


@router.post("/tenants/{tenant_id}/documents/{doc_id}/issues/{issue_id}/resolve")
def v1_resolve_issue(
    tenant_id: str,
    doc_id: str,
    issue_id: str,
    req: ResolveIssueRequest,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    """Resolving a review item is a canonical mutation: If-Match CAS, new
    revision, dependency invalidation — not an isolated field update."""
    ctx, rec = _doc_ctx(tenant_id, doc_id, "edit", request, cstore)
    issue = cstore.get_issue(issue_id)
    head = cstore.get_head_revision(doc_id)
    if issue is None or head is None or issue.revision_id != head.id:
        _err(404, "NOT_FOUND", "issue not found on current revision")

    service = _service(cstore)
    rev = _handle(
        lambda: service.apply(
            tenant_id,
            ctx.user_id,
            doc_id,
            _if_match(request),
            [ChangeOp(op="ResolveATU", target_id=req.atu_id, value=req.value)],
            route="issue.resolve",
            idempotency_key=_idem(request),
            request_body=req.model_dump(),
            mode=RevisionMode.EDIT,
        )
    )
    cstore.set_issue_state(issue_id, IssueState.RESOLVED, change_set_id=rev.id)
    return {"data": {"revision": _revision_out(rev)}, "request_id": _request_id()}


# --- checks / eligibility -----------------------------------------------------------


@router.post("/tenants/{tenant_id}/documents/{doc_id}/checks/run")
def v1_run_checks(
    tenant_id: str,
    doc_id: str,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    ctx, rec = _doc_ctx(tenant_id, doc_id, "edit", request, cstore)
    head = cstore.get_head_revision(doc_id)
    if head is None:
        _err(404, "NOT_FOUND", "no revision")
    try:
        from jobs.runner import default_providers

        providers = default_providers()
    except Exception:
        providers = None  # checks without solver support stay NOT_RUN
    checks = _service(cstore).run_checks(head.id, providers=providers)
    return {
        "data": {"checks": [c.model_dump() for c in checks]},
        "request_id": _request_id(),
    }


@router.get("/tenants/{tenant_id}/documents/{doc_id}/eligibility")
def v1_eligibility(
    tenant_id: str,
    doc_id: str,
    request: Request,
    revision_id: str | None = None,
    cstore: CanonicalStore = Depends(get_canonical),
):
    _doc_ctx(tenant_id, doc_id, "read", request, cstore)
    elig = _handle(
        lambda: _service(cstore).compute_eligibility(doc_id, tenant_id, revision_id)
    )
    return {"data": elig, "request_id": _request_id()}


# --- artifacts / exports --------------------------------------------------------------


class CreateArtifactRequest(BaseModel):
    revision_id: str
    format: str = "hwpx"
    output_mode: str = "STUDENT_WITH_ENDNOTES"
    purpose: str = "DRAFT"


@router.post("/tenants/{tenant_id}/documents/{doc_id}/artifacts")
def v1_create_artifact(
    tenant_id: str,
    doc_id: str,
    req: CreateArtifactRequest,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
    objects: LocalObjectStore = Depends(get_object_store),
):
    """Internal draft artifact generation — never a final download path."""
    ctx, rec = _doc_ctx(tenant_id, doc_id, "export", request, cstore)
    rev = cstore.get_revision(req.revision_id)
    if rev is None or rev.document_id != doc_id:
        _err(404, "NOT_FOUND", "revision not found")

    doc = Document.model_validate(rev.content_json)
    fmt = req.format.lower()
    proof = None
    if fmt == "hwpx":
        blob = render_hwpx(doc, output_mode=req.output_mode)
        sha = hashlib.sha256(blob).hexdigest()
        key = f"artifacts/{tenant_id}/{doc_id}/{rev.id}/{fmt}-{sha[:16]}.{fmt}"
        uri = objects.put(key, blob)
        art = _service(cstore).register_draft_artifact(
            tenant_id, doc_id, rev.id, fmt, uri, sha, len(blob), req.output_mode
        )
        # Server-side proof: the same checks the pipeline bridge computes
        # (own parse + independent hwpilot readback) — the artifact does
        # not rely on client-supplied claims.
        hwpx_path = objects.open(uri)
        _service(cstore).record_proof(
            art.id,
            checks=hwpx_checks(hwpx_path, doc),
            worker_identity="v1.create_artifact",
        )
    elif fmt in {"hwp", "pdf"}:
        hwpx_blob = render_hwpx(doc, output_mode=req.output_mode)
        hwpx_sha = hashlib.sha256(hwpx_blob).hexdigest()
        hwpx_key = f"artifacts/{tenant_id}/{doc_id}/{rev.id}/hwpx-{hwpx_sha[:16]}.hwpx"
        hwpx_uri = objects.put(hwpx_key, hwpx_blob)
        hwpx_art = _service(cstore).register_draft_artifact(
            tenant_id, doc_id, rev.id, "hwpx", hwpx_uri, hwpx_sha, len(hwpx_blob), req.output_mode
        )
        base = objects.open(hwpx_uri)
        hwp_path = base.with_suffix(".hwp")
        pdf_path = base.with_suffix(".pdf")
        try:
            proof = WindowsHWPWorker().convert_with_proof(
                base, hwp_path, pdf_path, request_revision=rev.id
            )
        except HWPWorkerUnavailable as exc:
            _err(503, "HWP_WORKER_UNAVAILABLE", str(exc), retryable=True)
        # The rendered PDF is also the render evidence for the HWPX
        # bytes it was produced from — record it on the intermediate
        # artifact so the hwpx format can reach eligibility honestly.
        _service(cstore).record_proof(
            hwpx_art.id,
            checks=hwpx_checks(base, doc, pdf_path=pdf_path),
            worker_identity=(proof or {}).get("worker_identity", ""),
        )
        target = hwp_path if fmt == "hwp" else pdf_path
        blob = target.read_bytes()
        sha = hashlib.sha256(blob).hexdigest()
        key = f"artifacts/{tenant_id}/{doc_id}/{rev.id}/{fmt}-{sha[:16]}.{fmt}"
        uri = objects.put(key, blob)
        art = _service(cstore).register_draft_artifact(
            tenant_id, doc_id, rev.id, fmt, uri, sha, len(blob), req.output_mode
        )
        required = set(restore_policy(req.output_mode).required_artifact_checks_by_format.get(fmt, []))
        # Same evidence as the pipeline bridge: worker step-returns +
        # rendered-PDF text + independent hwpilot readback on the binary.
        if fmt == "hwp":
            checks = hwp_checks(hwp_path, pdf_path, doc, proof or {})
        else:
            checks = pdf_checks(pdf_path, doc, proof)
        for k in required:
            if k not in checks:
                checks[k] = "FAILED"
        _service(cstore).record_proof(
            art.id, checks=checks, worker_identity=(proof or {}).get("worker_identity", "")
        )
        proof_manifest = {
            "tenant_id": tenant_id,
            "document_id": doc_id,
            "artifact_id": art.id,
            "format": fmt,
            "request_revision_id": rev.id,
            "artifact_revision_id": art.revision_id,
            "content_hash": art.content_hash,
            "style_hash": art.style_hash,
            "solution_hash": art.solution_hash,
            "artifact_sha256": art.artifact_sha256,
            "proof": proof,
            "checks": checks,
            "timestamp": time.time(),
        }
        proof_key = (
            f"artifacts/{tenant_id}/{doc_id}/{rev.id}/"
            f"{fmt}-{sha[:16]}.proof.json"
        )
        proof_uri = objects.put(
            proof_key, json.dumps(proof_manifest, ensure_ascii=False, indent=2).encode("utf-8")
        )
        proof = {**(proof or {}), "manifest_blob_key": proof_uri}
    else:
        _err(422, "VALIDATION", f"unsupported format {req.format}")
    return {
        "data": {
            "artifact": art.model_dump(),
            "proof": proof,
        },
        "request_id": _request_id(),
    }


class ProofRequest(BaseModel):
    checks: dict[str, str]
    worker_identity: str = ""


@router.post("/tenants/{tenant_id}/artifacts/{artifact_id}/proof")
def v1_record_proof(
    tenant_id: str,
    artifact_id: str,
    req: ProofRequest,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    ctx = _tenant_ctx(tenant_id, request, "export")
    art = cstore.get_artifact(artifact_id)
    if art is None or art.tenant_id != tenant_id:
        _err(404, "NOT_FOUND", "artifact not found")
    proof = _handle(
        lambda: _service(cstore).record_proof(
            artifact_id, req.checks, req.worker_identity
        )
    )
    art = cstore.get_artifact(artifact_id)
    return {
        "data": {"proof": proof.model_dump(), "artifact_state": art.state.value},
        "request_id": _request_id(),
    }


class ExportRequestV1(BaseModel):
    revision_id: str
    artifact_ids: list[str]


@router.post("/tenants/{tenant_id}/documents/{doc_id}/exports")
def v1_export(
    tenant_id: str,
    doc_id: str,
    req: ExportRequestV1,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    """Final export: EXPORT grant + exact proof binding, promotes the same
    verified bytes — stale or unproven artifacts are rejected."""
    ctx, rec = _doc_ctx(tenant_id, doc_id, "export", request, cstore)
    arts = _handle(
        lambda: _service(cstore).export_final(
            tenant_id, doc_id, req.revision_id, req.artifact_ids
        )
    )
    return {
        "data": {
            "artifacts": [
                {
                    "id": a.id,
                    "format": a.format,
                    "sha256": a.artifact_sha256,
                    "download_url": f"/api/v1/artifacts/{a.id}/download?purpose=final",
                }
                for a in arts
            ]
        },
        "request_id": _request_id(),
    }


@router.get("/artifacts/{artifact_id}/download")
def v1_download_artifact(
    artifact_id: str,
    request: Request,
    purpose: str = "draft",
    cstore: CanonicalStore = Depends(get_canonical),
    objects: LocalObjectStore = Depends(get_object_store),
):
    """Artifact bytes. `purpose=final` re-checks FINAL state + exact proof
    binding server-side; draft artifacts are marked, never confused with
    final. Reviewers are denied by the `download` action."""
    ctx = require_auth(request)
    db = get_tenancy()
    art = cstore.get_artifact(artifact_id)
    if art is None:
        _err(404, "NOT_FOUND", "artifact not found")
    m = db.get_membership(art.tenant_id, ctx.user_id)
    if m is None:
        g = db.get_document_grant(art.document_id, ctx.user_id)
        if g is None:
            _err(404, "NOT_FOUND", "artifact not found")
        role = g.role
    else:
        role = m.role
    if "download" not in ROLE_ACTIONS[role]:
        _err(403, "FORBIDDEN", f"role {role.value} cannot download")

    if purpose == "final":
        proof = cstore.get_proof_for_artifact(art.id)
        if art.state != ArtifactState.FINAL:
            _err(422, "VALIDATION", "artifact is not a promoted final")
        if proof is None or proof.artifact_sha256 != art.artifact_sha256:
            _err(409, "PROOF_MISMATCH", "proof does not bind these exact bytes")
    elif purpose == "draft":
        if art.state == ArtifactState.FINAL:
            pass  # a final artifact can also be fetched as its bytes
    else:
        _err(422, "VALIDATION", f"unknown purpose {purpose}")

    path = objects.open(art.blob_key)
    if not path.exists():
        _err(404, "NOT_FOUND", "artifact blob missing")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != art.artifact_sha256:
        _err(409, "HASH_MISMATCH", "stored bytes no longer match the artifact record")
    headers = {}
    if purpose == "draft":
        headers["X-Draft-Revision"] = art.revision_id
        headers["X-Draft"] = "true"
    return FileResponse(
        path,
        filename=f"{art.format}-{art.id}.{art.format}",
        headers=headers,
    )


# --- jobs -------------------------------------------------------------------------


class SubmitJobRequest(BaseModel):
    kind: str = "restore_pipeline"
    revision_id: str | None = None


@router.post("/tenants/{tenant_id}/jobs/{job_id}/retry")
def v1_retry_job(
    tenant_id: str,
    job_id: str,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    ctx = _tenant_ctx(tenant_id, request, "edit")
    job = cstore.get_job(job_id)
    if job is None or job.tenant_id != tenant_id:
        _err(404, "NOT_FOUND", "job not found")
    if job.state not in (JobV2State.FAILED, JobV2State.CANCELLED):
        _err(409, "ILLEGAL_TRANSITION", f"cannot retry a {job.state.value} job")
    with cstore._lock, cstore._conn:
        cstore._conn.execute(
            "UPDATE jobs SET state='QUEUED', not_before=?, cancel_requested_at=NULL WHERE id=?",
            (time.time(), job_id),
        )
    return {"data": {"job_id": job_id, "state": "QUEUED"}, "request_id": _request_id()}


@router.get("/tenants/{tenant_id}/jobs/{job_id}")
def v1_get_job(
    tenant_id: str,
    job_id: str,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    _tenant_ctx(tenant_id, request, "read")
    job = cstore.get_job(job_id)
    if job is None or job.tenant_id != tenant_id:
        _err(404, "NOT_FOUND", "job not found")
    return {"data": job.model_dump(), "request_id": _request_id()}


@router.get("/tenants/{tenant_id}/jobs/{job_id}/events")
async def v1_job_events(
    tenant_id: str,
    job_id: str,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
):
    """Durable SSE: every event has a persisted seq; Last-Event-ID resumes
    after it. A cursor ahead of the newest event is a client bug, not data
    loss — events are retained, so replay always works."""
    _tenant_ctx(tenant_id, request, "read")
    job = cstore.get_job(job_id)
    if job is None or job.tenant_id != tenant_id:
        _err(404, "NOT_FOUND", "job not found")

    last_id = request.headers.get("last-event-id")
    after = 0
    if last_id:
        try:
            after = int(str(last_id).split(":")[-1])
        except ValueError:
            _err(422, "VALIDATION", "invalid Last-Event-ID cursor")

    async def stream():
        sent = after
        while True:
            events = cstore.events_since(job_id, sent)
            for e in events:
                payload = {
                    "job_id": job_id,
                    "seq": e.seq,
                    "timestamp": e.ts,
                    "state": e.state,
                    "stage": e.stage,
                    "revision_id": e.revision_id,
                    "completed_units": e.completed_units,
                    "total_units": e.total_units,
                    "error": e.error,
                    **e.data,
                }
                yield f"id: {job_id}:{e.seq}\nevent: {e.event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                sent = e.seq
            cur = cstore.get_job(job_id)
            if cur is None:
                return
            if cur.state in _TERMINAL and sent >= cstore.max_event_seq(job_id):
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream")
