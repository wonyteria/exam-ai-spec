from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .layers import (
    LayerClass,
    REVIEW_CLASSES,
    classify_layers,
    load_rgb,
    overlay_image,
)
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
    """LayerDNA layer separation (RESTORE-04 six-class → RESTORE-11 14-class).

    Every ink pixel gets a class (print text/figure/math, per-ink-color
    annotation, highlighter, paper artifact, print↔writing/grading
    overlap, unknown) with per-component evidence. Only confident,
    non-overlapping annotation components are whiten-candidates — the
    restored variant is `restored_candidate`, and overlap/unknown
    components are preserved and recorded for review. Per-class masks
    and a color overlay are written next to the variants so every
    decision stays inspectable. Classification is not deletion:
    PAPER_ARTIFACT and UNKNOWN are preserved by policy.
    """
    import hashlib

    total_removed = 0
    total_review = 0
    work = ctx.workdir / "trace"
    work.mkdir(parents=True, exist_ok=True)
    for page in ctx.document.pages:
        # One bad page must not lose the rest of the job — failures are
        # recorded on the page and surface through review, not a crash.
        try:
            removed, review = _run_page(ctx, page, work)
            total_removed += removed
            total_review += review
        except Exception as exc:  # noqa: BLE001
            page.processing_error = f"trace_separation_failed: {exc}"
            ctx.emit(
                "student_trace",
                f"페이지 {page.index + 1}: 흔적 분리 실패 — {exc}",
                "error",
            )
    ctx.metric("student_trace", "removed_px", total_removed)
    ctx.metric("student_trace", "review_regions", total_review)
    ctx.metric("student_trace", "pages", len(ctx.document.pages))
    ctx.emit(
        "student_trace",
        f"{len(ctx.document.pages)}페이지 14-클래스 분리 — 제거 후보 픽셀 "
        f"{total_removed}, 검수 영역 {total_review}",
        "info" if total_removed or not total_review else "warn",
    )


def _run_page(ctx, page, work: Path) -> tuple[int, int]:
    """Separate one page; returns (removed_px, review_region_count)."""
    import hashlib

    gray_uri = page.original.variants.get("grayscale", page.original.uri)
    gray_path = ctx.resolve_uri(gray_uri)
    if not gray_path.exists():
        page.trace_mask_uri = None
        return 0, 0

    gray = np.asarray(Image.open(gray_path).convert("L"), dtype=np.uint8)
    if LEGACY_REMOVAL:
        _legacy_run(ctx, page, gray, gray_path, work)
        return 0, 0
    rgb = load_rgb(ctx.resolve_uri(page.original.uri), gray.shape)
    evidence = classify_layers(gray, rgb)

    # TraceDetector providers contribute region-level candidates;
    # ExamDNA's own pixel policy decides what may be removed inside
    # each box (provider output is never a removal mask).
    trace_boxes = _provider_trace_boxes(ctx, page, gray.shape)
    if trace_boxes:
        extra_removal, kept = _region_guided_removal(gray, trace_boxes)
        extra_removal &= ~evidence.removal_mask
        evidence.removal_mask |= extra_removal
        _record_provider_regions(page, trace_boxes, kept)
        _save_trace_overlay(
            gray, trace_boxes, evidence.removal_mask,
            work / f"{gray_path.stem}_provider_trace_overlay.png",
            page,
        )

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

    # Overlap / unknown / low-confidence components stay untouched and
    # become review entries (REVIEW_REQUIRED).
    review_regions = [
        {
            "bbox_px": {
                "x": c.bbox[0], "y": c.bbox[1], "w": c.bbox[2], "h": c.bbox[3],
            },
            "layer": c.layer.name,
            "overlap_pixels": c.overlap_pixels,
            "confidence": c.confidence,
            "reason": c.reason,
            "policy": "REVIEW_REQUIRED",
        }
        for c in evidence.components
        if c.layer in REVIEW_CLASSES
    ]
    if review_regions:
        page.uncertain_regions = (
            page.uncertain_regions or []
        ) + review_regions
        ctx.emit(
            "student_trace",
            f"페이지 {page.index + 1}: 겹침/불확실 {len(review_regions)}영역 "
            f"보존 — 검수 대상",
            "warn",
        )

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
    return int(mask.sum()), len(review_regions)


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


