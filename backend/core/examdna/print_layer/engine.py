from __future__ import annotations

from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Reconstruct the clean printed layer after trace removal."""
    used_restored = 0
    for page in ctx.document.pages:
        # RESTORE-04: the print layer consumes the policy-filtered
        # `restored_candidate` (confident, non-overlap annotations removed)
        # — never the raw candidate mask applied to the source.
        clean = page.original.variants.get(
            "restored_candidate"
        ) or page.original.variants.get("trace_removed")
        if clean:
            used_restored += 1
        page.clean_uri = clean or page.original.variants.get(
            "grayscale", page.original.uri
        )
    ctx.emit(
        "print_layer",
        f"{len(ctx.document.pages)}페이지 인쇄 레이어 복원 — 필기 제거 적용 {used_restored}페이지",
    )
