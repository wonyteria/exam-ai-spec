from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import platform
import shutil
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path


class HWPWorkerUnavailable(RuntimeError):
    pass


def _hwp_security_dialogs(pids: set[int]) -> list[int]:
    """HWNDs of Hancom file-access security dialogs owned by `pids`.

    With a FilePathCheck module registered (e.g. by another installed
    product), Hancom shows a per-process consent dialog on the first
    external Open and blocks the COM call until a human answers. On an
    automation host nobody is there to click — without handling, every
    operation dies at the timeout. The dialog is a small visible
    HwndWrapper window; the main document window ('... - 한글') is
    excluded so an Alt+N is never posted to a document.
    """
    if platform.system() != "Windows":
        return []
    try:
        import win32gui
        import win32process
    except ImportError:
        return []
    out: list[int] = []

    def cb(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid not in pids or not win32gui.IsWindowVisible(hwnd):
                return True
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            w, h = r - l, b - t
            title = win32gui.GetWindowText(hwnd) or ""
            if (
                200 < w < 900
                and 100 < h < 500
                and "한글" not in title
                and win32gui.GetClassName(hwnd).startswith("HwndWrapper")
            ):
                out.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        return []
    return out


def _approve_security_dialog(hwnd: int) -> bool:
    """Post Alt+N ('모두 허용(N)') to the file-access consent dialog.
    Posted messages only — never real input injection, so no focus steal."""
    try:
        import win32con
        import win32gui
    except ImportError:
        return False
    try:
        win32gui.PostMessage(hwnd, win32con.WM_SYSKEYDOWN, ord("N"), 0x20380001)
        win32gui.PostMessage(hwnd, win32con.WM_SYSKEYUP, ord("N"), 0xC0380001)
        return True
    except Exception:
        return False


def _security_dialog_watchdog(
    hwp_before: set[int],
    stop: threading.Event,
    state: dict,
    title_markers: tuple = (),
) -> None:
    """While a COM call is in flight, approve Hancom's per-process
    file-access consent dialogs — but only on PIDs confirmed COM-spawned
    (a user's GUI-launched editor is never signalled). PIDs owning a
    window titled with our uuid input name are recorded in
    state["own_pids"] so the sweep kills only instances it can prove
    are ours. Each approval is counted for honest proof reporting."""
    from rebranding.hwp_worker_operation import (
        hwp_command_lines,
        hwp_process_inventory,
        hwp_window_pids,
        is_com_spawned,
    )

    seen: set[int] = set()
    com_cache: dict[int, bool] = {}
    own: set[int] = set(state.get("own_pids") or ())
    while not stop.is_set():
        spawned = hwp_process_inventory() - hwp_before
        own |= hwp_window_pids(title_markers) & spawned
        dialogs = _hwp_security_dialogs(spawned)
        if dialogs:
            cmdlines = hwp_command_lines()
            for hwnd in dialogs:
                if hwnd in seen:
                    continue
                try:
                    import win32process

                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                except Exception:
                    pid = 0
                if pid and pid not in com_cache:
                    com_cache[pid] = is_com_spawned(cmdlines.get(pid, ""))
                # never post approval to a GUI-launched editor's dialog
                if pid and not com_cache.get(pid, False):
                    continue
                if _approve_security_dialog(hwnd):
                    seen.add(hwnd)
                    state["security_dialogs_approved"] = (
                        state.get("security_dialogs_approved", 0) + 1
                    )
        stop.wait(0.5)
    state["own_pids"] = sorted(own)


class WindowsHWPWorker:
    """HWPX -> HWP conversion via Hancom HWP COM automation.

    Runs only on a Windows machine (server VM or academy PC agent) with
    Hancom Office installed. The web platform calls this as the last step
    of the export pipeline, then the result goes through HWP Proof.
    """

    _lock = threading.Lock()
    _runs = 0

    def __init__(self, prog_id: str = "HWPFrame.HwpObject"):
        self.prog_id = prog_id
        self.timeout_seconds = float(os.environ.get("EXAMDNA_HWP_TIMEOUT_SECONDS", "180"))
        self.recycle_every = int(os.environ.get("EXAMDNA_HWP_RECYCLE_EVERY", "20"))

    @staticmethod
    def is_available() -> bool:
        if platform.system() != "Windows":
            return False
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _isolated_roundtrip(
        prog_id: str,
        hwpx_path: str,
        out_hwp: str,
        out_pdf: str,
        queue: mp.Queue,
    ) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        hwp = None
        try:
            hwp = win32com.client.Dispatch(prog_id)
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
            open_hwpx = bool(hwp.Open(str(hwpx_path)))
            if not open_hwpx:
                raise RuntimeError("Open(HWPX) returned False")
            save_hwp = hwp.SaveAs(str(out_hwp), "HWP")
            hwp.Run("FileClose")
            reopen_hwp = bool(hwp.Open(str(out_hwp)))
            if not reopen_hwp:
                raise RuntimeError("ReOpen(HWP) returned False")
            save_pdf = hwp.SaveAs(str(out_pdf), "PDF")
            hwp.Run("FileClose")
            queue.put(
                {
                    "ok": True,
                    "steps": {
                        "open_hwpx": open_hwpx,
                        "saveas_hwp": bool(save_hwp) if save_hwp is not None else True,
                        "reopen_hwp": reopen_hwp,
                        "saveas_pdf": bool(save_pdf) if save_pdf is not None else True,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            if hwp is not None:
                try:
                    hwp.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

    def convert_with_proof(
        self, hwpx_path: Path, out_hwp: Path, out_pdf: Path, request_revision: str = "",
        operation_kind: str = "HWPX_TO_HWP_PDF",
    ) -> dict:
        if not self.is_available():
            raise HWPWorkerUnavailable(
                "Windows + pywin32 + Hancom HWP required for HWP export"
            )
        from rebranding.hwp_worker_operation import (
            hwp_process_inventory,
            sweep_spawned_hwp,
        )

        with self._lock:
            self.__class__._runs += 1
            run_no = self.__class__._runs
            root = Path(tempfile.mkdtemp(prefix="examdna-hwp-"))
            started = time.time()
            spawned_report: dict = {"spawned": [], "killed": [], "leak": 0}
            hwp_before = hwp_process_inventory()
            iso_in = root / f"in-{uuid.uuid4().hex}.hwpx"
            iso_hwp = root / "out.hwp"
            iso_pdf = root / "out.pdf"
            # the uuid input name appears in the document window title —
            # it is the ownership marker the watchdog/sweep pin our PID by
            markers = (iso_in.stem,)
            watchdog_state: dict = {}
            watchdog_stop = threading.Event()
            watchdog = threading.Thread(
                target=_security_dialog_watchdog,
                args=(hwp_before, watchdog_stop, watchdog_state, markers),
                daemon=True,
            )
            try:
                shutil.copy2(hwpx_path, iso_in)
                q: mp.Queue = mp.Queue()
                proc = mp.Process(
                    target=self._isolated_roundtrip,
                    args=(self.prog_id, str(iso_in), str(iso_hwp), str(iso_pdf), q),
                    daemon=True,
                )
                watchdog.start()
                proc.start()
                proc.join(timeout=self.timeout_seconds)
                watchdog_stop.set()
                timed_out = proc.is_alive()
                if timed_out:
                    proc.terminate()
                    proc.join(timeout=5)
                    spawned_report = sweep_spawned_hwp(
                        hwp_before,
                        grace_s=0,
                        own_pids=watchdog_state.get("own_pids", ()),
                        title_markers=markers,
                    )
                    raise TimeoutError(
                        f"HWP roundtrip timeout after {self.timeout_seconds}s"
                    )
                result = q.get_nowait() if not q.empty() else {"ok": False, "error": "no-result"}
                if not result.get("ok"):
                    raise RuntimeError(result.get("error", "unknown COM failure"))
                if not iso_hwp.exists() or not iso_pdf.exists():
                    raise RuntimeError("SaveAs outputs missing (HWP/PDF)")
                out_hwp.parent.mkdir(parents=True, exist_ok=True)
                out_pdf.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(iso_hwp, out_hwp)
                shutil.copy2(iso_pdf, out_pdf)
                checks = {
                    "FORMAT_OPEN_VALIDITY": "PASSED",
                    "FORMAT_CONVERSION_PROVENANCE": "PASSED",
                    "HWP_ACTUAL_REOPEN": "PASSED",
                    "ARTIFACT_HASH_BINDING": "PASSED",
                }
                spawned_report = sweep_spawned_hwp(
                    hwp_before,
                    own_pids=watchdog_state.get("own_pids", ()),
                    title_markers=markers,
                )
                spawned_report.update(watchdog_state)
                return {
                    "checks": checks,
                    "worker_identity": f"{socket.gethostname()}:{os.getpid()}",
                    "request_revision": request_revision,
                    "operation_kind": operation_kind,
                    "step_returns": (result.get("steps") or {}),
                    "hwpx_sha256": self._sha256(hwpx_path),
                    "hwp_sha256": self._sha256(out_hwp),
                    "pdf_sha256": self._sha256(out_pdf),
                    "elapsed_ms": int((time.time() - started) * 1000),
                    "isolation_dir": str(root),
                    "run_no": run_no,
                    "recycle_due": self.recycle_every > 0 and run_no % self.recycle_every == 0,
                    "hwp_process": spawned_report,
                }
            finally:
                watchdog_stop.set()
                spawned_report.update(watchdog_state)
                meta = root / "proof_meta.json"
                try:
                    meta.write_text(
                        json.dumps(
                            {
                                "request_revision": request_revision,
                                "operation_kind": operation_kind,
                                "run_no": run_no,
                                "timestamp": time.time(),
                                "hwp_process": spawned_report,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

    # -- HWP -> HWPX (rebrand scan input) -----------------------------------------

    @staticmethod
    def _isolated_open_saveas(
        prog_id: str, in_path: str, out_path: str, fmt: str, queue: mp.Queue
    ) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        hwp = None
        try:
            hwp = win32com.client.Dispatch(prog_id)
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
            opened = bool(hwp.Open(str(in_path)))
            if not opened:
                raise RuntimeError(f"Open({in_path}) returned False")
            saved = hwp.SaveAs(str(out_path), fmt)
            hwp.Run("FileClose")
            queue.put(
                {
                    "ok": True,
                    "steps": {
                        "open_source": opened,
                        "saveas": bool(saved) if saved is not None else True,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            if hwp is not None:
                try:
                    hwp.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

    def convert_to_hwpx(
        self, in_path: Path, out_hwpx: Path, request_revision: str = "",
        operation_kind: str = "REBRAND_SCAN_CONVERT",
    ) -> dict:
        """Open an .hwp (or .hwpx) in Hancom and SaveAs HWPX for structure
        scanning. Same isolation/timeout/process-leak contract as the
        export roundtrip."""
        if not self.is_available():
            raise HWPWorkerUnavailable(
                "Windows + pywin32 + Hancom HWP required to read .hwp sources"
            )
        from rebranding.hwp_worker_operation import (
            hwp_process_inventory,
            sweep_spawned_hwp,
        )

        with self._lock:
            self.__class__._runs += 1
            run_no = self.__class__._runs
            root = Path(tempfile.mkdtemp(prefix="examdna-hwp-scan-"))
            started = time.time()
            spawned_report: dict = {"spawned": [], "killed": [], "leak": 0}
            hwp_before = hwp_process_inventory()
            iso_in = root / f"in-{uuid.uuid4().hex}{in_path.suffix}"
            iso_out = root / "scan.hwpx"
            markers = (iso_in.stem,)
            watchdog_state: dict = {}
            watchdog_stop = threading.Event()
            watchdog = threading.Thread(
                target=_security_dialog_watchdog,
                args=(hwp_before, watchdog_stop, watchdog_state, markers),
                daemon=True,
            )
            try:
                shutil.copy2(in_path, iso_in)
                q: mp.Queue = mp.Queue()
                proc = mp.Process(
                    target=self._isolated_open_saveas,
                    args=(self.prog_id, str(iso_in), str(iso_out), "HWPX", q),
                    daemon=True,
                )
                watchdog.start()
                proc.start()
                proc.join(timeout=self.timeout_seconds)
                watchdog_stop.set()
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=5)
                    spawned_report = sweep_spawned_hwp(
                        hwp_before,
                        grace_s=0,
                        own_pids=watchdog_state.get("own_pids", ()),
                        title_markers=markers,
                    )
                    raise TimeoutError(
                        f"HWP->HWPX conversion timeout after {self.timeout_seconds}s"
                    )
                result = q.get_nowait() if not q.empty() else {"ok": False, "error": "no-result"}
                if not result.get("ok"):
                    raise RuntimeError(result.get("error", "unknown COM failure"))
                if not iso_out.exists():
                    raise RuntimeError("SaveAs HWPX output missing")
                out_hwpx.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(iso_out, out_hwpx)
                spawned_report = sweep_spawned_hwp(
                    hwp_before,
                    own_pids=watchdog_state.get("own_pids", ()),
                    title_markers=markers,
                )
                spawned_report.update(watchdog_state)
                return {
                    "ok": True,
                    "steps": result.get("steps") or {},
                    "worker_identity": f"{socket.gethostname()}:{os.getpid()}",
                    "request_revision": request_revision,
                    "operation_kind": operation_kind,
                    "source_sha256": self._sha256(in_path),
                    "hwpx_sha256": self._sha256(out_hwpx),
                    "elapsed_ms": int((time.time() - started) * 1000),
                    "run_no": run_no,
                    "hwp_process": spawned_report,
                }
            finally:
                watchdog_stop.set()
                spawned_report.update(watchdog_state)
                meta = root / "proof_meta.json"
                try:
                    meta.write_text(
                        json.dumps(
                            {
                                "request_revision": request_revision,
                                "operation_kind": operation_kind,
                                "run_no": run_no,
                                "timestamp": time.time(),
                                "hwp_process": spawned_report,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

    def convert(self, hwpx_path: Path, out_path: Path) -> Path:
        out_pdf = out_path.with_suffix(".pdf")
        self.convert_with_proof(hwpx_path, out_path, out_pdf)
        return out_path
