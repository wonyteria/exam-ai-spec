from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from canonical.models import JobV2
from canonical.store import CanonicalStore
from canonical.service import MutationService
from document.models import Document, Page, PageImage
from jobs.store import Store
from jobs.worker import run_once
from storage.local import LocalObjectStore, sanitize_filename
from tenancy.auth import AuthContext, audit, require_action
from tenancy.db import TenancyDB

from ..deps import get_canonical, get_object_store, get_store, get_tenancy

router = APIRouter(prefix="/api", tags=["uploads"])

MAX_FILE_BYTES = 50 * 1024 * 1024  # ADR baseline: 50 MiB per file
MAX_FILES = 50


@router.post("/uploads")
async def upload(
    request: Request,
    files: list[UploadFile] = File(...),
    store: Store = Depends(get_store),
    objects: LocalObjectStore = Depends(get_object_store),
    cstore: CanonicalStore = Depends(get_canonical),
    tenancy: TenancyDB = Depends(get_tenancy),
    ctx: AuthContext = Depends(require_action("upload")),
):
    if not files:
        raise HTTPException(400, "no files")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"too many files (max {MAX_FILES} pages)")

    assert ctx.tenant_id is not None
    doc = Document(tenant_id=ctx.tenant_id)

    # Originals are immutable blobs in private object storage — never
    # served directly, only through authorized endpoints (WP01).
    for i, f in enumerate(files):
        data = await f.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, f"file too large: {f.filename}")
        name = sanitize_filename(f.filename or f"page{i+1}")
        uri = objects.put(f"uploads/{ctx.tenant_id}/{doc.id}/{i:03d}_{name}", data)
        doc.pages.append(Page(index=i, original=PageImage(uri=uri)))

    store.save_document(doc)

    # Canonical record + first revision + durable job (WP02 contract).
    service = MutationService(cstore, tenancy)
    service.create_revision(doc, ctx.tenant_id, ctx.user_id)
    job = cstore.create_job(
        JobV2(
            tenant_id=ctx.tenant_id,
            document_id=doc.id,
            input_revision_id=cstore.get_document(doc.id).head_revision_id,
            created_by=ctx.user_id,
        )
    )

    audit(
        request,
        ctx,
        "document.upload",
        "document",
        doc.id,
        {"files": len(files), "job_id": job.id},
    )
    threading.Thread(
        target=run_once,
        args=(cstore, store, objects, tenancy, "api-worker"),
        daemon=True,
    ).start()
    return {"job_id": job.id, "document_id": doc.id}
