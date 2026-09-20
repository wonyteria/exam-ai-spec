"""Human review package (RESTORE-03).

Builds the per-question/per-page evidence bundle the review UI needs:
source crop (with hash), source anchor + transform chain, candidate
statuses, page role and uncertainty regions. Nothing here decides truth —
it packages evidence for a reviewer.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from document.models import Document, Page, Question, VerificationStatus


def build_review_package(
    doc: Document,
    workdir: Optional[Path] = None,
    resolve_uri=None,
) -> dict:
    """Assemble the review payload. `resolve_uri` maps stored URIs to local
    paths (PipelineContext.resolve_uri); without it, plain paths are used."""
    resolve = resolve_uri or (lambda u: Path(u))
    crop_dir = workdir / "review_crops" if workdir else None
    if crop_dir:
        crop_dir.mkdir(parents=True, exist_ok=True)

    pages = [_page_entry(p) for p in doc.pages]
    questions = [
        _question_entry(q, doc, resolve, crop_dir) for q in doc.questions
    ]
    pending = [
        q["id"]
        for q in questions
        if q["unverified"] or q["conflicts"] or q["unreadable"]
    ]
    return {
        "document_id": doc.id,
        "page_count": len(doc.pages),
        "pages": pages,
        "questions": questions,
        "review": {
            "question_count": len(questions),
            "pending_count": len(pending),
            "pending_question_ids": pending,
            "pages_with_errors": [
                p["index"] for p in pages if p["processing_error"]
            ],
            "uncertain_region_count": sum(p["uncertain_regions"] for p in pages),
        },
    }


def _page_entry(page: Page) -> dict:
    inv = page.inventory
    return {
        "index": page.index,
        "page_role": page.page_role,
        "role_source": page.role_source,
        "image_only": inv.image_only if inv else None,
        "text_chars": inv.text_chars if inv else None,
        "uncertain_regions": len(page.uncertain_regions or []),
        "processing_error": page.processing_error,
        "transform_kinds": [s.kind for s in page.transform_chain],
    }


def _question_entry(q: Question, doc, resolve, crop_dir) -> dict:
    anchor = q.source_anchor
    entry = {
        "id": q.id,
        "number": q.number,
        "label": q.label,
        "status": q.verification.status.value,
        "unverified": sum(
            1 for a in q.atus if a.status == VerificationStatus.UNVERIFIED
        ),
        "conflicts": sum(
            1 for a in q.atus if a.status == VerificationStatus.CONFLICT
        ),
        "unreadable": sum(
            1 for a in q.atus if a.status == VerificationStatus.UNREADABLE
        ),
        "atu_count": len(q.atus),
        "anchor": anchor.model_dump() if anchor else None,
    }
    crop = _crop_source(q, doc, resolve, crop_dir)
    if crop:
        entry["crop"] = crop
    return entry


def _crop_source(q: Question, doc, resolve, crop_dir) -> Optional[dict]:
    """Crop the question's source region from the page raster and bind the
    crop to its hash — reviewers compare against the source, not a guess."""
    if not crop_dir or not q.source or not q.source.bbox:
        return None
    if q.source.page >= len(doc.pages):
        return None
    page = doc.pages[q.source.page]
    raster_uri = page.original.variants.get("raster") or page.original.uri
    raster = resolve(raster_uri)
    if not raster.exists() or raster.suffix.lower() == ".pdf":
        return None
    from PIL import Image

    b = q.source.bbox
    with Image.open(raster) as im:
        im = im.convert("RGB")
        crop = im.crop((int(b.x), int(b.y), int(b.x + b.w), int(b.y + b.h)))
        out = crop_dir / f"{q.id}.png"
        crop.save(out)
    return {
        "uri": str(out),
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "bbox_px": {"x": b.x, "y": b.y, "w": b.w, "h": b.h},
    }
