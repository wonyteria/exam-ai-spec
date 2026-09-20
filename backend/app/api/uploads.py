from __future__ import annotations

import hashlib
import io
import re
import threading

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from PIL import Image

from canonical.models import JobV2, SourceAsset, SourceManifest, SourcePage
from canonical.store import CanonicalStore
from canonical.service import MutationService
from document.models import Document, Page, PageImage
from document.page_roles import extract_pdf_page_text, suggest_page_role
from jobs.store import Store
from jobs.worker import run_once
from storage.local import LocalObjectStore, sanitize_filename
from tenancy.auth import AuthContext, audit, require_action
from tenancy.db import TenancyDB
from tenancy.limits import QuotaExceeded, TenantLimiter

from ..deps import get_canonical, get_object_store, get_store, get_tenancy

router = APIRouter(prefix="/api", tags=["uploads"])

_LIMITER = TenantLimiter()


def get_limiter() -> TenantLimiter:
    return _LIMITER

MAX_FILE_BYTES = 50 * 1024 * 1024  # ADR baseline: 50 MiB per file
MAX_FILES = 50
MAX_PIXELS = 80_000_000  # decompression-bomb guard (~80MP per page)
MAX_PDF_PAGES = 100
PDF_RENDER_SCALE = 200 / 72  # 200 dpi rasterization baseline

Image.MAX_IMAGE_PIXELS = None  # we enforce our own explicit cap


