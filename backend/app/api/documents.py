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


def _require_verified_final(doc) -> None:
    """Reject legacy binary export until the zero-typo gate is proven.

    The v1 artifact API is the canonical final-download path.  This guard is
    intentionally duplicated on the legacy routes so an older client cannot
    turn a review draft into a downloadable exam by accident.
    """
    gate = doc.verification.gate or {}
    if (
        doc.verification.status != "VERIFIED_FINAL"
        or gate.get("artifact_proof") != "PASS"
        or gate.get("document_empty") is True
        or any(
            value not in (0, False, [], {})
            for key, value in gate.items()
            if key not in {"missing_numbers", "manifest_mismatches", "lineage", "artifact_proof", "document_empty"}
        )
        or gate.get("missing_numbers")
        or gate.get("manifest_mismatches")
    ):
        raise HTTPException(
            422,
            "document is not VERIFIED_FINAL; review and hash-bound artifact proof are required",
        )


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


# --- question-centric restoration API ---------------------------------------


def _find_question(doc, qid: str):
    """Resolve by id first, then label, then printed number — same
    precedence as the canonical service."""
    for q in doc.questions:
        if q.id == qid:
            return q
    matches = [
        q for q in doc.questions
        if (q.label or "") == qid or str(q.number) == qid
    ]
    if len(matches) > 1:
        raise HTTPException(
            409, f"question {qid!r} is ambiguous — use the question id"
        )
    if not matches:
        raise HTTPException(404, "question not found")
    return matches[0]


def _question_payload(doc, q, doc_id: str) -> dict:
    crop = None
    if q.source and q.source.bbox:
        b = q.source.bbox
        crop = (
            f"/api/documents/{doc_id}/crops/{q.source.page}"
            f"?x={b.x}&y={b.y}&w={b.w}&h={b.h}"
        )
    return {
        "id": q.id,
        "number": q.number,
        "label": q.label or str(q.number),
        "type": q.type.value if q.type else None,
        "points": q.points,
        "body": [s.text for s in q.body],
        "choices": [
            {"label": c.label,
             "body": [s.text for s in c.body]}
            for c in q.choices
        ],
        "equations": [
            {"id": e.id, "latex": e.latex} for e in q.equations
        ],
        "figures": [
            {"id": f.id, "labels": f.labels,
             "description": f.topology.get("description")}
            for f in q.figures
        ],
        "answer": q.answer.value if q.answer else None,
        "status": q.restoration.status.value,
        "confidence": q.restoration.confidence,
        "issues": [i.model_dump() for i in q.restoration.issues],
        "corrections": [c.model_dump() for c in q.restoration.corrections],
        "atus": [
            {
                "id": a.id,
                "kind": a.kind.value,
                "field": a.field,
                "status": a.status.value,
                "value": a.value,
                "candidates": [
                    {"provider": c.provider, "value": c.value,
                     "confidence": c.confidence}
                    for c in a.candidates
                ],
            }
            for a in q.atus
        ],
        "logic_flags": [f.model_dump() for f in q.verification.logic_flags],
        "crop": crop,
        "crop_clean": (crop + "&source=clean") if crop else None,
    }


@router.get("/{doc_id}/restoration")
def restoration_summary(access=Depends(doc_access("read"))):
    """문항 단위 복원 요약 — 문제가 있는 문항만 나열한다 (내부 로그는
    절대 노출하지 않음)."""
    from document.models import QuestionStatus
    from document.restoration import refresh_document_status, status_counts

    _, doc = _read_document(access)
    status = refresh_document_status(doc)
    problem = [
        q for q in doc.questions
        if q.restoration.status
        in (QuestionStatus.NEEDS_USER_REVIEW, QuestionStatus.BLOCKED)
    ]
    return {
        "restoration_status": status,
        "final_status": doc.verification.status,
        "counts": status_counts(doc),
        "review_questions": [
            {
                "id": q.id,
                "number": q.number,
                "label": q.label or str(q.number),
                "status": q.restoration.status.value,
                "issues": [i.model_dump() for i in q.restoration.issues],
                "crop": _question_payload(doc, q, doc.id)["crop"],
            }
            for q in problem
        ],
    }


@router.get("/{doc_id}/questions/{qid}")
def question_detail(qid: str, access=Depends(doc_access("read"))):
    _, doc = _read_document(access)
    return _question_payload(doc, _find_question(doc, qid), doc.id)


class QuestionEditRequest(BaseModel):
    instruction: str
    apply: bool = False


def _rewrite_body(question, hint: str):
    """문장 정리류 지시는 로컬 모델로 새 본문을 생성 — 외부 API는 절대
    호출하지 않고, provider가 없으면 recognized=False로 돌려보낸다."""
    from jobs.runner import default_providers

    planner = next(
        (p for p in default_providers().reasoning if hasattr(p, "complete")),
        None,
    )
    if planner is None:
        return None
    body = " ".join(s.text for s in question.body)
    cand = planner.complete(
        "다음 시험 문항 본문을 자연스럽게 정리하세요. "
        "숫자·수식·의미는 바꾸지 말고 문장만 다듬으세요. "
        "수정된 본문만 출력하세요.\n"
        f"사용자 지시: {hint}\n본문: {body}",
        context={"label": question.label, "type": str(question.type)},
    )
    reply = (cand.value or {}).get("reply") if cand else None
    reply = str(reply or "").strip()
    return reply or None


