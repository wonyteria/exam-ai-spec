from __future__ import annotations

from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Separate student handwriting/marking traces from the printed layer.

    Stub: produces no masks yet. A real separator will emit per-page trace
    masks plus per-mark classifications (pencil/pen/red-check/etc.).
    """
    for page in ctx.document.pages:
        page.trace_mask_uri = None
    ctx.emit(
        "student_trace",
        f"{len(ctx.document.pages)}페이지 필기 분리 (stub — 마스크 없음)",
        "warn",
    )