# --- provider trace regions -------------------------------------------------
# Policy inside a provider-flagged box: a component is *preserved* (kept +
# review entry) only when it looks like part of the printed page — it sits
# on a printed text line that continues well past the box, it is a
# near-perfectly straight dark stroke (printed figure/table edge), or it is
# a small dense glyph as dark as print cores. Everything else inside the
# box is removable ink. Removal still never touches print_dark cores.

INK_MARGIN = 8            # grow mask — catches the light halo around marks
INK_DECIDE_MARGIN = 25    # decide mask — tight enough to stop halo fusion
STRAIGHT_RESID = 1.4      # px — minor-axis std of a ruled print line
GLYPH_DARK_MARGIN = 55    # comp is "print-dark" when mean <= print_level + this
LINE_EXTEND = 80          # px — a protecting text line must outrun the box
MAX_TRACE_AREA_FRAC = 0.6  # a "trace" covering most of the page is not evidence
ENCLOSED_PRINT_MIN = 3    # print cores inside a comp bbox make it structural


def _provider_trace_boxes(ctx, page, shape: tuple[int, int]) -> list[dict]:
    """Collect trace region candidates from trace-detection providers.

    Provider output is a claim in normalized 0-1000 coordinates — never a
    pixel mask. Failures are recorded as warnings and simply contribute no
    regions."""
    providers = getattr(ctx.providers, "trace", None) or []
    if not providers:
        return []
    # PDF pages keep the raw document as `original` — providers need the
    # rasterized page image, not the container file.
    src = ctx.resolve_uri(
        page.original.variants.get("raster")
        or page.original.variants.get("grayscale")
        or page.original.uri
    )
    h, w = shape
    boxes: list[dict] = []
    for prov in providers:
        name = getattr(prov, "name", "trace")
        try:
            cand = prov.detect_traces(src)
        except Exception as exc:  # noqa: BLE001 — provider failure is evidence
            ctx.emit(
                "student_trace",
                f"페이지 {page.index + 1}: trace provider {name} 실패 — {exc}",
                "warn",
            )
            continue
        val = cand.value if isinstance(cand.value, dict) else {}
        if val.get("upside_down"):
            ctx.emit(
                "student_trace",
                f"페이지 {page.index + 1}: 페이지가 뒤집혀 있을 수 있습니다"
                " — 원본을 확인해주세요",
                "warn",
            )
        for t in val.get("traces") or []:
            try:
                x = float(t["x"]) / 1000 * w
                y = float(t["y"]) / 1000 * h
                bw = float(t["w"]) / 1000 * w
                bh = float(t["h"]) / 1000 * h
            except (KeyError, TypeError, ValueError):
                continue
            if bw <= 0 or bh <= 0 or bw * bh > MAX_TRACE_AREA_FRAC * w * h:
                continue
            boxes.append(
                {
                    "bbox": (x, y, bw, bh),
                    "kind": str(t.get("kind") or "trace"),
                    "provider": name,
                }
            )
    return boxes


def _minor_std(pts: np.ndarray) -> float:
    """Minor-axis spread of a component's pixels — ~0 for a straight edge."""
    if len(pts) < 4:
        return 0.0
    cov = np.cov(pts.astype(float).T)
    if cov.shape != (2, 2):
        return 0.0
    eig = np.linalg.eigvalsh(cov)
    return float(np.sqrt(max(eig[0], 0.0)))


