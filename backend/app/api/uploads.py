from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from document.models import Document
from jobs.models import Job
from jobs.runner import run_pipeline
from jobs.store import Store

from ..deps import get_store

router = APIRouter(prefix="/api", tags=["uploads"])


@router.post("/uploads")
async def upload(
    files: list[UploadFile] = File(...),
    store: Store = Depends(get_store),
):
    if not files:
        raise HTTPException(400, "no files")

    doc = Document()
    job = store.create_job(Job(document_id=doc.id))
    upload_dir = store.job_dir(job.id) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        target = upload_dir / (f.filename or "unnamed")
        target.write_bytes(await f.read())

    store.save_document(doc)
    threading.Thread(
        target=run_pipeline, args=(store, job.id), daemon=True
    ).start()
    return {"job_id": job.id, "document_id": doc.id}
