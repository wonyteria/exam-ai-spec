from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageOps

from document.models import Page, PageImage, PdfPageInventory, TransformStep
from .context import PipelineContext

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_VARIANTS = ("grayscale", "high_contrast", "binarized")
PDF_RENDER_SCALE = 200 / 72  # 200 dpi rasterization baseline
# A page with fewer glyphs than this has a text layer too thin to trust
# (e.g. a watermark string on a scan) — treated as image-only for
# recognition purposes but reported separately (RESTORE-01).
TEXT_LAYER_SPARSE_CHARS = 20

# EXIF orientation values that involve a 90/270-degree swap.
_EXIF_SWAP = {5, 6, 7, 8}


def run(ctx: PipelineContext) -> None:
    """Normalize page images: derive grayscale/high-contrast/binarized
    variants into the job workdir. Originals are immutable blobs and are
    never modified in place (WP03 non-destructive preprocessing)."""
    if not ctx.document.pages:
        _import_legacy_uploads(ctx)
    if not ctx.document.pages:
        ctx.emit("preprocessing", "업로드된 파일이 없습니다", "warn")
        return

    for page in ctx.document.pages:
        path = ctx.resolve_uri(page.original.uri)
        ext = path.suffix.lower()
        if page.pdf_page_index is not None or ext == ".pdf":
            _rasterize_pdf_page(ctx, page, path)
            continue
        if not path.exists():
            page.processing_error = "source_missing"
            ctx.emit("preprocessing", f"{path.name}: 원본을 찾을 수 없습니다", "warn")
            continue
        base = _load_oriented(ctx, page, path)
        if base is None:
            continue
        page.original.variants = _make_variants(base, ctx.workdir, path.stem, page)

    ctx.emit("preprocessing", f"{len(ctx.document.pages)}페이지 정규화 완료")


def _load_oriented(ctx: PipelineContext, page: Page, path: Path) -> Image.Image | None:
    """Load the original honoring EXIF orientation; record the transform so
    source anchors in original pixels stay invertible (02 SourceAnchor)."""
    try:
        with Image.open(path) as im:
            exif_orientation = None
            try:
                exif_orientation = im.getexif().get(274)
            except Exception:
                pass
            oriented = ImageOps.exif_transpose(im)
            base = oriented.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        page.processing_error = f"image_decode_failed: {exc}"
        ctx.emit("preprocessing", f"{path.name}: 이미지 디코드 실패 — {exc}", "warn")
        return None
    page.width, page.height = base.size
    if exif_orientation and exif_orientation != 1:
        swapped = exif_orientation in _EXIF_SWAP
        page.transform = {
            "kind": "exif_orientation",
            "exif_orientation": exif_orientation,
            "axes_swapped": swapped,
            "original_width": int(page.height) if swapped else int(page.width),
            "original_height": int(page.width) if swapped else int(page.height),
            "applied": True,
        }
        page.transform_chain.append(
            TransformStep(kind="exif_orientation", params=dict(page.transform))
        )
        ctx.emit(
            "preprocessing",
            f"{path.name}: EXIF 회전 {exif_orientation} 적용",
        )
    return base


