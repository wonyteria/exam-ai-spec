from __future__ import annotations

from qa.artifact_proof import bind_artifact_proof
from qa.hwp_proof import run_hwp_proof
from qa.hwpilot_proof import hwpilot_argv, hwpilot_readback
from .context import PipelineContext


def _independent_readback(ctx: PipelineContext) -> None:
    """Second-observer content readback through hwpilot — an
    implementation we did not write. Runs on every artifact present
    (HWPX and the binary HWP alike); tool absence is NOT_RUN evidence,
    never silently dropped."""
    results = []
    argv = hwpilot_argv()
    out = ctx.store.export_dir(ctx.document.id)
    for name in ("exam.hwpx", "exam.hwp"):
        path = out / name
        if not path.exists():
            continue
        miss = hwpilot_readback(path, ctx.document) if argv else None
        results.append(
            {
                "file": name,
                "status": "NOT_RUN" if miss is None else ("PASS" if miss == 0 else "FAILED"),
                "mismatch_count": miss,
            }
        )
    if results:
        ctx.artifact_proof["independent_readback"] = {
            "tool": "hwpilot",
            "level": "content_readback",
            "results": results,
        }
        worst = "FAILED" if any(r["status"] == "FAILED" for r in results) else (
            "NOT_RUN" if all(r["status"] == "NOT_RUN" for r in results) else "PASS"
        )
        ctx.emit(
            "export_verification",
            f"독립 readback(hwpilot): {worst} — "
            + ", ".join(f"{r['file']} {r['status']}" for r in results),
            "warn" if worst == "FAILED" else "info",
        )


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
    ctx.hwp_mismatch = run_hwp_proof(hwpx, ctx.workdir, ctx.document)
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
    _independent_readback(ctx)
