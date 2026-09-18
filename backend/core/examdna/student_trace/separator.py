from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from ..context import PipelineContext

# Print is near-black; pencil graphite sits between print and the local
# paper gray (scanned paper is ~150-210, not white).
PRINT_MAX = 55            # print cores live below this; pencil cores reach ~110
STROKE_MARGIN = 40        # stroke = at least this much darker than local paper
MIN_MARK_AREA = 150       # px — smaller blobs are antialiased glyph edges
MAX_PRINT_NEIGHBOR = 0.5  # marks often sit next to print; only reject heavy fusion
MIN_BBOX_RATIO = 4.0      # strokes are sparse inside their bbox; glyph clusters are not
MIN_DIAGONAL = 70         # px — marks are large; glyph fragments are small
CHROMA_MIN = 40           # colored ink (red/blue pens) stands out by chroma
WHITE_MIN = 245

# S01 guard: never whiten print-dark pixels; record overlap components as
# uncertain regions. Internal knob — the golden-cache migration script
# disables it to reproduce the pre-guard (destructive) output bytes.
PRESERVE_PRINT_OVERLAP = True


def run(ctx: PipelineContext) -> None:
    """Separate student handwriting/marking traces from the printed layer.

    Emits a per-page trace mask and a trace_removed variant where masked
    stroke pixels are whitened. Print-layer restoration consumes it.
    """
    total_marks = 0
    work = ctx.workdir / "trace"
    work.mkdir(parents=True, exist_ok=True)
    for page in ctx.document.pages:
        gray_uri = page.original.variants.get("grayscale", page.original.uri)
        gray_path = ctx.resolve_uri(gray_uri)
        if not gray_path.exists():
            page.trace_mask_uri = None
            continue

        gray = np.asarray(Image.open(gray_path).convert("L"), dtype=np.uint8)
        mask = _trace_mask(gray, ctx.resolve_uri(page.original.uri))
        # S01 print-destruction guard: never whiten printed cores. Pixels
        # the trace classifier caught that sit on print-dark strokes are
        # unmasked and their components recorded as uncertain regions for
        # original comparison / human review.
        print_dark = gray < PRINT_MAX
        overlap = mask & print_dark
        if PRESERVE_PRINT_OVERLAP and overlap.any():
            mask = mask & ~print_dark
            page.uncertain_regions = _uncertain_regions(overlap)
            ctx.emit(
                "student_trace",
                f"페이지 {page.index + 1}: 인쇄 겹침 "
                f"{len(page.uncertain_regions)}영역을 원본 대조 대상으로 보존",
                "warn",
            )
        total_marks += int(mask.sum())

        mask_img = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
        mask_path = work / f"{gray_path.stem}_trace_mask.png"
        mask_img.save(mask_path)
        page.trace_mask_uri = str(mask_path)

        restored = gray.copy()
        restored[mask] = 255
        restored_path = work / f"{gray_path.stem}_trace_removed.png"
        Image.fromarray(restored, mode="L").save(restored_path)
        page.original.variants["trace_removed"] = str(restored_path)

    ctx.emit(
        "student_trace",
        f"{len(ctx.document.pages)}페이지 필기 분리 — 추적 픽셀 {total_marks}",
        "info" if total_marks else "warn",
    )


def _trace_mask(gray: np.ndarray, original: Path) -> np.ndarray:
    mask = _pencil_mask(gray) | _color_mask(original, gray.shape)
    return _dilate(mask, 2)


def _uncertain_regions(overlap: np.ndarray) -> list[dict]:
    """Bounding boxes of print-overlapping trace components — regions where
    deletion could damage print, kept so they can be compared against the
    original instead of silently erased (S01)."""
    labels, counts = _label(overlap)
    ys, xs = np.nonzero(overlap)
    regions: list[dict] = []
    if not len(ys):
        return regions
    coords = np.stack([labels[ys, xs], ys, xs], axis=1)
    for lbl, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        pts = coords[coords[:, 0] == lbl][:, 1:]
        regions.append(
            {
                "bbox_px": {
                    "x": int(pts[:, 1].min()),
                    "y": int(pts[:, 0].min()),
                    "w": int(pts[:, 1].max() - pts[:, 1].min()) + 1,
                    "h": int(pts[:, 0].max() - pts[:, 0].min()) + 1,
                },
                "overlap_pixels": int(count),
                "reason": "trace_mask_overlaps_print",
            }
        )
    return regions


def _pencil_mask(gray: np.ndarray) -> np.ndarray:
    """Hand-drawn strokes: darker than local paper, sparse inside their bbox.

    Print cores (<55) are excluded from candidates. Pencil strokes reach
    ~60-160 and form large, sparse components (circles, checks, writing)
    whereas printed glyph fragments stay small or sit next to print-dark
    cores.
    """
    print_dark = gray < PRINT_MAX
    bg = np.asarray(
        Image.fromarray(gray).filter(ImageFilter.GaussianBlur(radius=12)),
        dtype=np.int16,
    )
    pencil = (gray >= PRINT_MAX) & (gray.astype(np.int16) < bg - STROKE_MARGIN)
    labels, counts = _label(pencil)
    ys, xs = np.nonzero(pencil)
    coords = np.stack([labels[ys, xs], ys, xs], axis=1) if len(ys) else np.empty((0, 3))
    out = np.zeros_like(pencil)
    for lbl, count in counts.items():
        if count < MIN_MARK_AREA:
            continue
        region = labels == lbl
        pts = coords[coords[:, 0] == lbl][:, 1:]
        h = int(pts[:, 0].max() - pts[:, 0].min()) + 1
        w = int(pts[:, 1].max() - pts[:, 1].min()) + 1
        diagonal = (h * h + w * w) ** 0.5
        if diagonal < MIN_DIAGONAL or h * w < count * MIN_BBOX_RATIO:
            continue
        ring = _dilate(region, 3) & ~region
        print_frac = float(print_dark[ring].mean()) if ring.any() else 0.0
        if print_frac < MAX_PRINT_NEIGHBOR:
            out |= region
    return out


def _color_mask(original: Path, shape: tuple[int, int]) -> np.ndarray:
    """Colored ink (red/blue grading pens) via chroma on the original scan."""
    if not original.exists() or original.suffix.lower() == ".pdf":
        return np.zeros(shape, dtype=bool)
    rgb = np.asarray(Image.open(original).convert("RGB"), dtype=np.int16)
    if rgb.shape[:2] != shape:
        rgb = np.asarray(
            Image.open(original).convert("RGB").resize((shape[1], shape[0])),
            dtype=np.int16,
        )
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    return (chroma > CHROMA_MIN) & (rgb.max(axis=2) < WHITE_MIN)


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
    """Two-pass 8-connectivity component labeling (no scipy dependency)."""
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
