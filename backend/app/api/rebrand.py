"""Imported HWP/HWPX rebranding API (REQ-16 / HWP_REBRANDING_SPEC).

Flow (fail-closed at every step):
  POST   /api/v1/tenants/{t}/rebrand/imports      — immutable source upload
  POST   /api/v1/tenants/{t}/rebrand/logo          — academy logo asset
  GET    /api/v1/tenants/{t}/documents/{d}/rebrand/candidates — structure census
  POST   /api/v1/tenants/{t}/documents/{d}/rebrand/apply      — confirmed plan →
         allowlisted mutation → new revision + draft artifact + proof manifest

Sources are never mutated. HWP sources require real Hancom COM to become
scannable HWPX — unavailable worker answers 503, never a fake conversion.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from canonical.models import (
    RevisionMode,
    SourceAsset,
    SourceManifest,
    SourcePage,
)
from canonical.store import CanonicalStore
from canonical.service import MutationService
from canonical.policy import restore_policy
from document.models import Document, Page, PageImage
from jobs.store import Store
from rebranding import build_plan, scan_hwpx
from rebranding.hwpx_mutator import apply_plan
from rebranding.models import (
    BrandRewriteRequest,
    PlanError,
    TitlePolicy,
    WatermarkSpec,
)
from rebranding.proof import build_proof_manifest
from renderers.hwp import HWPWorkerUnavailable, WindowsHWPWorker
from storage.local import LocalObjectStore
from tenancy.auth import AuthContext, audit, require_auth
from tenancy.db import TenancyDB
from tenancy.models import ROLE_ACTIONS

from ..deps import get_canonical, get_object_store, get_store, get_tenancy
from .v1 import _doc_ctx, _err, _request_id, _revision_out, _service

router = APIRouter(prefix="/api/v1", tags=["rebrand"])

MAX_IMPORT_BYTES = 50 * 1024 * 1024
MAX_LOGO_BYTES = 10 * 1024 * 1024


def _sniff_import(data: bytes, filename: str) -> str:
    """hwpx (zip package) or hwp (OLE compound). Anything else is rejected
    — ambiguous formats fail closed rather than being guessed at."""
    if data[:5] == b"%PDF-" or data.startswith(b"\x89PNG"):
        _err(422, "UNSUPPORTED_TYPE", f"not an HWP/HWPX file: {filename}")
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "hwp"
    if data.startswith(b"PK"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
            if "mimetype" in zf.namelist():
                return "hwpx"
        except zipfile.BadZipFile:
            pass
        _err(422, "UNSUPPORTED_TYPE", f"not a valid HWPX package: {filename}")
    _err(422, "UNSUPPORTED_TYPE", f"unrecognized document format: {filename}")


def _source_bytes(cstore: CanonicalStore, objects: LocalObjectStore, doc_id: str):
    """(asset, bytes) of the imported source — immutable by construction."""
    pages = cstore.list_source_pages(doc_id)
    if not pages:
        _err(404, "NOT_FOUND", "no source pages for document")
    asset = cstore.get_source_asset(pages[0].asset_id)
    if asset is None:
        _err(404, "NOT_FOUND", "source asset missing")
    return asset, objects.open(f"local://{asset.blob_key}").read_bytes()


def _work_hwpx(
    tenant_id: str,
    doc_id: str,
    cstore: CanonicalStore,
    objects: LocalObjectStore,
) -> bytes:
    """Bytes of the scannable HWPX. HWPX sources are read directly; HWP
    sources go through the real Hancom COM conversion on a *copy* — no
    worker, no fake scan: 503."""
    asset, raw = _source_bytes(cstore, objects, doc_id)
    fmt = _sniff_format(raw)
    if fmt == "hwpx":
        return raw
    work_key = f"rebrand/{tenant_id}/{doc_id}/work.hwpx"
    work_uri = f"local://{work_key}"
    if objects.exists(work_uri):
        return objects.open(work_uri).read_bytes()
    worker = WindowsHWPWorker()
    src_path = objects.open(f"local://{asset.blob_key}")
    out_path = src_path.with_name("work.hwpx")
    try:
        worker.convert_to_hwpx(
            src_path, out_path, operation_kind="REBRAND_SCAN_CONVERT"
        )
    except HWPWorkerUnavailable as exc:
        _err(503, "HWP_WORKER_UNAVAILABLE", str(exc), retryable=True)
    except Exception as exc:  # noqa: BLE001
        _err(
            503,
            "HWP_CONVERT_FAILED",
            f"Hancom HWP→HWPX conversion failed: {exc}",
            retryable=True,
        )
    data = out_path.read_bytes()
    objects.put(work_key, data)
    return data


def _sniff_format(raw: bytes) -> str:
    if raw.startswith(b"\xd0\xcf\x11\xe0"):
        return "hwp"
    return "hwpx"


@router.post("/tenants/{tenant_id}/rebrand/imports")
async def rebrand_import(
    tenant_id: str,
    request: Request,
    file: UploadFile = File(...),
    cstore: CanonicalStore = Depends(get_canonical),
    objects: LocalObjectStore = Depends(get_object_store),
    store: Store = Depends(get_store),
    tenancy: TenancyDB = Depends(get_tenancy),
):
    """Register an imported HWP/HWPX as an immutable source document."""
    ctx = require_auth(request)
    m = tenancy.get_membership(tenant_id, ctx.user_id)
    if m is None:
        _err(404, "NOT_FOUND", "academy not found")
    if "upload" not in ROLE_ACTIONS[m.role]:
        _err(403, "FORBIDDEN", f"role {m.role.value} cannot upload")
    ctx.tenant_id = tenant_id

    data = await file.read()
    if not data:
        _err(422, "VALIDATION", "empty file")
    if len(data) > MAX_IMPORT_BYTES:
        _err(422, "FILE_TOO_LARGE", f"file exceeds {MAX_IMPORT_BYTES} bytes")
    fmt = _sniff_import(data, file.filename or "import")
    sha = hashlib.sha256(data).hexdigest()

    doc = Document(tenant_id=tenant_id)
    doc.metadata.subject = "imported"
    cstore.create_document(tenant_id, created_by=ctx.user_id, doc_id=doc.id)

    blob_key = f"imports/{tenant_id}/{doc.id}/source.{fmt}"
    objects.put(blob_key, data)
    asset = cstore.put_source_asset(
        SourceAsset(
            tenant_id=tenant_id,
            sha256=sha,
            mime="application/x-hwpx" if fmt == "hwpx" else "application/x-hwp",
            byte_size=len(data),
            original_name=file.filename or f"source.{fmt}",
            blob_key=blob_key,
        )
    )
    sp = SourcePage(
        tenant_id=tenant_id,
        document_id=doc.id,
        asset_id=asset.id,
        original_sha256=sha,
        original_name=file.filename or f"source.{fmt}",
        page_role="UNKNOWN",
        role_source="AUTO",
    )
    cstore.put_source_page(sp)
    manifest = cstore.create_manifest(
        SourceManifest(
            tenant_id=tenant_id,
            document_id=doc.id,
            page_ids_ordered=[sp.id],
        )
    )
    doc.pages.append(
        Page(
            index=0,
            original=PageImage(uri=f"local://{blob_key}"),
            source_asset_id=asset.id,
            source_page_id=sp.id,
            sha256=sha,
            original_name=file.filename or "",
        )
    )
    store.save_document(doc)
    service = MutationService(cstore, tenancy)
    rev = service.create_revision(
        doc, tenant_id, ctx.user_id, manifest_id=manifest.id
    )
    audit(
        request,
        ctx,
        "rebrand.import",
        "document",
        doc.id,
        {"format": fmt, "sha256": sha, "name": file.filename},
    )
    return {
        "data": {
            "document_id": doc.id,
            "source_format": fmt,
            "source_sha256": sha,
            "revision_id": rev.id,
            "hancom_required": fmt == "hwp",
        },
        "request_id": _request_id(),
    }


@router.post("/tenants/{tenant_id}/rebrand/logo")
async def rebrand_logo(
    tenant_id: str,
    request: Request,
    file: UploadFile = File(...),
    objects: LocalObjectStore = Depends(get_object_store),
    tenancy: TenancyDB = Depends(get_tenancy),
):
    """Academy logo for watermarking — content-addressed blob."""
    ctx = require_auth(request)
    m = tenancy.get_membership(tenant_id, ctx.user_id)
    if m is None:
        _err(404, "NOT_FOUND", "academy not found")
    if "upload" not in ROLE_ACTIONS[m.role]:
        _err(403, "FORBIDDEN", f"role {m.role.value} cannot upload")
    data = await file.read()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        _err(422, "UNSUPPORTED_TYPE", "logo must be a PNG image")
    if len(data) > MAX_LOGO_BYTES:
        _err(422, "FILE_TOO_LARGE", "logo exceeds 10MB")
    sha = hashlib.sha256(data).hexdigest()
    objects.put(f"imports/{tenant_id}/logos/{sha}.png", data)
    return {"data": {"logo_sha256": sha}, "request_id": _request_id()}


@router.get("/tenants/{tenant_id}/documents/{doc_id}/rebrand/candidates")
def rebrand_candidates(
    tenant_id: str,
    doc_id: str,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
    objects: LocalObjectStore = Depends(get_object_store),
):
    """Structure census — every title/watermark/page-number candidate with
    deterministic ids, exact paths, and digests for confirmation."""
    _doc_ctx(tenant_id, doc_id, "read", request, cstore)
    hwpx = _work_hwpx(tenant_id, doc_id, cstore, objects)
    manifest = scan_hwpx(hwpx, source_name=doc_id)
    objects.put(
        f"rebrand/{tenant_id}/{doc_id}/manifest-{manifest.source_sha256[:12]}.json",
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2).encode(),
    )
    return {
        "data": {
            "manifest": manifest.model_dump(mode="json"),
            "needs_confirmation": [c.id for c in manifest.needs_confirmation()],
            "fail_closed_flags": manifest.flags.model_dump(),
        },
        "request_id": _request_id(),
    }


class RebrandApplyRequest(BaseModel):
    academy_name: str
    confirmed_candidate_ids: list[str] = Field(default_factory=list)
    remove_page_numbers: bool = True
    title_policy: str = "USER_CONFIRMED"
    watermark_enabled: bool = True
    watermark_opacity: float = 0.30
    watermark_scale: float = 0.35
    watermark_replace_existing: bool = False
    logo_sha256: str = ""


@router.post("/tenants/{tenant_id}/documents/{doc_id}/rebrand/apply")
def rebrand_apply(
    tenant_id: str,
    doc_id: str,
    req: RebrandApplyRequest,
    request: Request,
    cstore: CanonicalStore = Depends(get_canonical),
    objects: LocalObjectStore = Depends(get_object_store),
    store: Store = Depends(get_store),
    tenancy: TenancyDB = Depends(get_tenancy),
):
    """Confirmed plan → allowlisted mutation on a copy → new revision +
    draft artifact + rebrand proof. Never touches the source."""
    ctx, _rec = _doc_ctx(tenant_id, doc_id, "edit", request, cstore)
    hwpx = _work_hwpx(tenant_id, doc_id, cstore, objects)
    manifest = scan_hwpx(hwpx, source_name=doc_id)

    logo_png = None
    if req.logo_sha256:
        logo_key = f"imports/{tenant_id}/logos/{req.logo_sha256}.png"
        uri = f"local://{logo_key}"
        if not objects.exists(uri):
            _err(404, "NOT_FOUND", "logo asset not found")
        logo_png = objects.open(uri).read_bytes()

    breq = BrandRewriteRequest(
        tenant_id=tenant_id,
        source_id=doc_id,
        source_sha256=manifest.source_sha256,
        academy_name=req.academy_name,
        logo_sha256=req.logo_sha256,
        title_policy=TitlePolicy(req.title_policy),
        watermark=WatermarkSpec(
            enabled=req.watermark_enabled,
            opacity=req.watermark_opacity,
            scale=req.watermark_scale,
            replace_existing=req.watermark_replace_existing,
        ),
        remove_page_numbers=req.remove_page_numbers,
        confirmed_candidate_ids=req.confirmed_candidate_ids,
        requested_by=ctx.user_id,
    )
    try:
        plan = build_plan(manifest, breq)
        out_hwpx, invariant = apply_plan(hwpx, plan, logo_png=logo_png)
    except PlanError as exc:
        status = 422 if exc.code not in {"SOURCE_UNSUPPORTED", "SOURCE_UNSAFE"} else 409
        _err(status, exc.code, str(exc), exc.details)

    out_sha = hashlib.sha256(out_hwpx).hexdigest()

    # new revision bound to the same manifest (page set unchanged)
    service = MutationService(cstore, tenancy)
    head = cstore.get_head_revision(doc_id)
    doc = Document.model_validate(head.content_json)
    rev = service.create_revision(
        doc,
        tenant_id,
        ctx.user_id,
        mode=RevisionMode.EDIT,
        ops_summary=[
            {
                "op": "rebrand_apply",
                "plan_digest": plan.digest,
                "removed": invariant.removed_paths,
                "replaced": invariant.replaced_paths,
                "added": invariant.added_paths,
            }
        ],
        manifest_id=head.manifest_id,
    )

    key = f"rebrand/{tenant_id}/{doc_id}/{rev.id}/out-{out_sha[:16]}.hwpx"
    uri = objects.put(key, out_hwpx)
    art = service.register_draft_artifact(
        tenant_id, doc_id, rev.id, "hwpx", uri, out_sha, len(out_hwpx)
    )

    # real Hancom proof when the worker exists — never faked
    worker_proof = None
    worker_unavailable = False
    try:
        out_path = objects.open(uri)
        proof = WindowsHWPWorker().convert_with_proof(
            out_path,
            out_path.with_suffix(".hwp"),
            out_path.with_suffix(".pdf"),
            request_revision=rev.id,
            operation_kind="REBRAND_PROOF",
        )
        worker_proof = proof
    except HWPWorkerUnavailable:
        worker_unavailable = True
    except Exception:  # noqa: BLE001
        worker_unavailable = True

    rebrand_proof = build_proof_manifest(
        tenant_id=tenant_id,
        document_id=doc_id,
        source_id=doc_id,
        source_name=doc.pages[0].original_name if doc.pages else "",
        source_sha256=manifest.source_sha256,
        output_sha256=out_sha,
        output_format="hwpx",
        manifest=manifest,
        plan=plan,
        invariant=invariant,
        worker_proof=worker_proof,
        artifact_id=art.id,
    )
    checks = dict(rebrand_proof["checks"])
    required = set(
        restore_policy("STUDENT_WITH_ENDNOTES")
        .required_artifact_checks_by_format.get("hwpx", [])
    )
    for k in required:
        checks.setdefault(k, "NOT_RUN")
    service.record_proof(
        art.id,
        checks=checks,
        worker_identity=(worker_proof or {}).get("worker_identity", ""),
    )
    proof_key = f"rebrand/{tenant_id}/{doc_id}/{rev.id}/proof-{out_sha[:16]}.json"
    objects.put(proof_key, json.dumps(rebrand_proof, ensure_ascii=False, indent=2).encode())

    audit(
        request,
        ctx,
        "rebrand.apply",
        "document",
        doc_id,
        {
            "revision_id": rev.id,
            "artifact_id": art.id,
            "plan_digest": plan.digest,
            "output_sha256": out_sha,
        },
    )
    return {
        "data": {
            "revision": _revision_out(rev),
            "artifact": art.model_dump(),
            "invariant": invariant.model_dump(),
            "proof": rebrand_proof,
            "worker_unavailable": worker_unavailable,
        },
        "request_id": _request_id(),
    }
