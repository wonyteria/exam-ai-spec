from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .layers import LayerClass, classify_layers, load_rgb, overlay_image
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

# Cache-migration shim: reproduce the pre-RESTORE-04 removal semantics
# (dilated pencil|color mask minus print cores, written to the restored
# path). Only tests/golden/migrate_cache_restore04.py sets this.
LEGACY_REMOVAL = False


def run(ctx: PipelineContext) -> None:
    """Six-class layer separation (RESTORE-04).

    Every ink pixel gets a class (print/figure/grading/pen/pencil/overlap)
    with per-component evidence. Only confident, non-overlapping
    annotation components are whiten-candidates — the restored variant is
    `restored_candidate`, and overlap/uncertain components are preserved
    and recorded for review. Per-class masks and a color overlay are
    written next to the variants so every decision stays inspectable.
    """
    import hashlib

    total_removed = 0
    total_review = 0
    work = ctx.workdir / "trace"
    work.mkdir(parents=True, exist_ok=True)
    for page in ctx.document.pages:
        gray_uri = page.original.variants.get("grayscale", page.original.uri)
        gray_path = ctx.resolve_uri(gray_uri)
        if not gray_path.exists():
            page.trace_mask_uri = None
            continue

        gray = np.asarray(Image.open(gray_path).convert("L"), dtype=np.uint8)
        if LEGACY_REMOVAL:
            _legacy_run(ctx, page, gray, gray_path, work)
            continue
        rgb = load_rgb(ctx.resolve_uri(page.original.uri), gray.shape)
        evidence = classify_layers(gray, rgb)

        # Per-class evidence masks + review overlay — never merged into
        # one binary mask (spec 3.2).
        for cls in LayerClass:
            if cls == LayerClass.BACKGROUND:
                continue
            m = evidence.class_mask(cls)
            if not m.any():
                continue
            p = work / f"{gray_path.stem}_layer_{cls.name.lower()}.png"
            Image.fromarray((m * 255).astype(np.uint8), mode="L").save(p)
            page.original.variants[f"layer_{cls.name.lower()}"] = str(p)
            page.original.variant_sha256[f"layer_{cls.name.lower()}"] = (
                hashlib.sha256(p.read_bytes()).hexdigest()
            )
        overlay_path = work / f"{gray_path.stem}_layer_overlay.png"
        overlay_image(gray, evidence).save(overlay_path)
        page.original.variants["layer_overlay"] = str(overlay_path)

        # Restoration policy: REMOVE_CONFIDENT_ANNOTATION only — approved
        # (confident, non-overlap) annotation pixels are whitened; nothing
        # outside the approved mask may change.
        mask = evidence.removal_mask
        restored = gray.copy()
        restored[mask] = 255
        changed = restored != gray
        assert not (changed & ~mask).any(), "out-of-mask pixel change"

        # OVERLAP / low-confidence components stay untouched and become
        # review entries (REVIEW_REQUIRED).
        review_regions = [
            {
                "bbox_px": {
                    "x": c.bbox[0], "y": c.bbox[1], "w": c.bbox[2], "h": c.bbox[3],
                },
                "overlap_pixels": c.overlap_pixels,
                "confidence": c.confidence,
                "reason": c.reason,
                "policy": "REVIEW_REQUIRED",
            }
            for c in evidence.components
            if c.layer == LayerClass.OVERLAP
        ]
        if review_regions:
            page.uncertain_regions = review_regions
            ctx.emit(
                "student_trace",
                f"페이지 {page.index + 1}: 겹침/불확실 {len(review_regions)}영역 "
                f"보존 — 검수 대상",
                "warn",
            )

        total_removed += int(mask.sum())
        total_review += len(review_regions)

        page.trace_mask_uri = str(
            _save_mask(mask, work / f"{gray_path.stem}_trace_mask.png")
        )

        restored_path = work / f"{gray_path.stem}_restored_candidate.png"
        Image.fromarray(restored, mode="L").save(restored_path)
        page.original.variants["restored_candidate"] = str(restored_path)
        page.original.variant_sha256["restored_candidate"] = hashlib.sha256(
            restored_path.read_bytes()
        ).hexdigest()
        # `trace_removed` kept as an alias for legacy consumers/migration;
        # new code must read `restored_candidate`.
        page.original.variants.setdefault("trace_removed", str(restored_path))

    ctx.emit(
        "student_trace",
        f"{len(ctx.document.pages)}페이지 6-클래스 분리 — 제거 후보 픽셀 "
        f"{total_removed}, 검수 영역 {total_review}",
        "info" if total_removed or not total_review else "warn",
    )


def _save_mask(mask: np.ndarray, path: Path) -> Path:
    Image.fromarray((mask * 255).astype(np.uint8), mode="L").save(path)
    return path


def _legacy_run(ctx, page, gray: np.ndarray, gray_path: Path, work: Path) -> None:
    """Pre-RESTORE-04 semantics for golden-cache key reproduction only."""
    mask = _trace_mask(gray, ctx.resolve_uri(page.original.uri))
    if PRESERVE_PRINT_OVERLAP:
        mask = mask & ~(gray < PRINT_MAX)
    page.trace_mask_uri = str(
        _save_mask(mask, work / f"{gray_path.stem}_trace_mask.png")
    )
    restored = gray.copy()
    restored[mask] = 255
    restored_path = work / f"{gray_path.stem}_restored_candidate.png"
    Image.fromarray(restored, mode="L").save(restored_path)
    page.original.variants["restored_candidate"] = str(restored_path)
    page.original.variants["trace_removed"] = str(restored_path)


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
