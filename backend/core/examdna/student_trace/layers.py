"""LayerDNA per-pixel layer evidence (RESTORE-04 six-class → RESTORE-11 14-class).

Taxonomy (spec §11 LayerDNA minimum):

     0 BACKGROUND              paper — never stored as ink
     1 PRINT_TEXT              printed text — must be preserved
     2 PRINT_FIGURE            printed figure/graph lines — must be preserved
     3 GRADING_MARK            large colored grading marks (○/X/✓) — candidate
     4 BLACK_PEN               dark handwriting strokes — candidate
     5 PENCIL                  light/graphite strokes — candidate
     6 PRINT_WRITING_OVERLAP   print↔handwriting fusion — review only
     7 PRINT_GRADING_OVERLAP   print↔colored-ink fusion — review only
     8 BLUE_PEN                blue handwriting strokes — candidate
     9 RED_PEN                 red handwriting strokes — candidate
    10 HIGHLIGHTER             translucent colored marking — candidate
    11 PRINT_MATH              printed equation content — must be preserved
    12 PAPER_ARTIFACT          scan noise, stains, bleed-through — preserve
    13 UNKNOWN                 unclassifiable ink — review only

Backward compatibility: the six RESTORE-04 names (PRINT, GRADING, PEN,
OVERLAP) remain as enum aliases over the same numeric ids, so cached
masks and external consumers keep working.

Features (chroma, intensity, stroke morphology, neighborhood) feed the
classifier; they are never removal rules by themselves. A component is
removable only when its class is an annotation class, its confidence
clears the calibrated bar, and it does not touch print — everything else
stays in the source or is promoted to an overlap/unknown class for human
review. Classification is not deletion: PAPER_ARTIFACT and UNKNOWN are
preserved by policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
from PIL import Image, ImageFilter


class LayerClass(IntEnum):
    BACKGROUND = 0
    PRINT_TEXT = 1
    PRINT = 1                       # RESTORE-04 alias
    PRINT_FIGURE = 2
    GRADING_MARK = 3
    GRADING = 3                     # RESTORE-04 alias
    BLACK_PEN = 4
    PEN = 4                         # RESTORE-04 alias
    PENCIL = 5
    PRINT_WRITING_OVERLAP = 6
    OVERLAP = 6                     # RESTORE-04 alias
    PRINT_GRADING_OVERLAP = 7
    BLUE_PEN = 8
    RED_PEN = 9
    HIGHLIGHTER = 10
    PRINT_MATH = 11
    PAPER_ARTIFACT = 12
    UNKNOWN = 13


# Removable candidates: annotation ink only. Classification never
# authorizes removal by itself — CONFIDENCE_MIN and zero print overlap
# still apply. PAPER_ARTIFACT and UNKNOWN are preserved by policy.
ANNOTATION_CLASSES = (
    LayerClass.GRADING_MARK,
    LayerClass.BLACK_PEN,
    LayerClass.PENCIL,
    LayerClass.BLUE_PEN,
    LayerClass.RED_PEN,
    LayerClass.HIGHLIGHTER,
)
REVIEW_CLASSES = (
    LayerClass.PRINT_WRITING_OVERLAP,
    LayerClass.PRINT_GRADING_OVERLAP,
    LayerClass.UNKNOWN,
)

# Feature thresholds. These are calibration inputs, not verdicts: each
# component records a confidence margin relative to them, and removal
# additionally requires CONFIDENCE_MIN and zero print overlap.
PRINT_MAX = 55            # print cores live below this; pencil cores reach ~110
STROKE_MARGIN = 40        # stroke = at least this much darker than local paper
MIN_MARK_AREA = 150       # px — smaller blobs are antialiased glyph edges
UNKNOWN_MIN_AREA = 40     # px — ambiguous ink above this is recorded, not dropped
MAX_PRINT_NEIGHBOR = 0.5  # marks often sit next to print; only reject heavy fusion
MIN_BBOX_RATIO = 4.0      # strokes are sparse inside their bbox; glyph clusters are not
MIN_DIAGONAL = 70         # px — marks are large; glyph fragments are small
GRADING_MIN_DIAGONAL = 120  # px — grading ○/X marks span wider than pen strokes
CHROMA_MIN = 40           # colored ink (red/blue pens) stands out by chroma
WHITE_MIN = 245
PENCIL_MIN = 90           # pencil/graphite cores; darker strokes are pen ink
BLUE_DOMINANCE = 25       # blue ink: B exceeds R and G by at least this
HIGHLIGHT_MIN_CHANNEL = 90  # translucent marks keep a bright weakest channel
ARTIFACT_MARGIN = 8       # paper residue below stroke margin but above this
FIGURE_RUN_FRAC = 0.6     # a dark run this long inside its bbox = ruled line
FIGURE_MIN_EXTENT = 100   # px — figures/lines span far more than glyphs
DILATE_RADIUS = 2

# Dev-fixture calibration knob: removal requires confidence >= this.
# TODO(RESTORE-04): calibrate per class on the rights-cleared labeled set;
# a single global bar is the safe interim — below it goes to review.
CONFIDENCE_MIN = 0.5


@dataclass
class ComponentEvidence:
    label: int
    layer: LayerClass
    bbox: tuple[int, int, int, int]  # x, y, w, h
    area: int
    confidence: float
    overlap_pixels: int = 0
    removable: bool = False
    reason: str = ""


@dataclass
class LayerEvidence:
    """Per-page classification: one class id per pixel + component table."""

    class_map: np.ndarray                       # HxW uint8 of LayerClass
    components: list[ComponentEvidence] = field(default_factory=list)
    removal_mask: np.ndarray = None             # approved annotation pixels
    review_mask: np.ndarray = None              # OVERLAP / low-confidence
    source_shape: tuple[int, int] = (0, 0)

    def class_mask(self, cls: LayerClass) -> np.ndarray:
        return self.class_map == int(cls)


def classify_layers(
    gray: np.ndarray,
    rgb: Optional[np.ndarray] = None,
    math_regions: Optional[Sequence[tuple[int, int, int, int]]] = None,
) -> LayerEvidence:
    """Assign every ink pixel a layer class with per-component evidence.

    `math_regions` (x, y, w, h in pixel space) upgrades print components
    that intersect them from PRINT_TEXT to PRINT_MATH; when omitted the
    class is simply never assigned — MathDNA regions are wired in a later
    phase.
    """
    h, w = gray.shape
    class_map = np.zeros((h, w), dtype=np.uint8)
    components: list[ComponentEvidence] = []

    print_dark = gray < PRINT_MAX
    bg = np.asarray(
        Image.fromarray(gray).filter(ImageFilter.GaussianBlur(radius=12)),
        dtype=np.int16,
    )

    # --- print classes -----------------------------------------------------
    labels, counts = _label(print_dark)
    for lbl, count in counts.items():
        region = labels == lbl
        ys, xs = np.nonzero(region)
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        bw, bh = x1 - x0, y1 - y0
        if _is_figure_component(region, x0, y0, bw, bh):
            layer = LayerClass.PRINT_FIGURE
        elif math_regions and _hits_any(x0, y0, bw, bh, math_regions):
            layer = LayerClass.PRINT_MATH
        else:
            layer = LayerClass.PRINT_TEXT
        class_map[region] = int(layer)
        components.append(
            ComponentEvidence(
                label=lbl, layer=layer, bbox=(x0, y0, bw, bh), area=count,
                confidence=1.0, reason="print_dark",
            )
        )

    # --- annotation candidates --------------------------------------------
    chroma = _chroma(rgb, (h, w))
    rgb_min = _rgb_min(rgb, (h, w))
    saturated = chroma > CHROMA_MIN
    # Translucent colored marking keeps a bright weakest channel; dark ink
    # (red/blue pens, grading marks) does not.
    highlight_cand = saturated & (rgb_min >= HIGHLIGHT_MIN_CHANNEL)
    color_cand = saturated & (_rgb_max(rgb, (h, w)) < WHITE_MIN) & ~highlight_cand
    stroke_cand = (
        (~print_dark) & (gray.astype(np.int16) < bg - STROKE_MARGIN)
    )
    artifact_cand = (
        (~print_dark) & ~saturated & ~stroke_cand
        & (gray.astype(np.int16) < bg - ARTIFACT_MARGIN)
    )
    comp_map = np.zeros((h, w), dtype=np.int32)  # pixel -> component id
    _classify_annotation(
        highlight_cand, class_map, comp_map, components, gray, chroma,
        print_dark, rgb, kind="highlighter",
    )
    _classify_annotation(
        color_cand, class_map, comp_map, components, gray, chroma, print_dark,
        rgb, kind="colored",
    )
    _classify_annotation(
        stroke_cand & ~saturated, class_map, comp_map, components, gray,
        chroma, print_dark, rgb, kind="stroke",
    )
    _classify_annotation(
        artifact_cand, class_map, comp_map, components, gray, chroma,
        print_dark, rgb, kind="artifact",
    )

    # Dilated coverage — antialiased edges around a confident mark go with it.
    annotation = np.isin(
        class_map,
        [int(c) for c in ANNOTATION_CLASSES] + [int(c) for c in REVIEW_CLASSES],
    )
    review = np.isin(class_map, [int(c) for c in REVIEW_CLASSES])
    removable = np.zeros((h, w), dtype=bool)
    for comp in components:
        if comp.removable:
            removable |= comp_map == comp.label

    # Grow removal/review into the antialiased halo of their own components.
    removal_mask = _dilate(removable, DILATE_RADIUS) & ~print_dark & ~review
    review_mask = (_dilate(review, 1) & annotation) | review
    review_mask &= ~removal_mask

    return LayerEvidence(
        class_map=class_map,
        components=components,
        removal_mask=removal_mask,
        review_mask=review_mask,
        source_shape=(h, w),
    )


def _is_figure_component(
    region: np.ndarray, x0: int, y0: int, bw: int, bh: int
) -> bool:
    """Long ruled runs or a large sparse extent mark figure/table ink."""
    if max(bw, bh) >= FIGURE_MIN_EXTENT:
        sub = region[y0 : y0 + bh, x0 : x0 + bw]
        for row in sub:
            if _longest_run(row) >= FIGURE_RUN_FRAC * bw:
                return True
        for col in sub.T:
            if _longest_run(col) >= FIGURE_RUN_FRAC * bh:
                return True
    return False


def _classify_annotation(
    cand: np.ndarray,
    class_map: np.ndarray,
    comp_map: np.ndarray,
    components: list[ComponentEvidence],
    gray: np.ndarray,
    chroma: np.ndarray,
    print_dark: np.ndarray,
    rgb: Optional[np.ndarray],
    kind: str,
) -> None:
    """Split candidate ink into annotation/artifact classes or promote to
    overlap/UNKNOWN. `kind` is colored|stroke|highlighter|artifact."""
    labels, counts = _label(cand)
    # Component ids must be unique across the annotation passes.
    offset = int(comp_map.max())
    if offset:
        lbl_mask = labels > 0
        labels = labels + offset * lbl_mask.astype(np.int32)
        counts = {lbl + offset: c for lbl, c in counts.items()}
    ys, xs = np.nonzero(cand)
    coords = (
        np.stack([labels[ys, xs], ys, xs], axis=1)
        if len(ys)
        else np.empty((0, 3), dtype=np.int64)
    )
    for lbl, count in counts.items():
        if count < UNKNOWN_MIN_AREA:
            continue
        region = labels == lbl
        pts = coords[coords[:, 0] == lbl][:, 1:]
        y0, y1 = int(pts[:, 0].min()), int(pts[:, 0].max()) + 1
        x0, x1 = int(pts[:, 1].min()), int(pts[:, 1].max()) + 1
        bw, bh = x1 - x0, y1 - y0
        diagonal = (bw * bw + bh * bh) ** 0.5
        # Classes are disjoint per pixel, so "overlap" means the mark's
        # antialiased halo touches print cores — a stroke crossing a print
        # line connects to it under a small dilation.
        overlap_px = int((_dilate(region, 3) & print_dark).sum())

        # Confidence = smallest normalized margin across the shape checks.
        margins = [
            min(1.0, diagonal / (MIN_DIAGONAL * 2)),
            min(1.0, (bw * bh) / (count * MIN_BBOX_RATIO * 2)),
        ]
        if kind == "colored":
            mean_chroma = float(chroma[region].mean())
            margins.append(min(1.0, mean_chroma / (CHROMA_MIN * 3)))
            layer = _colored_layer(region, rgb, diagonal, count, bw, bh)
        elif kind == "highlighter":
            mean_chroma = float(chroma[region].mean())
            margins.append(min(1.0, mean_chroma / (CHROMA_MIN * 3)))
            layer = LayerClass.HIGHLIGHTER
        elif kind == "artifact":
            layer = LayerClass.PAPER_ARTIFACT
            margins.append(1.0)
        else:
            mean_gray = float(gray[region].mean())
            layer = (
                LayerClass.PENCIL
                if mean_gray >= PENCIL_MIN
                else LayerClass.BLACK_PEN
            )
            margins.append(min(1.0, abs(mean_gray - PENCIL_MIN) / 60 + 0.5))
        confidence = float(min(margins))

        ring = _dilate(region, 3) & ~region
        print_frac = float(print_dark[ring].mean()) if ring.any() else 0.0
        if kind == "artifact":
            # Paper artifacts are preserved unconditionally — never
            # removable, never pushed to human review.
            comp = ComponentEvidence(
                label=lbl, layer=layer, bbox=(x0, y0, bw, bh), area=count,
                confidence=round(confidence, 3), overlap_pixels=overlap_px,
                removable=False, reason="paper_artifact",
            )
        elif count < MIN_MARK_AREA:
            # Above the recording floor but below the shape floor — keep it
            # visible for review instead of silently dropping it.
            comp = ComponentEvidence(
                label=lbl, layer=LayerClass.UNKNOWN, bbox=(x0, y0, bw, bh),
                area=count, confidence=round(confidence, 3),
                overlap_pixels=overlap_px, removable=False,
                reason="below_shape_floor",
            )
        else:
            uncertain = (
                overlap_px > 0
                or print_frac >= MAX_PRINT_NEIGHBOR
                or diagonal < MIN_DIAGONAL
                or bw * bh < count * MIN_BBOX_RATIO
                or confidence < CONFIDENCE_MIN
            )
            overlap_layer = (
                LayerClass.PRINT_GRADING_OVERLAP
                if kind in ("colored", "highlighter")
                else LayerClass.PRINT_WRITING_OVERLAP
            )
            comp = ComponentEvidence(
                label=lbl,
                layer=overlap_layer if uncertain else layer,
                bbox=(x0, y0, bw, bh),
                area=count,
                confidence=round(confidence, 3),
                overlap_pixels=overlap_px,
                removable=not uncertain,
                reason=(
                    "print_overlap" if overlap_px
                    else "print_neighbor" if print_frac >= MAX_PRINT_NEIGHBOR
                    else "low_confidence" if confidence < CONFIDENCE_MIN
                    else "shape_rejected" if uncertain
                    else f"{kind}_confident"
                ),
            )
        class_map[region] = int(comp.layer)
        comp_map[region] = comp.label
        components.append(comp)


def _colored_layer(
    region: np.ndarray,
    rgb: Optional[np.ndarray],
    diagonal: float,
    count: int,
    bw: int,
    bh: int,
) -> LayerClass:
    """Blue ink → BLUE_PEN; red-family ink → GRADING_MARK when it spans
    like a ○/X grading mark, else RED_PEN (small red handwriting)."""
    if rgb is not None:
        sub = rgb[region]
        if (
            float(sub[:, 2].mean()) - float(sub[:, 0].mean())
            > BLUE_DOMINANCE
            and float(sub[:, 2].mean()) - float(sub[:, 1].mean())
            > BLUE_DOMINANCE
        ):
            return LayerClass.BLUE_PEN
    return (
        LayerClass.GRADING_MARK
        if diagonal >= GRADING_MIN_DIAGONAL
        else LayerClass.RED_PEN
    )


def _hits_any(
    x0: int, y0: int, bw: int, bh: int,
    regions: Sequence[tuple[int, int, int, int]],
) -> bool:
    x1, y1 = x0 + bw, y0 + bh
    for rx, ry, rw, rh in regions:
        if x0 < rx + rw and rx < x1 and y0 < ry + rh and ry < y1:
            return True
    return False


def _chroma(rgb: Optional[np.ndarray], shape: tuple[int, int]) -> np.ndarray:
    if rgb is None:
        return np.zeros(shape, dtype=np.int16)
    if rgb.shape[:2] != shape:
        rgb = np.asarray(
            Image.fromarray(rgb.astype(np.uint8)).resize((shape[1], shape[0])),
            dtype=np.int16,
        )
    return rgb.max(axis=2) - rgb.min(axis=2)


def _rgb_max(rgb: Optional[np.ndarray], shape: tuple[int, int]) -> np.ndarray:
    if rgb is None:
        return np.full(shape, 255, dtype=np.int16)
    if rgb.shape[:2] != shape:
        rgb = np.asarray(
            Image.fromarray(rgb.astype(np.uint8)).resize((shape[1], shape[0])),
            dtype=np.int16,
        )
    return rgb.max(axis=2)


def _rgb_min(rgb: Optional[np.ndarray], shape: tuple[int, int]) -> np.ndarray:
    if rgb is None:
        return np.full(shape, 255, dtype=np.int16)
    if rgb.shape[:2] != shape:
        rgb = np.asarray(
            Image.fromarray(rgb.astype(np.uint8)).resize((shape[1], shape[0])),
            dtype=np.int16,
        )
    return rgb.min(axis=2)


def load_rgb(path: Path, shape: tuple[int, int]) -> Optional[np.ndarray]:
    """RGB evidence for chroma features; PDFs return None."""
    if not path.exists() or path.suffix.lower() == ".pdf":
        return None
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
    if rgb.shape[:2] != shape:
        rgb = np.asarray(
            Image.open(path).convert("RGB").resize((shape[1], shape[0])),
            dtype=np.int16,
        )
    return rgb


def overlay_image(gray: np.ndarray, evidence: LayerEvidence) -> Image.Image:
    """Color-coded review overlay — every kept decision stays inspectable."""
    colors = {
        LayerClass.PRINT_TEXT: (60, 60, 60),
        LayerClass.PRINT_FIGURE: (30, 90, 200),
        LayerClass.PRINT_MATH: (20, 160, 120),
        LayerClass.GRADING_MARK: (230, 30, 30),
        LayerClass.RED_PEN: (230, 110, 110),
        LayerClass.BLUE_PEN: (60, 110, 240),
        LayerClass.BLACK_PEN: (240, 140, 0),
        LayerClass.PENCIL: (200, 190, 40),
        LayerClass.HIGHLIGHTER: (255, 240, 90),
        LayerClass.PAPER_ARTIFACT: (160, 160, 160),
        LayerClass.PRINT_WRITING_OVERLAP: (220, 0, 220),
        LayerClass.PRINT_GRADING_OVERLAP: (140, 0, 220),
        LayerClass.UNKNOWN: (0, 200, 220),
    }
    out = np.stack([gray] * 3, axis=2).astype(np.uint8)
    for cls, rgb in colors.items():
        out[evidence.class_map == int(cls)] = rgb
    return Image.fromarray(out, mode="RGB")


def _longest_run(row) -> int:
    if not row.any():
        return 0
    padded = np.concatenate(([False], row, [False]))
    diff = np.diff(padded.astype(np.int8))
    starts = np.nonzero(diff == 1)[0]
    ends = np.nonzero(diff == -1)[0]
    if not len(starts):
        return 0
    return int((ends - starts).max())


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(radius):
        grown = out.copy()
        grown[1:] |= out[:-1]
        grown[:-1] |= out[1:]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def _label(mask: np.ndarray) -> tuple[np.ndarray, dict[int, int]]:
    """8-connectivity component labeling — cv2 fast path with a
    pure-Python fallback for minimal installs."""
    try:
        import cv2

        n, labels = cv2.connectedComponents(
            mask.astype(np.uint8), connectivity=8
        )
        hist = np.bincount(labels.ravel(), minlength=n)
        counts = {int(i): int(hist[i]) for i in range(1, n)}
        return labels.astype(np.int32), counts
    except ImportError:
        pass
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    parent = [0]

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    next_label = 1
    for y in range(h):
        for x in np.nonzero(mask[y])[0]:
            neighbors = []
            if x > 0 and labels[y, x - 1]:
                neighbors.append(labels[y, x - 1])
            if y > 0:
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if 0 <= xx < w and labels[y - 1, xx]:
                        neighbors.append(labels[y - 1, xx])
            if neighbors:
                m = min(neighbors)
                labels[y, x] = m
                for n in neighbors:
                    union(m, n)
            else:
                parent.append(next_label)
                labels[y, x] = next_label
                next_label += 1

    counts: dict[int, int] = {}
    for y in range(h):
        for x in np.nonzero(mask[y])[0]:
            r = find(int(labels[y, x]))
            labels[y, x] = r
            counts[r] = counts.get(r, 0) + 1
    return labels, counts
