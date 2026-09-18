from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from document.models import VerificationStatus
from jobs.store import Store
from renderers.hwp import HWPWorkerUnavailable, WindowsHWPWorker
from renderers.hwpx import render_hwpx
from renderers.pdf import render_pdf
from renderers.web import render_preview

from ..deps import get_store

router = APIRouter(prefix="/api/documents", tags=["documents"])

_REVIEW_STATUSES = {
    VerificationStatus.UNVERIFIED,
    VerificationStatus.CONFLICT,
    VerificationStatus.UNREADABLE,
}


@router.get("/{doc_id}")
def get_document(doc_id: str, store: Store = Depends(get_store)):
    try:
        return store.load_document(doc_id)
    except FileNotFoundError:
        raise HTTPException(404, "document not found")


@router.get("/{doc_id}/preview", response_class=HTMLResponse)
def preview(doc_id: str, store: Store = Depends(get_store)):
    doc = store.load_document(doc_id)
    return render_preview(doc)


@router.get("/{doc_id}/review-items")
def review_items(doc_id: str, store: Store = Depends(get_store)):
    doc = store.load_document(doc_id)
    items = []
    for q in doc.questions:
        for atu in q.atus:
            if atu.status in _REVIEW_STATUSES:
                items.append(
                    {
                        "atu_id": atu.id,
                        "question_number": q.number,
                        "question_label": q.label or str(q.number),
                        "kind": atu.kind.value,
                        "status": atu.status.value,
                        "source": atu.source.model_dump() if atu.source else None,
                        "candidates": [c.model_dump() for c in atu.candidates],
                    }
                )
    flags = [
        {
            "question_number": q.number,
            "question_label": q.label or str(q.number),
            "flags": [f.model_dump() for f in q.verification.logic_flags],
        }
        for q in doc.questions
        if q.verification.logic_flags
    ]
    return {
        "items": items,
        "logic_flags": flags,
        "gate": doc.verification.gate,
        "missing_numbers": (doc.verification.gate or {}).get("missing_numbers", []),
    }


class ResolveRequest(BaseModel):
    value: str


@router.post("/{doc_id}/review-items/{atu_id}")
def resolve_item(doc_id: str, atu_id: str, req: ResolveRequest, store: Store = Depends(get_store)):
    doc = store.load_document(doc_id)
    for q in doc.questions:
        for atu in q.atus:
            if atu.id == atu_id:
                atu.value = req.value
                atu.status = VerificationStatus.HUMAN_VERIFIED
                doc.version += 1
                store.save_document(doc)
                return {"ok": True}
    raise HTTPException(404, "atu not found")


class EditRequest(BaseModel):
    instruction: str


@router.post("/{doc_id}/edits")
def edit(doc_id: str, req: EditRequest, store: Store = Depends(get_store)):
    from core.examdna.editing import apply_ops, summarize
    from jobs.runner import _gemini_provider

    doc = store.load_document(doc_id)
    provider = _gemini_provider()
    if provider is None or not hasattr(provider, "edit_ops"):
        return {
            "ok": False,
            "instruction": req.instruction,
            "detail": "편집 provider가 없습니다 (GEMINI_API_KEY 필요)",
            "document_version": doc.version,
        }
    ops = provider.edit_ops(summarize(doc), req.instruction)
    result = apply_ops(doc, ops)
    if result["applied"]:
        store.save_document(doc)
    return {
        "ok": bool(result["applied"]),
        "instruction": req.instruction,
        **result,
        "document_version": doc.version,
    }


class ExportRequest(BaseModel):
    format: str = "hwpx"


@router.post("/{doc_id}/exports")
def export(doc_id: str, req: ExportRequest, store: Store = Depends(get_store)):
    doc = store.load_document(doc_id)
    out = store.export_dir(doc_id)
    fmt = req.format.lower()

    if fmt == "hwpx":
        path = out / "exam.hwpx"
        path.write_bytes(render_hwpx(doc))
    elif fmt == "pdf":
        path = out / "exam.pdf"
        path.write_bytes(render_pdf(doc))
    elif fmt == "hwp":
        hwpx_path = out / "exam.hwpx"
        if not hwpx_path.exists():
            hwpx_path.write_bytes(render_hwpx(doc))
        try:
            path = WindowsHWPWorker().convert(hwpx_path, out / "exam.hwp")
        except HWPWorkerUnavailable as exc:
            raise HTTPException(503, str(exc))
    else:
        raise HTTPException(400, f"unsupported format {req.format}")
    return {"file": path.name, "url": f"/api/documents/{doc_id}/files/{path.name}"}


@router.get("/{doc_id}/files/{name}")
def download(doc_id: str, name: str, store: Store = Depends(get_store)):
    path = store.export_dir(doc_id) / name
    if not path.exists() or path.parent != store.export_dir(doc_id):
        raise HTTPException(404, "file not found")
    return FileResponse(path, filename=name)
