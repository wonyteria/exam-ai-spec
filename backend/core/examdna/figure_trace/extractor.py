"""Pixel → FigureScene extractor (RESTORE-14).

Pipeline: binarize → Hough segments → endpoint dedup into point nodes →
Hough circles → measured relations (intersection, parallel,
perpendicular, equal_length). Everything emitted is a candidate scene —
`validate_scene`/`check_scene` still gate it downstream, and the
extractor reports extraction confidence honestly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from document.scene import (
    FigureScene,
    ScenePrimitive,
    SceneRelation,
)

_MIN_SEG_LEN = 20          # px — shorter strokes are glyph fragments
_POINT_MERGE_R = 8         # px — endpoints closer than this share a node
_PARALLEL_TOL_DEG = 3.0
_PERP_TOL_DEG = 3.0
_EQUAL_LEN_FRAC = 0.04
_MAX_SEGMENTS = 60         # cap before scene's own MAX_PRIMITIVES
_MAX_CIRCLES = 10


@dataclass
class ExtractionResult:
    scene: FigureScene
    confidence: float          # fraction of ink explained by primitives
    unexplained_ink: int       # ink pixels not covered by any primitive


def extract_scene(gray: np.ndarray) -> ExtractionResult:
    """Extract a candidate FigureScene from a figure-region raster."""
    import cv2

    if gray is None or gray.size == 0:
        return ExtractionResult(FigureScene(), 0.0, 0)
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    total_ink = int(np.count_nonzero(ink))

    segments = _segments(ink)
    circles = _circles(gray)

    primitives: list[ScenePrimitive] = []
    relations: list[SceneRelation] = []
    points: list[list[float]] = []          # [[x, y]] — node table
    seg_ids: list[str] = []
    seg_geom: list[tuple] = []              # (p1idx, p2idx, angle, length)

    def node(x: float, y: float) -> int:
        for i, (px, py) in enumerate(points):
            if (px - x) ** 2 + (py - y) ** 2 <= _POINT_MERGE_R ** 2:
                return i
        points.append([float(x), float(y)])
        primitives.append(
            ScenePrimitive(
                id=f"p{len(points) - 1}", kind="point",
                props={"x": float(x), "y": float(y)},
            )
        )
        return len(points) - 1

    for (x1, y1, x2, y2) in segments[:_MAX_SEGMENTS]:
        i1, i2 = node(x1, y1), node(x2, y2)
        if i1 == i2:
            continue
        sid = f"s{len(seg_ids)}"
        seg_ids.append(sid)
        length = float(np.hypot(x2 - x1, y2 - y1))
        angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180
        seg_geom.append((i1, i2, angle, length))
        primitives.append(
            ScenePrimitive(
                id=sid, kind="segment",
                refs=[f"p{i1}", f"p{i2}"],
                props={"length": length, "angle_deg": angle},
            )
        )

    for (cx, cy, r) in circles[:_MAX_CIRCLES]:
        ci = node(cx, cy)
        cid = f"c{len([p for p in primitives if p.kind == 'circle'])}"
        primitives.append(
            ScenePrimitive(
                id=cid, kind="circle", refs=[f"p{ci}"],
                props={"radius": float(r)},
            )
        )

    relations.extend(_segment_relations(seg_ids, seg_geom))
    covered = _covered_ink(ink, segments, circles)
    confidence = covered / total_ink if total_ink else 0.0
    return ExtractionResult(
        FigureScene(primitives=primitives, relations=relations),
        confidence=confidence,
        unexplained_ink=total_ink - covered,
    )


def _segments(ink: np.ndarray) -> list[tuple[int, int, int, int]]:
    import cv2

    lines = cv2.HoughLinesP(
        ink, rho=1, theta=np.pi / 180, threshold=30,
        minLineLength=_MIN_SEG_LEN, maxLineGap=4,
    )
    if lines is None:
        return []
    out = []
    for ln in lines[:, 0, :]:
        x1, y1, x2, y2 = (int(v) for v in ln)
        if np.hypot(x2 - x1, y2 - y1) >= _MIN_SEG_LEN:
            out.append((x1, y1, x2, y2))
    # dedupe near-parallel overlapping Hough hits
    kept: list[tuple] = []
    for seg in sorted(
        out, key=lambda s: -np.hypot(s[2] - s[0], s[3] - s[1])
    ):
        if not any(_same_line(seg, k) for k in kept):
            kept.append(seg)
    return kept


def _same_line(a, b) -> bool:
    """Two segments covering the same geometric line — midpoint distance
    plus angle agreement."""
    ang_a = np.degrees(np.arctan2(a[3] - a[1], a[2] - a[0])) % 180
    ang_b = np.degrees(np.arctan2(b[3] - b[1], b[2] - b[0])) % 180
    d_ang = abs(ang_a - ang_b)
    d_ang = min(d_ang, 180 - d_ang)
    if d_ang > 3:
        return False
    mid_a = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2)
    mid_b = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    return np.hypot(mid_a[0] - mid_b[0], mid_a[1] - mid_b[1]) < 12


def _circles(gray: np.ndarray) -> list[tuple[float, float, float]]:
    import cv2

    try:
        found = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=20,
            param1=120, param2=30, minRadius=8, maxRadius=min(gray.shape) // 3,
        )
    except cv2.error:
        return []
    if found is None:
        return []
    return [(float(c[0]), float(c[1]), float(c[2])) for c in found[0]]


def _segment_relations(
    seg_ids: list[str], seg_geom: list[tuple]
) -> list[SceneRelation]:
    relations: list[SceneRelation] = []
    for i in range(len(seg_geom)):
        for j in range(i + 1, len(seg_geom)):
            p1a, p2a, ang_a, len_a = seg_geom[i]
            p1b, p2b, ang_b, len_b = seg_geom[j]
            d_ang = abs(ang_a - ang_b)
            d_ang = min(d_ang, 180 - d_ang)
            shared = {p1a, p2a} & {p1b, p2b}
            if shared:
                relations.append(
                    SceneRelation(
                        kind="intersection",
                        refs=[seg_ids[i], seg_ids[j], f"p{shared.pop()}"],
                    )
                )
            if d_ang <= _PARALLEL_TOL_DEG and not shared:
                relations.append(
                    SceneRelation(
                        kind="parallel", refs=[seg_ids[i], seg_ids[j]]
                    )
                )
            elif abs(d_ang - 90) <= _PERP_TOL_DEG:
                relations.append(
                    SceneRelation(
                        kind="perpendicular",
                        refs=[seg_ids[i], seg_ids[j]],
                    )
                )
            if abs(len_a - len_b) <= _EQUAL_LEN_FRAC * max(len_a, len_b):
                relations.append(
                    SceneRelation(
                        kind="equal_length", refs=[seg_ids[i], seg_ids[j]]
                    )
                )
    return relations


def _covered_ink(
    ink: np.ndarray,
    segments: list[tuple],
    circles: list[tuple],
) -> int:
    """Ink pixels explained by the extracted primitives (drawn over a
    blank canvas with a 3px stroke tolerance)."""
    import cv2

    canvas = np.zeros_like(ink)
    for x1, y1, x2, y2 in segments:
        cv2.line(canvas, (x1, y1), (x2, y2), 255, 3)
    for cx, cy, r in circles:
        cv2.circle(canvas, (int(cx), int(cy)), int(r), 255, 3)
    return int(np.count_nonzero(ink & canvas.astype(bool)))
