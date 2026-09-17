from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from document.models import Page, PageImage
from .context import PipelineContext

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_VARIANTS = ("grayscale", "high_contrast", "binarized")


def run(ctx: PipelineContext) -> None:
    uploads = sorted((ctx.workdir / "uploads").iterdir())
    if not uploads:
        ctx.emit("preprocessing", "업로드된 파일이 없습니다", "warn")
        return

    ctx.document.pages = []
    for index, path in enumerate(uploads):
        ext = path.suffix.lower()
        page = Page(index=index, original=PageImage(uri=str(path)))
        if ext in _IMAGE_EXTS:
            page.original.variants = _make_variants(path, ctx.workdir)
            with Image.open(path) as im:
                page.width, page.height = im.size
        elif ext == ".pdf":
            ctx.emit(
                "preprocessing",
                f"{path.name}: PDF 래스터라이저 미연결 — 페이지 이미지 없이 등록",
                "warn",
            )
        ctx.document.pages.append(page)

    ctx.emit("preprocessing", f"{len(ctx.document.pages)}페이지 정규화 완료")


def _make_variants(path: Path, workdir: Path) -> dict[str, str]:
    out_dir = workdir / "variants"
    out_dir.mkdir(exist_ok=True)
    variants: dict[str, str] = {}
    with Image.open(path) as im:
        base = im.convert("RGB")
        gray = ImageOps.grayscale(base)
        gray_path = out_dir / f"{path.stem}_grayscale.png"
        gray.save(gray_path)
        variants["grayscale"] = str(gray_path)

        high = ImageOps.autocontrast(gray, cutoff=1)
        high_path = out_dir / f"{path.stem}_high_contrast.png"
        high.save(high_path)
        variants["high_contrast"] = str(high_path)

        binarized = high.point(lambda p: 255 if p > 180 else 0, mode="1")
        bin_path = out_dir / f"{path.stem}_binarized.png"
        binarized.save(bin_path)
        variants["binarized"] = str(bin_path)
    return variants