def _preview_ops(doc, qid: str, ops):
    """Apply ops to a deep copy — validates the plan AND produces the
    after-state for the diff view, without touching the document."""
    from canonical.service import MutationService
    from document.models import Document

    service = MutationService(store=None, tenancy=None)  # type: ignore[arg-type]
    copy_doc = Document.model_validate(doc.model_dump())
    service._apply_ops(copy_doc, ops)
    return _find_question(copy_doc, qid)


@router.post("/{doc_id}/questions/{qid}/edit")
def question_edit(
    doc_id: str,
    qid: str,
    req: QuestionEditRequest,
    request: Request,
    access=Depends(doc_access("edit")),
    store: Store = Depends(get_store),
):
    """자연어 지시 → 구조화 op → 검증 → 미리보기(또는 적용) → 해당 문항만
    재검증 → 감사 로그. 모호한 지시는 문서 전체에 추측 적용하지 않는다."""
    from agent.question_ops import parse_question_edit
    from canonical.models import ChangeOp
    from canonical.store import (
        ConflictError, NotFoundError, PreconditionError, ValidationError,
    )
    from document.models import QuestionStatus
    from document.restoration import (
        refresh_document_status,
        refresh_question_status,
    )

    ctx, doc = _read_document(access)
    question = _find_question(doc, qid)
    plan = parse_question_edit(question, req.instruction)

    ops = plan.ops
    if plan.recognized and plan.rewrite:
        new_body = _rewrite_body(question, plan.rewrite["hint"])
        if not new_body:
            return {
                "ok": False,
                "recognized": False,
                "explanation": "본문 정리를 위한 로컬 모델이 없습니다.",
                "needs_clarification": True,
            }
        ops = [ChangeOp(op="SetBody", target_id=question.id,
                        value=new_body)]
        plan.explanation = "본문을 자연스럽게 정리했습니다."
    if not plan.recognized or not ops:
        return {
            "ok": False,
            "recognized": plan.recognized,
            "explanation": plan.explanation or "해석할 수 없는 지시입니다.",
            "needs_clarification": plan.needs_clarification,
        }

    before = _question_payload(doc, question, doc_id)
    try:
        after_q = _preview_ops(doc, question.id, ops)
    except (ConflictError, NotFoundError, PreconditionError,
            ValidationError) as exc:
        raise HTTPException(409, str(exc))
    after = _question_payload(doc, after_q, doc_id)

    if not req.apply:
        return {
            "ok": True,
            "recognized": True,
            "explanation": plan.explanation,
            "ops": [{"op": o.op, "target": o.target_id,
                     "field": o.field, "value": o.value} for o in ops],
            "preview": {"before": before, "after": after},
            "applied": False,
        }

    service, head = _canonical_for(doc_id)
    if service is not None and head is not None:
        try:
            rev = service.apply(
                ctx.tenant_id, ctx.user_id, doc_id, head.id, ops,
                route="question.edit",
            )
        except (ConflictError, NotFoundError, PreconditionError,
                ValidationError) as exc:
            raise HTTPException(409, str(exc))
        audit(request, ctx, "document.question.edit", "document", doc_id,
              {"question": qid, "instruction": req.instruction,
               "revision_id": rev.id})
        return {
            "ok": True, "recognized": True, "applied": True,
            "explanation": plan.explanation,
            "revision_id": rev.id,
            "preview": {"before": before, "after": after},
        }
    # Legacy flat-document path.
    for op in ops:
        try:
            _preview_ops(doc, question.id, [op])  # validate first
        except (ConflictError, NotFoundError, PreconditionError,
                ValidationError) as exc:
            raise HTTPException(409, str(exc))
    _apply_flat(doc, question.id, ops)
    if question.restoration.status != QuestionStatus.USER_CONFIRMED:
        question.restoration.status = QuestionStatus.USER_EDITED
    refresh_question_status(question)
    refresh_document_status(doc)
    doc.version += 1
    store.save_document(doc)
    audit(request, ctx, "document.question.edit", "document", doc_id,
          {"question": qid, "instruction": req.instruction,
           "version": doc.version})
    return {
        "ok": True, "recognized": True, "applied": True,
        "explanation": plan.explanation,
        "preview": {"before": before,
                    "after": _question_payload(doc, question, doc_id)},
    }


def _apply_flat(doc, qid: str, ops) -> None:
    from canonical.service import MutationService

    MutationService(store=None, tenancy=None)._apply_ops(  # type: ignore[arg-type]
        doc, ops
    )


