from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from document.models import Document
from jobs.models import Job
from jobs.runner import run_pipeline
from jobs.store import Store
from storage.local import LocalObjectStore, sanitize_filename
from tenancy.auth import AuthContext, audit, require_action

from ..deps import get_object_store, get_store

router = APIRouter(prefix="/api", tags=["uploads"])

MAX_FILE_BYTES = 50 * 1024 * 1024  # ADR baseline: 50 MiB per file


@router.post("/uploads")
async def upload(
    request: Request,
    files: list[UploadFile] = File(...),
    store: Store = Depends(get_store),
    objects: LocalObjectStore = Depends(get_object_store),
    ctx: AuthContext = Depends(require_action("upload")),
):
    if not files:
        raise HTTPException(400, "no files")
    if len(files) > 50:
        raise HTTPException(400, "too many files (max 50 pages)")

    assert ctx.tenant_id is not None
    doc = Document(tenant_id=ctx.tenant_id)
    job = store.create_job(Job(document_id=doc.id, tenant_id=ctx.tenant_id))

    # Originals are immutable blobs in private object storage — never
    # served directly, only through authorized endpoints (WP01).
    for i, f in enumerate(files):
        data = await f.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, f"file too large: {f.filename}")
        name = sanitize_filename(f.filename or f"page{i+1}")
        uri = objects.put(f"uploads/{ctx.tenant_id}/{doc.id}/{i:03d}_{name}", data)
        from document.models import Page, PageImage

        doc.pages.append(Page(index=i, original=PageImage(uri=uri)))

    store.save_document(doc)
    audit(
        request,
        ctx,
        "document.upload",
        "document",
        doc.id,
        {"files": len(files), "job_id": job.id},
    )
    threading.Thread(
        target=run_pipeline, args=(store, job.id), daemon=True
    ).start()
    return {"job_id": job.id, "document_id": doc.id}
