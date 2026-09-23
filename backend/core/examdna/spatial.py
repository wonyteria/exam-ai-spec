"""Inverse coordinate mapping: working-image space -> source space.

Every stage anchors evidence (question bboxes, review regions, figure
boxes) in working-pixel space. The working image is derived from the
source through recorded transform_chain steps (EXIF orientation,
resolution cap, PDF raster). This module walks the chain in reverse so a
bbox on a derived image can be expressed in source coordinates — for
review crops, audits, and future variant routing.

`deskewed` is the only variant in a different pixel space; pass
`from_variant="deskewed"` to unwrap that rotation first.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence


def _rotate_cv(x: float, y: float, cx: float, cy: float,
               angle_deg: float) -> tuple[float, float]:
    """Point transform matching cv2.getRotationMatrix2D(c, angle, 1)."""
    a = math.radians(angle_deg)
    al, be = math.cos(a), math.sin(a)
    tx = (1 - al) * cx - be * cy
    ty = be * cx + (1 - al) * cy
    return al * x + be * y + tx, -be * x + al * y + ty


def _exif_inverse(x: float, y: float, orientation: int,
                  orig_w: float, orig_h: float) -> tuple[float, float]:
    """Undo PIL ImageOps.exif_transpose for one orientation value.

    `orig_w`/`orig_h` are the pre-transpose source dimensions recorded in
    the transform params (swapped axes already accounted for)."""
    if orientation == 2:      # FLIP_LEFT_RIGHT
        return orig_w - 1 - x, y
    if orientation == 3:      # ROTATE_180
        return orig_w - 1 - x, orig_h - 1 - y
    if orientation == 4:      # FLIP_TOP_BOTTOM
        return x, orig_h - 1 - y
    if orientation == 5:      # TRANSPOSE — self-inverse
        return y, x
    if orientation == 6:      # ROTATE_270 (90 CW display)
        return y, orig_h - 1 - x
    if orientation == 7:      # TRANSVERSE — anti-diagonal flip
        return orig_w - 1 - y, orig_h - 1 - x
    if orientation == 8:      # ROTATE_90 (90 CCW display)
        return orig_w - 1 - y, x
    return x, y


def map_point_to_source(page, x: float, y: float,
                        from_variant: Optional[str] = None
                        ) -> tuple[float, float]:
    """Working/variant pixel -> source pixel (or PDF pt for raster pages).

    Steps are undone in reverse application order. Unknown kinds are
    skipped — a missing inverse never fabricates coordinates."""
    px, py = float(x), float(y)
    if from_variant == "deskewed":
        angle = _deskew_angle(page)
        if angle:
            px, py = _rotate_cv(
                px, py, page.width / 2, page.height / 2, -angle
            )
    for step in reversed(page.transform_chain):
        kind, p = step.kind, step.params or {}
        if kind == "normalize_scale":
            s = p.get("scale") or 1.0
            px, py = px / s, py / s
        elif kind == "exif_orientation":
            px, py = _exif_inverse(
                px, py, int(p.get("exif_orientation", 1)),
                float(p.get("original_width", page.width)),
                float(p.get("original_height", page.height)),
            )
        elif kind == "pdf_raster":
            s = p.get("scale") or 1.0
            px, py = px / s, py / s
    return px, py


def map_bbox_to_source(page, bbox: Sequence[float],
                       from_variant: Optional[str] = None
                       ) -> list[float]:
    """[x, y, w, h] working bbox -> source-space bounding box."""
    x, y, w, h = bbox
    corners = [
        map_point_to_source(page, x, y, from_variant),
        map_point_to_source(page, x + w, y, from_variant),
        map_point_to_source(page, x, y + h, from_variant),
        map_point_to_source(page, x + w, y + h, from_variant),
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def _deskew_angle(page) -> float:
    for step in page.transform_chain:
        if step.kind == "deskew":
            return float((step.params or {}).get("angle_deg") or 0.0)
    return 0.0