@router.post("/{doc_id}/questions/{qid}/confirm")
def question_confirm(
    doc_id: str,
    qid: str,
    request: Request,
    access=Depends(doc_access("edit")),
    store: Store = Depends(get_store),
):
    """사용자 확정 — USER_CONFIRMED. Canonical 경로는 SetQuestionStatus op."""
    from canonical.models import ChangeOp
    from canonical.store import (
        ConflictError, NotFoundError, PreconditionError, ValidationError,
    )
    from document.models import QuestionStatus
    from document.restoration import refresh_document_status

    ctx, doc = _read_document(access)
    question = _find_question(doc, qid)
    service, head = _canonical_for(doc_id)
    if service is not None and head is not None:
        try:
            rev = service.apply(
                ctx.tenant_id, ctx.user_id, doc_id, head.id,
                [ChangeOp(
                    op="SetQuestionStatus", target_id=question.id,
                    value=QuestionStatus.USER_CONFIRMED.value)],
                route="question.confirm",
            )
        except (ConflictError, NotFoundError, PreconditionError,
                ValidationError) as exc:
            raise HTTPException(409, str(exc))
        audit(request, ctx, "document.question.confirm", "document", doc_id,
              {"question": qid, "revision_id": rev.id})
        return {"ok": True, "status": QuestionStatus.USER_CONFIRMED.value}
    question.restoration.status = QuestionStatus.USER_CONFIRMED
    refresh_document_status(doc)
    doc.version += 1
    store.save_document(doc)
    audit(request, ctx, "document.question.confirm", "document", doc_id,
          {"question": qid, "version": doc.version})
    return {"ok": True, "status": QuestionStatus.USER_CONFIRMED.value}


def _require_restored(doc) -> str:
    """Best-effort download gate: the pipeline must have produced a
    restoration status. Unlike _require_verified_final this never blocks
    on open review items — the count is reported, not hidden."""
    from document.restoration import refresh_document_status

    status = refresh_document_status(doc)
    if status == "IN_PROGRESS" or not doc.questions:
        raise HTTPException(422, "복원 결과가 아직 없습니다")
    return status


@router.post("/{doc_id}/restoration/export")
def restoration_export(
    doc_id: str,
    req: ExportRequest,
    request: Request,
    access=Depends(doc_access("export")),
    store: Store = Depends(get_store),
):
    """Best-effort export — downloadable even with review-needed items;
    never marked VERIFIED_FINAL."""
    import json

    from document.restoration import status_counts
    from renderers.plan import OUTPUT_MODES

    ctx, doc = _read_document(access)
    status = _require_restored(doc)
    fmt = req.format.lower()
    mode = req.output_mode
    if mode not in OUTPUT_MODES:
        raise HTTPException(400, f"unsupported output_mode {mode}")
    out = store.export_dir(doc_id)
    if fmt == "json":
        path = out / "exam.best-effort.json"
        path.write_text(
            json.dumps(doc.model_dump(mode="json"),
                       ensure_ascii=False, indent=2)
        )
    elif fmt == "hwpx":
        path = out / "exam.best-effort.hwpx"
        path.write_bytes(
            render_hwpx(doc, output_mode=mode, brand_id=req.brand_id))
    elif fmt == "docx":
        from renderers.docx.renderer import render_docx

        path = out / "exam.best-effort.docx"
        path.write_bytes(
            render_docx(doc, output_mode=mode, brand_id=req.brand_id))
    elif fmt == "pdf":
        path = out / "exam.best-effort.pdf"
        path.write_bytes(render_pdf(doc, output_mode=mode))
    else:
        raise HTTPException(400, f"unsupported format {req.format}")
    counts = status_counts(doc)
    audit(request, ctx, "document.restoration.export", "document", doc_id,
          {"format": fmt, "status": status,
           "needs_review": counts.get("NEEDS_USER_REVIEW", 0)})
    return {
        "file": path.name,
        "url": f"/api/documents/{doc_id}/restoration/files/{path.name}",
        "restoration_status": status,
        "counts": counts,
        "final": False,
    }


@router.get("/{doc_id}/restoration/files/{name}")
def restoration_download(
    doc_id: str,
    name: str,
    request: Request,
    access=Depends(doc_access("download")),
    store: Store = Depends(get_store),
):
    ctx, doc = _read_document(access)
    status = _require_restored(doc)
    safe = sanitize_filename(name)
    base = store.export_dir(doc_id)
    path = (base / safe).resolve()
    if base.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "file not found")
    audit(request, ctx, "document.restoration.download", "document",
          doc_id, {"file": safe, "status": status})
    return FileResponse(
        path, filename=safe,
        headers={"X-Restoration-Status": status, "X-Best-Effort": "true"},
    )


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
    _require_verified_final(doc)
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
    elif fmt == "docx":
        from renderers.docx.renderer import render_docx

        path = out / "exam.docx"
        path.write_bytes(
            render_docx(doc, output_mode=mode, brand_id=req.brand_id)
        )
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
    ctx, doc = _read_document(access)
    _require_verified_final(doc)
    safe = sanitize_filename(name)
    base = store.export_dir(doc_id)
    path = (base / safe).resolve()
    if base.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "file not found")
    audit(request, ctx, "document.download", "document", doc_id, {"file": safe})
    return FileResponse(path, filename=safe)
