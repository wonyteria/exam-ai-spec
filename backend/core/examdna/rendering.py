from __future__ import annotations

from renderers.hwpx import render_hwpx
from renderers.web import render_preview
from .context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Render web preview + HWPX artifact from the Document JSON."""
    out = ctx.store.export_dir(ctx.document.id)
    preview = out / "preview.html"
    preview.write_text(render_preview(ctx.document), encoding="utf-8")

    hwpx = out / "exam.hwpx"
    hwpx.write_bytes(render_hwpx(ctx.document))
    ctx.emit("rendering", f"미리보기 + HWPX 생성 → {out}")
