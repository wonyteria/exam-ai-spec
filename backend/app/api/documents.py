from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from document.models import VerificationStatus
from jobs.store import Store
from renderers.hwp import HWPWorkerUnavailable, WindowsHWPWorker
from renderers.hwpx import render_hwpx
from renderers.pdf import render_pdf
from renderers.web import render_preview
from storage.local import LocalObjectStore, sanitize_filename
from tenancy.auth import (
    AuthContext,
    audit,
    require_action,
    require_tenant,
    resolve_document_access,
)

from ..deps import get_object_store, get_store

router = APIRouter(prefix="/api/documents", tags=["documents"])

_REVIEW_STATUSES = {
    VerificationStatus.UNVERIFIED,
    VerificationStatus.CONFLICT,
    VerificationStatus.UNREADABLE,
}


def doc_access(action: str):
    """Dependency: resolve document + tenant/role authorization before the
    request body is validated, so unauthorized callers always get 404/403
    rather than a 422 that could distinguish request shapes."""

    def dep(
        doc_id: str, request: Request, store: Store = Depends(get_store)
    ):
        return resolve_document_access(doc_id, action, request, store)

    return dep


def _image_path(uri: str, objects: LocalObjectStore) -> Path:
    if uri.startswith("local://"):
        return objects.open(uri)
    return Path(uri)


def _read_document(access):
    """Canonical head revision is the authoritative read model once a
    canonical record exists; the legacy flat doc is only a fallback.
    Reads that skipped this would serve pre-mutation content (resolved
    ATUs still open, edits invisible)."""
    from document.models import Document

    ctx, doc = access
    _, head = _canonical_for(doc.id)
    if head is not None and head.content_json:
        try:
            return ctx, Document.model_validate(head.content_json)
        except Exception:
            pass
    return access


@router.get("")
def list_documents(
    request: Request,
    store: Store = Depends(get_store),
    ctx: AuthContext = Depends(require_tenant),
):
    """Document library for the caller's active academy only."""
    from document.models import Document

    docs = store.list_documents(ctx.tenant_id)
    out = []
    for d in docs:
        # Overlay the canonical head when it exists so post-mutation
        # counts/status (renumbering, resolved ATUs) are not stale.
        _, head = _canonical_for(d.id)
        if head is not None and head.content_json:
            try:
                d = Document.model_validate(head.content_json)
            except Exception:
                pass
        out.append(
            {
                "id": d.id,
                "version": d.version,
                "pages": len(d.pages),
                "questions": len(d.questions),
                "status": d.verification.status,
                "metadata": d.metadata.model_dump(),
            }
        )
    return {"documents": out}


@router.get("/{doc_id}")
def get_document(access=Depends(doc_access("read"))):
    _, doc = _read_document(access)
    return doc


@router.get("/{doc_id}/preview", response_class=HTMLResponse)
def preview(
    output_mode: str = "STUDENT_WITH_ENDNOTES",
    access=Depends(doc_access("read")),
):
    from renderers.plan import OUTPUT_MODES

    _, doc = _read_document(access)
    if output_mode not in OUTPUT_MODES:
        raise HTTPException(400, f"unsupported output_mode {output_mode}")
    return render_preview(doc, output_mode=output_mode)


@router.get("/{doc_id}/crops/{page_index}")
def source_crop(
    doc_id: str,
    page_index: int,
    request: Request,
    x: float = 0,
    y: float = 0,
    w: float = 0,
    h: float = 0,
    source: str = "original",
    access=Depends(doc_access("review")),
    objects: LocalObjectStore = Depends(get_object_store),
):
    """Source image region for review — default the original scan (with the
    student's marks); `source=clean` serves the restored print layer."""
    import io

    from PIL import Image

    _, doc = _read_document(access)
    if page_index >= len(doc.pages):
        raise HTTPException(404, "page not found")
    page = doc.pages[page_index]
    uri = page.original.uri if source == "original" else (page.clean_uri or page.original.uri)
    path = _image_path(uri, objects)
    if not path.exists():
        raise HTTPException(404, "source image not found")
    with Image.open(path) as im:
        base = im.convert("RGB")
        if w > 0 and h > 0:
            pad = 8
            box = (
                max(0, int(x) - pad),
                max(0, int(y) - pad),
                min(base.width, int(x + w) + pad),
                min(base.height, int(y + h) + pad),
            )
            base = base.crop(box)
        buf = io.BytesIO()
        base.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")


