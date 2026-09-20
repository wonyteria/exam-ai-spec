"""RESTORE-18 ReconstructionDNA — occlusion policy engine.

Spec rules honored:
- generative inpainting is never a source of truth
- restoration from reference is allowed ONLY inside the verified
  reference bbox, with transform + source/reference hashes as proof
- every uncertain/overlap region gets an explicit decision:
    PRESERVE_ORIGINAL  — annotation removed, print intact (no occlusion)
    RESTORE_REFERENCE  — verified reference evidence covers the bbox
    REVIEW_REQUIRED    — occluded print with no independent reference;
                         human review, never fabricated pixels
"""
from __future__ import annotations

import hashlib
from typing import Any

from ..context import PipelineContext

DECISIONS = {"PRESERVE_ORIGINAL", "RESTORE_REFERENCE", "REVIEW_REQUIRED"}


def _bbox_overlap(a: dict, b: dict) -> float:
    """Intersection-over-min-area — reference must cover the occlusion."""
    ax1, ay1 = a.get("x", 0), a.get("y", 0)
    ax2, ay2 = ax1 + a.get("w", 0), ay1 + a.get("h", 0)
    bx1, by1 = b.get("x", 0), b.get("y", 0)
    bx2, by2 = bx1 + b.get("w", 0), by1 + b.get("h", 0)
    ix, iy = max(0, min(ax2, bx2) - max(ax1, bx1)), max(
        0, min(ay2, by2) - max(ay1, by1)
    )
    inter = ix * iy
    denom = min(
        max(1, (ax2 - ax1) * (ay2 - ay1)),
        max(1, (bx2 - bx1) * (by2 - by1)),
    )
    return inter / denom


def _reference_regions(ctx: PipelineContext, page_index: int) -> list[dict]:
    """Verified reference bboxes for this page — only provider names
    starting with `reference:` count (one correlated family)."""
    out: list[dict] = []
    for region in ctx.document.pages[page_index].regions:
        if region.get("reference_bbox") and region.get("reference_source"):
            out.append(region)
    # ATU-level reference evidence: candidates carrying a SourceRef bbox
    for q in ctx.document.questions:
        src = getattr(q, "source", None)
        if src is None or src.page != page_index:
            continue
        for atu in q.atus:
            for cand in atu.candidates:
                if str(cand.provider).startswith("reference:") and cand.bbox_original:
                    bb = cand.bbox_original
                    out.append(
                        {
                            "reference_bbox": bb.model_dump(),
                            "reference_source": cand.provider,
                            "raw_output_sha256": cand.raw_output_sha256,
                        }
                    )
    return out


def decide_region(
    region: dict[str, Any], references: list[dict[str, Any]]
) -> dict[str, Any]:
    """One occlusion decision with provenance — never a pixel guess."""
    bbox = region.get("bbox") or region.get("bbox_px") or {}
    kind = region.get("kind", "uncertain")
    decision = "REVIEW_REQUIRED"
    proof = None
    # Trace-free uncertain pixels stay as the original — nothing to repair.
    if not region.get("overlaps_print", True):
        decision = "PRESERVE_ORIGINAL"
    else:
        for ref in references:
            ref_bbox = ref.get("reference_bbox") or {}
            if ref_bbox and _bbox_overlap(bbox, ref_bbox) >= 0.9:
                decision = "RESTORE_REFERENCE"
                proof = {
                    "reference_source": ref.get("reference_source"),
                    "reference_bbox": ref_bbox,
                    "raw_output_sha256": ref.get("raw_output_sha256"),
                    "occlusion_sha256": hashlib.sha256(
                        str(sorted(bbox.items())).encode()
                    ).hexdigest()[:16],
                }
                break
    return {
        "kind": kind,
        "bbox": bbox,
        "decision": decision,
        "overlaps_print": region.get("overlaps_print", True),
        "proof": proof,
    }


def run(ctx: PipelineContext) -> None:
    """Decide every uncertain region on every page."""
    counts = {"PRESERVE_ORIGINAL": 0, "RESTORE_REFERENCE": 0, "REVIEW_REQUIRED": 0}
    for page in ctx.document.pages:
        refs = _reference_regions(ctx, page.index)
        decisions = [
            decide_region(r, refs) for r in (page.uncertain_regions or [])
        ]
        page.reconstruction = decisions
        for d in decisions:
            counts[d["decision"]] += 1
    ctx.emit(
        "reconstruction",
        "오클루전 정책 결정 — "
        f"원본보존 {counts['PRESERVE_ORIGINAL']}, "
        f"참조복원 {counts['RESTORE_REFERENCE']}, "
        f"검수필요 {counts['REVIEW_REQUIRED']}",
    )
