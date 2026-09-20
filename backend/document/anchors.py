"""Source anchors: map a working-pixel bbox back to source coordinates.

Every derived region/crop/candidate must be able to state where it came
from in the immutable source. The transform chain recorded during
preprocessing is replayed in reverse; unknown step kinds refuse to guess
— they mark the anchor `uninvertible` instead of emitting wrong
coordinates (RESTORE-01).
"""
from __future__ import annotations

from typing import Optional

from document.models import BBox, Page, SourceAnchor, TransformStep


def anchor_for(
    page: Page,
    bbox: BBox,
    source_sha256: str = "",
    crop_sha256: Optional[str] = None,
) -> SourceAnchor:
    """Build the provenance record for a region detected in working pixels.

    `source_bbox` is the bbox mapped back through the recorded transform
    chain (PDF raster scale → points, EXIF orientation → stored pixels).
    """
    source_bbox, invertible = invert_bbox(bbox, page.transform_chain)
    anchor = SourceAnchor(
        source_sha256=source_sha256,
        page_index=page.pdf_page_index if page.pdf_page_index is not None else page.index,
        bbox_px=bbox,
        source_bbox=source_bbox,
        transform_chain=list(page.transform_chain),
        crop_sha256=crop_sha256,
    )
    if not invertible:
        anchor.source_bbox = None
    return anchor


def invert_bbox(
    bbox: BBox, chain: list[TransformStep]
) -> tuple[Optional[BBox], bool]:
    """Replay the chain in reverse. Returns (source-space bbox, invertible)."""
    cur: Optional[BBox] = bbox
    for step in reversed(chain):
        if cur is None:
            break
        cur = _invert_step(cur, step)
    return cur, cur is not None


def _invert_step(b: BBox, step: TransformStep) -> Optional[BBox]:
    p = step.params
    if step.kind == "pdf_raster":
        scale = float(p.get("scale") or 0)
        if scale <= 0:
            return None
        return BBox(x=b.x / scale, y=b.y / scale, w=b.w / scale, h=b.h / scale)

    if step.kind == "exif_orientation":
        return _invert_exif(b, p)

    return None  # unknown step — refuse to guess


def _invert_exif(b: BBox, p: dict) -> Optional[BBox]:
    """Map a bbox in the *displayed* image back to stored pixels."""
    ori = int(p.get("exif_orientation") or 1)
    ow = float(p.get("original_width") or 0)
    oh = float(p.get("original_height") or 0)
    if ori == 1 or not ow or not oh:
        return b if ori == 1 else None
    # Displayed size: swapped for 90/270-degree orientations.
    dw = oh if ori in (5, 6, 7, 8) else ow
    dh = ow if ori in (5, 6, 7, 8) else oh
    if ori == 2:   # horizontal flip
        return BBox(x=ow - (b.x + b.w), y=b.y, w=b.w, h=b.h)
    if ori == 3:   # 180°
        return BBox(x=ow - (b.x + b.w), y=oh - (b.y + b.h), w=b.w, h=b.h)
    if ori == 4:   # vertical flip
        return BBox(x=b.x, y=oh - (b.y + b.h), w=b.w, h=b.h)
    if ori == 5:   # transpose (main diagonal)
        return BBox(x=b.y, y=b.x, w=b.h, h=b.w)
    if ori == 6:   # displayed = stored rotated 90° CW
        return BBox(x=b.y, y=dw - (b.x + b.w), w=b.h, h=b.w)
    if ori == 7:   # transverse (anti-diagonal)
        return BBox(x=dh - (b.y + b.h), y=dw - (b.x + b.w), w=b.h, h=b.w)
    if ori == 8:   # displayed = stored rotated 90° CCW
        return BBox(x=dh - (b.y + b.h), y=b.x, w=b.h, h=b.w)
    return None