def _sniff_mime(data: bytes, filename: str) -> str:
    """Magic-byte sniffing — the declared Content-Type and extension are
    untrusted. Returns a canonical mime or raises 422."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    raise HTTPException(
        422,
        {
            "error": {
                "code": "UNSUPPORTED_TYPE",
                "message": f"unsupported or unrecognized file type: {filename}",
                "details": {},
                "retryable": False,
            }
        },
    )


def _validate_image(data: bytes, filename: str) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
    except Exception:
        raise HTTPException(
            422,
            {
                "error": {
                    "code": "CORRUPT_FILE",
                    "message": f"image file is corrupt or unreadable: {filename}",
                    "details": {},
                    "retryable": True,
                }
            },
        )
    if w * h > MAX_PIXELS:
        raise HTTPException(
            422,
            {
                "error": {
                    "code": "IMAGE_TOO_LARGE",
                    "message": f"image exceeds {MAX_PIXELS // 1_000_000}MP: {filename} ({w}x{h})",
                    "details": {"width": w, "height": h},
                    "retryable": False,
                }
            },
        )
    return w, h


def _pdf_page_count(data: bytes, filename: str) -> int:
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        try:
            n = len(pdf)
        finally:
            pdf.close()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            422,
            {
                "error": {
                    "code": "CORRUPT_FILE",
                    "message": f"PDF is corrupt or unreadable: {filename}",
                    "details": {},
                    "retryable": True,
                }
            },
        )
    if n == 0 or n > MAX_PDF_PAGES:
        raise HTTPException(
            422,
            {
                "error": {
                    "code": "PDF_PAGE_LIMIT",
                    "message": f"PDF has {n} pages (limit {MAX_PDF_PAGES}): {filename}",
                    "details": {"pages": n},
                    "retryable": False,
                }
            },
        )
    return n


def _natural_key(name: str) -> list:
    """Filename ordering key: page1/page2/page10 sorts numerically."""
    return [
        int(t) if t.isdigit() else t.lower()
        for t in re.split(r"(\d+)", name)
    ]


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
    # WP10: per-tenant rate limit — exceeded requests are rejected as
    # 429 before any byte is stored.
    try:
        get_limiter().check_rate(ctx.tenant_id)
    except QuotaExceeded as exc:
        raise HTTPException(
            429, {"error": {"code": "RATE_LIMITED", "message": exc.detail,
                            "retryable": True}},
        )
    doc = Document(tenant_id=ctx.tenant_id)

    # 1) Validate everything before storing anything — a bad file fails the
    #    whole request rather than leaving a half-registered document.
    staged: list[dict] = []
    for i, f in enumerate(files):
        data = await f.read()
        original_name = f.filename or f"file{i + 1}"
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(
                413,
                {
                    "error": {
                        "code": "FILE_TOO_LARGE",
                        "message": f"file too large: {original_name}",
                        "details": {"limit": MAX_FILE_BYTES},
                        "retryable": False,
                    }
                },
            )
        mime = _sniff_mime(data, original_name)
        entry: dict = {
            "data": data,
            "original_name": original_name,
            "safe_name": sanitize_filename(original_name),
            "mime": mime,
            "sha256": hashlib.sha256(data).hexdigest(),
            "upload_index": i,
            "pdf_pages": 0,
            "width": None,
            "height": None,
        }
        if mime == "application/pdf":
            entry["pdf_pages"] = _pdf_page_count(data, original_name)
        else:
            entry["width"], entry["height"] = _validate_image(data, original_name)
        staged.append(entry)

    # 2) Initial page order: natural sort on the original name
    #    (page1, page2, page10), stable by upload order for ties.
    staged.sort(key=lambda e: (_natural_key(e["safe_name"]), e["upload_index"]))

    # 3) Create the canonical document row first — source_pages references
    #    it via foreign key.
    cstore.create_document(ctx.tenant_id, created_by=ctx.user_id, doc_id=doc.id)

    # 4) Store blobs + register assets/pages. Originals are immutable
    #    content-addressed blobs; identical bytes reuse the same asset.
    source_pages: list[SourcePage] = []
    for entry in staged:
        # Content-addressed dedup: identical bytes for this tenant reuse
        # the existing asset (and its blob) instead of double-storing.
        asset = cstore.find_source_asset(ctx.tenant_id, entry["sha256"])
        if asset is None:
            blob_key = (
                f"uploads/{ctx.tenant_id}/{doc.id}/"
                f"{entry['upload_index']:03d}_{entry['safe_name']}"
            )
            uri = objects.put(blob_key, entry["data"])
            asset = cstore.put_source_asset(
                SourceAsset(
                    tenant_id=ctx.tenant_id,
                    sha256=entry["sha256"],
                    mime=entry["mime"],
                    byte_size=len(entry["data"]),
                    original_name=entry["original_name"],
                    blob_key=blob_key,
                )
            )
        entry["asset"] = asset
        entry["uri"] = f"local://{asset.blob_key}"

        if entry["mime"] == "application/pdf":
            for p in range(entry["pdf_pages"]):
                # AT-061: classify the page role up front — an answer/score
                # sheet must surface in the manifest, never silently become
                # a question page. Scans without a text layer stay UNKNOWN
                # until the user confirms a role.
                role, _ev = suggest_page_role(
                    extract_pdf_page_text(entry["data"], p),
                    p,
                    entry["pdf_pages"],
                )
                source_pages.append(
                    SourcePage(
                        tenant_id=ctx.tenant_id,
                        document_id=doc.id,
                        asset_id=asset.id,
                        pdf_page_index=p,
                        original_sha256=entry["sha256"],
                        original_name=entry["original_name"],
                        upload_index=entry["upload_index"],
                        page_role=role,
                        role_source="AUTO",
                    )
                )
        else:
            source_pages.append(
                SourcePage(
                    tenant_id=ctx.tenant_id,
                    document_id=doc.id,
                    asset_id=asset.id,
                    width_px=entry["width"],
                    height_px=entry["height"],
                    original_sha256=entry["sha256"],
                    original_name=entry["original_name"],
                    upload_index=entry["upload_index"],
                )
            )

    for sp in source_pages:
        cstore.put_source_page(sp)

    # 4) The manifest records the initial (unconfirmed) page order; a later
    #    confirm/reorder creates a new manifest + revision.
    manifest = cstore.create_manifest(
        SourceManifest(
            tenant_id=ctx.tenant_id,
            document_id=doc.id,
            page_ids_ordered=[p.id for p in source_pages],
        )
    )

    # 5) Document pages mirror the manifest order with source linkage.
    entry_by_asset = {e["asset"].id: e for e in staged}
    for i, sp in enumerate(source_pages):
        entry = entry_by_asset[sp.asset_id]
        doc.pages.append(
            Page(
                index=i,
                original=PageImage(uri=entry["uri"]),
                source_asset_id=sp.asset_id,
                source_page_id=sp.id,
                pdf_page_index=sp.pdf_page_index,
                sha256=sp.original_sha256,
                original_name=sp.original_name,
                width=float(sp.width_px) if sp.width_px else None,
                height=float(sp.height_px) if sp.height_px else None,
                page_role=sp.page_role,
                role_source=sp.role_source,
            )
        )

    store.save_document(doc)

    # WP10: charge the tenant byte budget for accepted source bytes.
    try:
        get_limiter().charge_bytes(
            ctx.tenant_id, sum(len(e["data"]) for e in staged)
        )
    except QuotaExceeded as exc:
        raise HTTPException(
            429, {"error": {"code": "BUDGET_EXCEEDED",
                            "message": exc.detail, "retryable": False}},
        )

    # Canonical record + first revision (bound to the manifest) + durable job.
    service = MutationService(cstore, tenancy)
    service.create_revision(doc, ctx.tenant_id, ctx.user_id, manifest_id=manifest.id)
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
        {
            "files": len(files),
            "pages": len(source_pages),
            "manifest_id": manifest.id,
            "job_id": job.id,
        },
    )
    threading.Thread(
        target=run_once,
        args=(cstore, store, objects, tenancy, "api-worker"),
        daemon=True,
    ).start()
    return {"job_id": job.id, "document_id": doc.id, "manifest_id": manifest.id}