def _region_guided_removal(
    gray: np.ndarray, boxes: list[dict]
) -> tuple[np.ndarray, list[dict]]:
    """Within each provider trace box, separate annotation ink from print.

    Returns (extra_removal_mask, kept_component_entries)."""
    h, w = gray.shape
    print_dark = gray < PRINT_MAX
    bg = np.asarray(
        Image.fromarray(gray).filter(ImageFilter.GaussianBlur(radius=12)),
        dtype=np.int16,
    )
    ink_grow = (~print_dark) & (gray.astype(np.int16) < bg - INK_MARGIN)
    # Components are formed on the tighter decide mask — photographed
    # print halos bridge marks to text at the loose threshold.
    ink = (~print_dark) & (
        gray.astype(np.int16) < bg - INK_DECIDE_MARGIN
    )
    stroke = print_dark | (
        (~print_dark) & (gray.astype(np.int16) < bg - STROKE_MARGIN)
    )

    # Print darkness reference from confirmed print cores; fallback keeps a
    # conservative absolute level when a page lacks deep-black print.
    core_vals = gray[print_dark]
    dark_thresh = (
        float(np.median(core_vals)) + GLYPH_DARK_MARGIN
        if len(core_vals) >= 500
        else 100.0
    )

    labels, counts = _label(ink)
    # Per-label pixel coordinates, computed once — components can span
    # multiple trace boxes.
    ys, xs = np.nonzero(ink)
    lbl_ids = labels[ys, xs]
    order = np.argsort(lbl_ids, kind="stable")
    bounds = np.flatnonzero(np.diff(lbl_ids[order])) + 1
    label_pts: dict[int, np.ndarray] = {}
    for grp in np.split(order, bounds):
        if not len(grp):
            continue
        label_pts[int(lbl_ids[grp[0]])] = np.stack(
            [ys[grp], xs[grp]], axis=1
        )
    # Pixels hugging print cores are treated as print structure — removal
    # (whole or partial) never eats them.
    near_print = _dilate(print_dark, 3)

    removal = np.zeros((h, w), dtype=bool)
    kept: list[dict] = []
    seen: set[int] = set()
    for box in boxes:
        bx, by, bw, bh = box["bbox"]
        x0, y0 = max(0, int(bx)), max(0, int(by))
        x1, y1 = min(w, int(bx + bw) + 1), min(h, int(by + bh) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        box_kept: list[dict] = []
        lbl_ids = np.unique(labels[y0:y1, x0:x1][ink[y0:y1, x0:x1]])
        for lbl in lbl_ids:
            lbl = int(lbl)
            if lbl in seen or lbl not in label_pts:
                continue
            seen.add(lbl)
            pts = np.asarray(label_pts[lbl])
            ch = int(pts[:, 0].max() - pts[:, 0].min()) + 1
            cw = int(pts[:, 1].max() - pts[:, 1].min()) + 1
            cy0, cx0 = int(pts[:, 0].min()), int(pts[:, 1].min())
            area = counts[lbl]
            fill = area / (ch * cw)
            diag = (ch * ch + cw * cw) ** 0.5
            mean_i = float(gray[pts[:, 0], pts[:, 1]].mean())

            # A component that mostly lives OUTSIDE the provider box is
            # part of a larger structure (printed figure edge, fused
            # print halo) the provider did not claim — keep it. Marks
            # merely spilling a few pixels past the box still count as
            # trace candidates.
            inside = int(((pts[:, 0] >= y0) & (pts[:, 0] < y1)
                        & (pts[:, 1] >= x0) & (pts[:, 1] < x1)).sum())
            mostly_outside = inside < 0.5 * area
            # A component whose bbox interior holds print cores encloses
            # printed content — a printed loop/figure, or a student mark
            # drawn over print (an overlap → review either way).
            encloses_print = (
                ch >= 6
                and cw >= 6
                and int(
                    print_dark[cy0 + 2 : cy0 + ch - 2, cx0 + 2 : cx0 + cw - 2].sum()
                )
                >= ENCLOSED_PRINT_MIN
            )

            # "On a printed line" is decided per row with the component's
            # own pixels excluded — so a circle crossing a text line does
            # not inherit the line's width, while a glyph that is part of
            # the line still sees the line running far past the box.
            comp_rows = np.unique(pts[:, 0])
            qualified_rows: set[int] = set()
            for ry in comp_rows:
                xs_r = pts[pts[:, 0] == ry, 1]
                row = stroke[ry].copy()
                row[xs_r] = False
                nz = np.nonzero(row)[0]
                if not len(nz):
                    continue
                rx0, rx1 = int(nz[0]), int(nz[-1])
                if (
                    bx - rx0 >= LINE_EXTEND or rx1 - (bx + bw) >= LINE_EXTEND
                ) and (rx1 - rx0) > 3 * cw:
                    qualified_rows.add(int(ry))
            on_print_line = len(qualified_rows) >= 0.5 * len(comp_rows)
            straight = (
                diag >= MIN_DIAGONAL and _minor_std(pts) <= STRAIGHT_RESID
            )
            glyph_dark = (
                fill >= 0.15
                and diag < MIN_DIAGONAL
                and mean_i <= dark_thresh
            )
            # Fully-preserved structures: anything mostly outside the
            # claimed box, enclosing print, ruled-straight, or a dark
            # dense glyph. A comp kept ONLY for sitting on a printed
            # line is a mark fused with text — its off-line, off-core
            # pixels inside the box are still annotation and come out.
            structural = mostly_outside or encloses_print or straight or glyph_dark
            if structural or on_print_line:
                kept_pts = pts
                if not structural:
                    off = ~np.isin(pts[:, 0], list(qualified_rows))
                    inb = (
                        (pts[:, 0] >= y0) & (pts[:, 0] < y1)
                        & (pts[:, 1] >= x0) & (pts[:, 1] < x1)
                    )
                    rm_sel = off & inb & ~near_print[pts[:, 0], pts[:, 1]]
                    if rm_sel.any():
                        removal[pts[rm_sel, 0], pts[rm_sel, 1]] = True
                        kept_pts = pts[~rm_sel]
                if len(kept_pts):
                    box_kept.append(
                        {
                            "x": int(kept_pts[:, 1].min()),
                            "y": int(kept_pts[:, 0].min()),
                            "w": int(kept_pts[:, 1].max() - kept_pts[:, 1].min()) + 1,
                            "h": int(kept_pts[:, 0].max() - kept_pts[:, 0].min()) + 1,
                            "reason": (
                                "extends_beyond_trace_box" if mostly_outside
                                else "encloses_print" if encloses_print
                                else "straight" if straight
                                else "glyph_dark" if glyph_dark
                                else "on_print_line"
                            ),
                        }
                    )
            else:
                # Marks spilling past the box are removed whole, except
                # pixels hugging print cores outside the claimed region.
                inb = (
                    (pts[:, 0] >= y0) & (pts[:, 0] < y1)
                    & (pts[:, 1] >= x0) & (pts[:, 1] < x1)
                )
                keep_out = (~inb) & near_print[pts[:, 0], pts[:, 1]]
                rm = pts[~keep_out]
                removal[rm[:, 0], rm[:, 1]] = True
        # One review entry per provider box — a teacher inspects regions,
        # not individual glyph components.
        if box_kept:
            x_min = min(k["x"] for k in box_kept)
            y_min = min(k["y"] for k in box_kept)
            x_max = max(k["x"] + k["w"] for k in box_kept)
            y_max = max(k["y"] + k["h"] for k in box_kept)
            kept.append(
                {
                    "bbox_px": {
                        "x": x_min,
                        "y": y_min,
                        "w": x_max - x_min,
                        "h": y_max - y_min,
                    },
                    "layer": "PROVIDER_TRACE",
                    "overlap_pixels": 0,
                    "confidence": 0.0,
                    "reason": "+".join(
                        sorted({k["reason"] for k in box_kept})
                    ),
                    "policy": "REVIEW_REQUIRED",
                    "trace_provider": box["provider"],
                    "trace_kind": box["kind"],
                }
            )

    removal &= ~print_dark
    # Grow removed cores into the loose ink mask to sweep up mark halos —
    # still never touching print cores or their immediate anti-aliasing.
    removal = (_dilate(removal, 2) & ink_grow & ~near_print) | removal
    return removal, kept


def _record_provider_regions(page, boxes: list[dict], kept: list[dict]) -> None:
    """Attach provider-trace review entries to the page's uncertain regions
    — kept print-like components inside trace boxes stay inspectable."""
    if kept:
        page.uncertain_regions = (page.uncertain_regions or []) + kept


def _save_trace_overlay(gray, boxes, removal_mask, path, page) -> None:
    """Color overlay: provider boxes (orange) over the removal mask (red)."""
    out = np.stack([gray] * 3, axis=2).astype(np.uint8)
    out[removal_mask] = (220, 60, 60)
    for box in boxes:
        x, y, w, h = box["bbox"]
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(gray.shape[1] - 1, int(x + w)), min(gray.shape[0] - 1, int(y + h))
        out[y0 : y0 + 2, x0:x1] = (255, 160, 0)
        out[y1 - 2 : y1, x0:x1] = (255, 160, 0)
        out[y0:y1, x0 : x0 + 2] = (255, 160, 0)
        out[y0:y1, x1 - 2 : x1] = (255, 160, 0)
    Image.fromarray(out, mode="RGB").save(path)
    page.original.variants["provider_trace_overlay"] = str(path)