def _rasterize_pdf_page(ctx: PipelineContext, page: Page, path: Path) -> None:
    """Render one PDF page to a PNG in the job workdir (original PDF bytes
    stay immutable) and derive the standard variants from it.

    Also records the page's native content inventory (RESTORE-01): an
    image-only page is explicitly marked `image_only` rather than silently
    treated as if OCR input were text.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        page.processing_error = "pypdfium2_missing"
        ctx.emit(
            "preprocessing",
            f"{path.name}: PDF 래스터라이저(pypdfium2) 미설치 — 건너뜀",
            "warn",
        )
        return
    try:
        pdf = pdfium.PdfDocument(str(path))
        try:
            idx = page.pdf_page_index or 0
            pdf_page = pdf[idx]
            page.inventory = _page_inventory(pdf_page, idx)
            bitmap = pdf_page.render(scale=PDF_RENDER_SCALE)
            base = bitmap.to_pil().convert("RGB")
        finally:
            pdf.close()
    except Exception as exc:
        page.processing_error = f"pdf_render_failed: {exc}"
        ctx.emit("preprocessing", f"{path.name}: PDF 렌더 실패 — {exc}", "warn")
        return

    if page.inventory and page.inventory.image_only:
        ctx.emit(
            "preprocessing",
            f"{path.name} p{idx}: 텍스트 계층 없음 — 이미지 경로로 처리",
        )

    page.width, page.height = base.size
    page.transform = {
        "kind": "pdf_raster",
        "pdf_page_index": idx,
        "scale": PDF_RENDER_SCALE,
        "applied": True,
    }
    page.transform_chain.append(
        TransformStep(kind="pdf_raster", params=dict(page.transform))
    )
    out_dir = ctx.workdir / "pdf_pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{path.stem}_p{idx:03d}"
    raster_path = out_dir / f"{stem}.png"
    base.save(raster_path)
    page.original.variants = {"raster": str(raster_path)}
    page.original.variant_sha256["raster"] = hashlib.sha256(
        raster_path.read_bytes()
    ).hexdigest()
    page.original.variants.update(_make_variants(base, ctx.workdir, stem, page))


def _page_inventory(pdf_page, idx: int) -> PdfPageInventory:
    """Native-object census of one PDF page (text/image/path/form counts,
    image bounds, rotation, boxes). Extraction failures on individual
    objects degrade to counts of what could be read, not a crash."""
    w, h = pdf_page.get_size()
    tp = pdf_page.get_textpage()
    try:
        text_chars = tp.count_chars()
    finally:
        tp.close()

    counts = {"text": 0, "image": 0, "path": 0, "form": 0, "shading": 0, "other": 0}
    image_bounds: list[list[float]] = []
    kind_names = {1: "text", 2: "path", 3: "image", 4: "shading", 5: "form"}
    try:
        objects = list(pdf_page.get_objects())
    except Exception:
        objects = []
    for obj in objects:
        kind = kind_names.get(getattr(obj, "type", None), "other")
        counts[kind] += 1
        if kind == "image":
            try:
                image_bounds.append([round(v, 1) for v in obj.get_bounds()])
            except Exception:
                pass

    return PdfPageInventory(
        page_index=idx,
        width_pt=round(w, 2),
        height_pt=round(h, 2),
        rotation=int(pdf_page.get_rotation()),
        mediabox=[round(v, 2) for v in pdf_page.get_mediabox()],
        cropbox=[round(v, 2) for v in pdf_page.get_cropbox()],
        text_chars=int(text_chars),
        text_objects=counts["text"],
        image_objects=counts["image"],
        path_objects=counts["path"],
        form_objects=counts["form"],
        shading_objects=counts["shading"],
        other_objects=counts["other"],
        image_bounds_pt=image_bounds,
        image_only=text_chars == 0,
        text_layer_sparse=0 < text_chars < TEXT_LAYER_SPARSE_CHARS,
    )


def _import_legacy_uploads(ctx: PipelineContext) -> None:
    """Jobs created before object storage kept files under
    workdir/uploads with no document.pages — keep importing those."""
    uploads_dir = ctx.workdir / "uploads"
    if not uploads_dir.exists():
        return
    for index, path in enumerate(sorted(uploads_dir.iterdir())):
        ctx.document.pages.append(
            Page(index=index, original=PageImage(uri=str(path)))
        )


def _make_variants(
    base: Image.Image, workdir: Path, stem: str, page: Page | None = None
) -> dict[str, str]:
    out_dir = workdir / "variants"
    out_dir.mkdir(parents=True, exist_ok=True)
    variants: dict[str, str] = {}

    gray = ImageOps.grayscale(base)
    gray_path = out_dir / f"{stem}_grayscale.png"
    gray.save(gray_path)
    variants["grayscale"] = str(gray_path)

    high = ImageOps.autocontrast(gray, cutoff=1)
    high_path = out_dir / f"{stem}_high_contrast.png"
    high.save(high_path)
    variants["high_contrast"] = str(high_path)

    binarized = high.point(lambda p: 255 if p > 180 else 0, mode="1")
    bin_path = out_dir / f"{stem}_binarized.png"
    binarized.save(bin_path)
    variants["binarized"] = str(bin_path)

    if page is not None:
        # Derived bytes are evidence: bind every variant to its hash so a
        # later crop/recognition input is attributable (RESTORE-01).
        for name, p in variants.items():
            page.original.variant_sha256[name] = hashlib.sha256(
                Path(p).read_bytes()
            ).hexdigest()
    return variants