@router.get("/{doc_id}/review-items")
def review_items(access=Depends(doc_access("review"))):
    _, doc = _read_document(access)
    items = []
    for q in doc.questions:
        for atu in q.atus:
            if atu.status in _REVIEW_STATUSES:
                items.append(
                    {
                        "atu_id": atu.id,
                        "question_number": q.number,
                        "question_label": q.label or str(q.number),
                        # Whole-question region — reviewers confirm a
                        # masked number against the full printed block,
                        # not just the ATU-level crop.
                        "question_source": (
                            q.source.model_dump() if q.source else None
                        ),
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
    # Missing printed numbers reflect the CURRENT labels — the gate
    # snapshot is pipeline-time evidence; a confirmed `?`-label must not
    # keep reporting its number as missing.
    numeric = {int(q.label) for q in doc.questions if (q.label or "").isdigit()}
    missing = (
        [n for n in range(1, max(numeric) + 1) if n not in numeric]
        if numeric
        else []
    )
    unresolved = [
        q.label for q in doc.questions if (q.label or "").startswith("?")
    ]
    return {
        "items": items,
        "logic_flags": flags,
        "gate": doc.verification.gate,
        "missing_numbers": missing,
        "unresolved_labels": unresolved,
    }


class ResolveRequest(BaseModel):
    value: str


@router.post("/{doc_id}/review-items/{atu_id}")
def resolve_item(
    doc_id: str,
    atu_id: str,
    req: ResolveRequest,
    request: Request,
    access=Depends(doc_access("edit")),
    store: Store = Depends(get_store),
):
    """Review resolution is a canonical mutation when a canonical record
    exists (ResolveATU → new revision, check invalidation, audit). The
    legacy flat-document path is kept for non-canonical docs."""
    ctx, doc = access
    service, head = _canonical_for(doc_id)
    if service is not None and head is not None:
        from canonical.models import ChangeOp
        from canonical.store import ConflictError, NotFoundError, PreconditionError, ValidationError

        try:
            service.apply(
                ctx.tenant_id,
                ctx.user_id,
                doc_id,
                head.id,
                [ChangeOp(op="ResolveATU", target_id=atu_id, value=req.value)],
                route="review.resolve",
            )
        except NotFoundError:
            raise HTTPException(404, "atu not found")
        except (ConflictError, PreconditionError, ValidationError) as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True, "revisioned": True}
    for q in doc.questions:
        for atu in q.atus:
            if atu.id == atu_id:
                atu.value = req.value
                atu.status = VerificationStatus.HUMAN_VERIFIED
                doc.version += 1
                store.save_document(doc)
                audit(request, ctx, "document.review.resolve", "document", doc_id,
                      {"atu_id": atu_id, "version": doc.version})
                return {"ok": True}
    raise HTTPException(404, "atu not found")


def _canonical_for(doc_id: str):
    """(MutationService, head_revision) when a canonical record exists,
    else (None, None) — legacy documents keep the flat path."""
    try:
        from canonical.service import MutationService

        from ..deps import get_canonical, get_tenancy

        cstore = get_canonical()
        rec = cstore.get_document(doc_id)
        if rec is None:
            return None, None
        head = cstore.get_head_revision(doc_id)
        return MutationService(cstore, get_tenancy()), head
    except Exception:
        return None, None


class EditRequest(BaseModel):
    instruction: str


@router.post("/{doc_id}/edits")
def edit(
    doc_id: str,
    req: EditRequest,
    request: Request,
    access=Depends(doc_access("edit")),
    store: Store = Depends(get_store),
):
    from core.examdna.editing import apply_ops, ops_to_change_ops, summarize
    from jobs.runner import default_providers

    ctx, doc = _read_document(access)
    planner = next(
        (p for p in default_providers().reasoning if hasattr(p, "edit_ops")),
        None,
    )
    if planner is None:
        return {
            "ok": False,
            "instruction": req.instruction,
            "detail": "편집 provider가 없습니다 (AI API 키 필요)",
            "document_version": doc.version,
        }
    service, head = _canonical_for(doc_id)
    if service is not None and head is not None:
        # Canonical path: validate plan -> atomic apply (no partial edits)
        from canonical.models import ChangeOp
        from canonical.store import ConflictError, NotFoundError, PreconditionError, ValidationError

        ops, skipped = ops_to_change_ops(
            planner.edit_ops(summarize(doc), req.instruction) or []
        )
        if not ops:
            return {
                "ok": False,
                "instruction": req.instruction,
                "applied": [],
                "skipped": skipped,
                "document_version": doc.version,
            }
        try:
            rev = service.apply(
                ctx.tenant_id, ctx.user_id, doc_id, head.id, ops,
                route="edits",
            )
        except (ConflictError, NotFoundError, PreconditionError, ValidationError) as exc:
            raise HTTPException(409, str(exc))
        return {
            "ok": True,
            "instruction": req.instruction,
            "applied": [{"op": o.op, "target": o.target_id} for o in ops],
            "skipped": skipped,
            "revision_id": rev.id,
            "document_version": doc.version,
        }
    ops = planner.edit_ops(summarize(doc), req.instruction)
    result = apply_ops(doc, ops)
    if result["applied"]:
        store.save_document(doc)
        audit(request, ctx, "document.edit", "document", doc_id,
              {"instruction": req.instruction, "version": doc.version})
    return {
        "ok": bool(result["applied"]),
        "instruction": req.instruction,
        **result,
        "document_version": doc.version,
    }


class ExportRequest(BaseModel):
    format: str = "hwpx"
    output_mode: str = "STUDENT_WITH_ENDNOTES"
    brand_id: str | None = None


@router.post("/{doc_id}/exports")
def export(
    doc_id: str,
    req: ExportRequest,
    request: Request,
    access=Depends(doc_access("export")),
    store: Store = Depends(get_store),
):
    from renderers.plan import OUTPUT_MODES

    ctx, doc = _read_document(access)
    out = store.export_dir(doc_id)
    fmt = req.format.lower()
    if req.output_mode not in OUTPUT_MODES:
        raise HTTPException(400, f"unsupported output_mode {req.output_mode}")
    mode = req.output_mode

    if fmt == "hwpx":
        path = out / "exam.hwpx"
        path.write_bytes(render_hwpx(doc, output_mode=mode, brand_id=req.brand_id))
    elif fmt == "pdf":
        path = out / "exam.pdf"
        path.write_bytes(render_pdf(doc, output_mode=mode))
    elif fmt == "hwp":
        hwpx_path = out / "exam.hwpx"
        if not hwpx_path.exists():
            hwpx_path.write_bytes(
                render_hwpx(doc, output_mode=mode, brand_id=req.brand_id)
            )
        try:
            path = WindowsHWPWorker().convert(hwpx_path, out / "exam.hwp")
        except HWPWorkerUnavailable as exc:
            raise HTTPException(503, str(exc))
    else:
        raise HTTPException(400, f"unsupported format {req.format}")
    audit(request, ctx, "document.export", "document", doc_id,
          {"format": fmt, "output_mode": mode, "version": doc.version})
    return {"file": path.name, "url": f"/api/documents/{doc_id}/files/{path.name}"}


@router.get("/{doc_id}/files/{name}")
def download(
    doc_id: str,
    name: str,
    request: Request,
    access=Depends(doc_access("download")),
    store: Store = Depends(get_store),
):
    """Artifact binary download — reviewers are denied by ROLE_ACTIONS."""
    ctx, doc = access
    safe = sanitize_filename(name)
    base = store.export_dir(doc_id)
    path = (base / safe).resolve()
    if base.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "file not found")
    audit(request, ctx, "document.download", "document", doc_id, {"file": safe})
    return FileResponse(path, filename=safe)
