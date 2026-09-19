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
            if not hwp.Open(str(hwpx_path)):
                raise RuntimeError("Open(HWPX) returned False")
            hwp.SaveAs(str(out_hwp), "HWP")
            hwp.Run("FileClose")
            if not hwp.Open(str(out_hwp)):
                raise RuntimeError("ReOpen(HWP) returned False")
            hwp.SaveAs(str(out_pdf), "PDF")
            hwp.Run("FileClose")
            queue.put({"ok": True})
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
        self, hwpx_path: Path, out_hwp: Path, out_pdf: Path, request_revision: str = ""
    ) -> dict:
        if not self.is_available():
            raise HWPWorkerUnavailable(
                "Windows + pywin32 + Hancom HWP required for HWP export"
            )
        with self._lock:
            self.__class__._runs += 1
            run_no = self.__class__._runs
            root = Path(tempfile.mkdtemp(prefix="examdna-hwp-"))
            started = time.time()
            try:
                iso_in = root / f"in-{uuid.uuid4().hex}.hwpx"
                iso_hwp = root / "out.hwp"
                iso_pdf = root / "out.pdf"
                shutil.copy2(hwpx_path, iso_in)
                q: mp.Queue = mp.Queue()
                proc = mp.Process(
                    target=self._isolated_roundtrip,
                    args=(self.prog_id, str(iso_in), str(iso_hwp), str(iso_pdf), q),
                    daemon=True,
                )
                proc.start()
                proc.join(timeout=self.timeout_seconds)
                timed_out = proc.is_alive()
                if timed_out:
                    proc.terminate()
                    proc.join(timeout=5)
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
                return {
                    "checks": checks,
                    "worker_identity": f"{socket.gethostname()}:{os.getpid()}",
                    "request_revision": request_revision,
                    "hwpx_sha256": self._sha256(hwpx_path),
                    "hwp_sha256": self._sha256(out_hwp),
                    "pdf_sha256": self._sha256(out_pdf),
                    "elapsed_ms": int((time.time() - started) * 1000),
                    "isolation_dir": str(root),
                    "run_no": run_no,
                    "recycle_due": self.recycle_every > 0 and run_no % self.recycle_every == 0,
                }
            finally:
                meta = root / "proof_meta.json"
                try:
                    meta.write_text(
                        json.dumps(
                            {
                                "request_revision": request_revision,
                                "run_no": run_no,
                                "timestamp": time.time(),
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
