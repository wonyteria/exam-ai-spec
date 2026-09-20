"""HWP COM process lifecycle for REBRAND_HWP (HWP_REBRANDING_SPEC §11).

A rebranding COM run must never leave Hwp.exe descendants behind — and
must never kill Hancom instances it did not spawn. A bare before/after
PID diff is NOT safe: a user (or another worker job) can launch Hwp.exe
while our operation runs, and a PID-diff sweep would taskkill it.

Ownership is therefore *confirmed*, never assumed:

- `hwp_command_lines()` distinguishes COM automation servers (command
  line carries -Embedding/-Automation) from user-launched editors.
- `hwp_window_pids()` pins the exact instance hosting our document:
  isolated inputs are copied under a uuid filename, so the document
  window title identifies the owning process uniquely.
- `sweep_spawned_hwp()` kills only PIDs confirmed ours. New COM-spawned
  PIDs we could not confirm are reported `unresolved` and left running;
  new GUI instances are reported `foreign_preserved` and never touched.

On timeout or crash the source is untouched and no final artifact exists
by construction (mutations run on copies; artifact registration happens
only after invariants pass).
"""
from __future__ import annotations

import csv
import io
import json
import platform
import subprocess
import time
from typing import Iterable

_HWP_IMAGE_NAMES = {"hwp.exe", "hwp"}
_HWP_KILL_GRACE_S = 4.0
# OLE marks out-of-process automation servers with an activation flag a
# user-launched editor never carries.
_COM_SPAWN_MARKERS = ("-embedding", "/embedding", "-automation", "/automation")


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


def hwp_command_lines() -> dict[int, str]:
    """PID -> command line for running Hwp.exe processes (Windows only).

    Empty when the query is unavailable — callers must then treat every
    spawned PID as *unconfirmed* (never kill)."""
    if platform.system() != "Windows":
        return {}
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='Hwp.exe'\" "
                "| Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    try:
        data = json.loads(out.stdout or "[]")
    except ValueError:
        return {}
    if isinstance(data, dict):
        data = [data]
    lines: dict[int, str] = {}
    for row in data:
        try:
            lines[int(row["ProcessId"])] = str(row.get("CommandLine") or "")
        except (KeyError, TypeError, ValueError):
            continue
    return lines


def is_com_spawned(cmdline: str) -> bool:
    low = (cmdline or "").lower()
    return any(m in low for m in _COM_SPAWN_MARKERS)


def hwp_window_pids(title_markers: Iterable[str]) -> set[int]:
    """PIDs owning a visible top-level window whose title contains any
    marker. Our isolated inputs carry uuid filenames, so the document
    window title pins exactly the instance this operation spawned."""
    markers = [m for m in title_markers if m]
    if platform.system() != "Windows" or not markers:
        return set()
    try:
        import win32gui
        import win32process
    except ImportError:
        return set()
    out: set[int] = set()

    def cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd) or ""
            if any(m in title for m in markers):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                out.add(pid)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        return set()
    return out


def kill_hwp_processes(pids: Iterable[int]) -> list[int]:
    """Force-kill specific Hwp PIDs confirmed owned by this operation.
    Returns the PIDs actually signalled. Never called with unconfirmed
    or pre-existing PIDs."""
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


def sweep_spawned_hwp(
    before: set[int],
    grace_s: float = _HWP_KILL_GRACE_S,
    own_pids: Iterable[int] = (),
    title_markers: Iterable[str] = (),
) -> dict:
    """Sweep Hwp.exe processes *this* operation spawned — nothing else.

    `own_pids` are PIDs already confirmed during the run (e.g. collected
    by the watchdog from our marker-titled windows); `title_markers` are
    substrings matched against live window titles for one final pin.
    Confirmed-own survivors are killed. New COM-spawned PIDs we cannot
    confirm are reported `unresolved` and left running; new GUI-launched
    instances are `foreign_preserved` and never signalled.
    """
    empty = {
        "spawned": [], "com_spawned": [], "own": [], "killed": [],
        "leak": 0, "leak_pids": [], "foreign_preserved": [], "unresolved": [],
    }
    if platform.system() != "Windows":
        return empty
    deadline = time.time() + grace_s
    spawned: set[int] = set()
    while True:
        spawned = hwp_process_inventory() - before
        if not spawned or time.time() >= deadline:
            break
        time.sleep(0.5)
    if not spawned:
        return empty

    own = (set(own_pids) | hwp_window_pids(title_markers)) & spawned
    cmdlines = hwp_command_lines()
    com_spawned = {
        pid for pid in spawned if is_com_spawned(cmdlines.get(pid, ""))
    }
    # When the cmdline query is unavailable we cannot even tell COM from
    # GUI — nothing is confirmed, so nothing extra joins `own`.
    unresolved = com_spawned - own
    foreign = spawned - com_spawned - own

    killed = set(kill_hwp_processes(own))
    still_up = own & hwp_process_inventory()
    return {
        "spawned": sorted(spawned),
        "com_spawned": sorted(com_spawned),
        "own": sorted(own),
        "killed": sorted(killed),
        "leak": len(still_up),
        "leak_pids": sorted(still_up),
        "foreign_preserved": sorted(foreign),
        "unresolved": sorted(unresolved - killed),
    }
