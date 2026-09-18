from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from document.models import Page, PageImage
from .context import PipelineContext

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_VARIANTS = ("grayscale", "high_contrast", "binarized")
PDF_RENDER_SCALE = 200 / 72  # 200 dpi rasterization baseline

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
            ctx.emit("preprocessing", f"{path.name}: 원본을 찾을 수 없습니다", "warn")
            continue
        base = _load_oriented(ctx, page, path)
        page.original.variants = _make_variants(base, ctx.workdir, path.stem)

    ctx.emit("preprocessing", f"{len(ctx.document.pages)}페이지 정규화 완료")


def _load_oriented(ctx: PipelineContext, page: Page, path: Path) -> Image.Image:
    """Load the original honoring EXIF orientation; record the transform so
    source anchors in original pixels stay invertible (02 SourceAnchor)."""
    with Image.open(path) as im:
        exif_orientation = None
        try:
            exif_orientation = im.getexif().get(274)
        except Exception:
            pass
        oriented = ImageOps.exif_transpose(im)
        base = oriented.convert("RGB")
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
        ctx.emit(
            "preprocessing",
            f"{path.name}: EXIF 회전 {exif_orientation} 적용",
        )
    return base


def _rasterize_pdf_page(ctx: PipelineContext, page: Page, path: Path) -> None:
    """Render one PDF page to a PNG in the job workdir (original PDF bytes
    stay immutable) and derive the standard variants from it."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
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
            bitmap = pdf_page.render(scale=PDF_RENDER_SCALE)
            base = bitmap.to_pil().convert("RGB")
        finally:
            pdf.close()
    except Exception as exc:
        ctx.emit("preprocessing", f"{path.name}: PDF 렌더 실패 — {exc}", "warn")
        return

    page.width, page.height = base.size
    page.transform = {
        "kind": "pdf_raster",
        "pdf_page_index": idx,
        "scale": PDF_RENDER_SCALE,
        "applied": True,
    }
    out_dir = ctx.workdir / "pdf_pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{path.stem}_p{idx:03d}"
    raster_path = out_dir / f"{stem}.png"
    base.save(raster_path)
    page.original.variants = {"raster": str(raster_path)}
    page.original.variants.update(_make_variants(base, ctx.workdir, stem))


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


def _make_variants(base: Image.Image, workdir: Path, stem: str) -> dict[str, str]:
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
    return variants
