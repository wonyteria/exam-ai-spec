from __future__ import annotations

from qa.artifact_proof import bind_artifact_proof
from qa.hwp_proof import run_hwp_proof
from .context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """HWP round-trip proof bound to the exact artifact bytes (RESTORE-07).

    The proof record carries the artifact's SHA-256; a file mutated after
    the proof can never inherit it. A missing artifact or an unavailable
    worker is NOT_RUN — never a pass.
    """
    hwpx = ctx.store.export_dir(ctx.document.id) / "exam.hwpx"
    if not hwpx.exists():
        ctx.artifact_proof = {"status": "NOT_RUN", "detail": "no_artifact"}
        ctx.emit("export_verification", "HWPX 산출물 없음 — 역검증 생략", "warn")
        return
    ctx.hwp_mismatch = run_hwp_proof(hwpx, ctx.workdir)
    if ctx.hwp_mismatch is None:
        ctx.artifact_proof = bind_artifact_proof(
            hwpx, "NOT_RUN", detail="hwp_worker_unavailable"
        )
        ctx.emit(
            "export_verification",
            "Windows HWP 워커 없음 — HWP 역검증 생략 (HWPX만 검증됨)",
            "warn",
        )
    else:
        status = "PASS" if ctx.hwp_mismatch == 0 else "FAILED"
        ctx.artifact_proof = bind_artifact_proof(
            hwpx, status, mismatch_count=ctx.hwp_mismatch
        )
        ctx.emit(
            "export_verification",
            f"HWP 역검증 완료 — 불일치 {ctx.hwp_mismatch}건 ({status})",
        )
