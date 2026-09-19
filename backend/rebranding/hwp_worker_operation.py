"""HWP COM process lifecycle for REBRAND_HWP (HWP_REBRANDING_SPEC §11).

A rebranding COM run must never leave Hwp.exe descendants behind: the
worker snapshots the Hwp.exe process set before and after the operation
and force-kills only PIDs that *this* operation spawned — pre-existing
user/editor instances are never touched. On timeout or crash the source
is untouched and no final artifact exists by construction (mutations run
on copies; artifact registration happens only after invariants pass).
"""
from __future__ import annotations

import csv
import io
import platform
import subprocess
import time
from typing import Iterable

_HWP_IMAGE_NAMES = {"hwp.exe", "hwp"}
_HWP_KILL_GRACE_S = 4.0


def hwp_process_inventory() -> set[int]:
    """PID set of running Hwp.exe processes. Windows-only; empty elsewhere
    and empty when tasklist is unavailable (tests then treat COM paths as
    NOT_RUN rather than faking success)."""
    if platform.system() != "Windows":
        return set()
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Hwp.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    pids: set[int] = set()
    for row in csv.reader(io.StringIO(out.stdout or "")):
        if len(row) >= 2 and row[0].strip().lower() in _HWP_IMAGE_NAMES:
            try:
                pids.add(int(row[1].strip()))
            except ValueError:
                continue
    return pids


def kill_hwp_processes(pids: Iterable[int]) -> list[int]:
    """Force-kill specific Hwp PIDs spawned by this operation. Returns the
    PIDs actually signalled. Never called with pre-existing PIDs."""
    killed: list[int] = []
    if platform.system() != "Windows":
        return killed
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
            )
            killed.append(pid)
        except (OSError, subprocess.SubprocessError):
            continue
    return killed


def sweep_spawned_hwp(before: set[int], grace_s: float = _HWP_KILL_GRACE_S) -> dict:
    """Compare current Hwp.exe inventory with `before` and kill only new
    PIDs. Returns a leak report for the proof manifest."""
    if platform.system() != "Windows":
        return {"spawned": [], "killed": [], "leak": 0}
    deadline = time.time() + grace_s
    spawned: set[int] = set()
    while True:
        spawned = hwp_process_inventory() - before
        if not spawned or time.time() >= deadline:
            break
        time.sleep(0.5)
    killed = kill_hwp_processes(spawned) if spawned else []
    remaining = hwp_process_inventory() - before
    return {
        "spawned": sorted(spawned),
        "killed": sorted(killed),
        "leak": len(remaining),
        "leak_pids": sorted(remaining),
    }
