from __future__ import annotations

from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Reconstruct the clean printed layer after trace removal.

    Stub: passes the grayscale variant through as the clean layer.
    """
    for page in ctx.document.pages:
        page.clean_uri = page.original.variants.get(
            "grayscale", page.original.uri
        )
    ctx.emit(
        "print_layer",
        f"{len(ctx.document.pages)}페이지 인쇄 레이어 복원 (stub — 그레이스케일 통과)",
        "warn",
    )
