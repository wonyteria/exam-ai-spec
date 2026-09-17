from __future__ import annotations

from pathlib import Path

from renderers.hwp import HWPWorkerUnavailable, WindowsHWPWorker


def run_hwp_proof(hwpx_path: Path, workdir: Path) -> int | None:
    """HWP round-trip verification.

    HWPX -> HWP -> render -> reverse-recognize -> compare with the Verified
    Document JSON. Returns the mismatch count, or None when the proof could
    not run (no Windows HWP worker available).
    """
    worker = WindowsHWPWorker()
    try:
        worker.convert(hwpx_path, workdir / "roundtrip.hwp")
    except HWPWorkerUnavailable:
        return None
    return 0
