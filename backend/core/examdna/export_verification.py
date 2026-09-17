from __future__ import annotations

from qa.hwp_proof import run_hwp_proof
from .context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """HWP round-trip proof on the rendered HWPX."""
    hwpx = ctx.store.export_dir(ctx.document.id) / "exam.hwpx"
    if not hwpx.exists():
        ctx.emit("export_verification", "HWPX 산출물 없음 — 역검증 생략", "warn")
        return
    ctx.hwp_mismatch = run_hwp_proof(hwpx, ctx.workdir)
    if ctx.hwp_mismatch is None:
        ctx.emit(
            "export_verification",
            "Windows HWP 워커 없음 — HWP 역검증 생략 (HWPX만 검증됨)",
            "warn",
        )
    else:
        ctx.emit(
            "export_verification",
            f"HWP 역검증 완료 — 불일치 {ctx.hwp_mismatch}건",
        )
