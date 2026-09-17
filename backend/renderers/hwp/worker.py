from __future__ import annotations

import platform
from pathlib import Path


class HWPWorkerUnavailable(RuntimeError):
    pass


class WindowsHWPWorker:
    """HWPX -> HWP conversion via Hancom HWP COM automation.

    Runs only on a Windows machine (server VM or academy PC agent) with
    Hancom Office installed. The web platform calls this as the last step
    of the export pipeline, then the result goes through HWP Proof.
    """

    def __init__(self, prog_id: str = "HWPFrame.HwpObject"):
        self.prog_id = prog_id

    @staticmethod
    def is_available() -> bool:
        if platform.system() != "Windows":
            return False
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            return False
        return True

    def convert(self, hwpx_path: Path, out_path: Path) -> Path:
        if not self.is_available():
            raise HWPWorkerUnavailable(
                "Windows + pywin32 + Hancom HWP required for HWP export"
            )
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            hwp = win32com.client.Dispatch(self.prog_id)
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
            hwp.Open(str(hwpx_path))
            hwp.SaveAs(str(out_path), "HWP")
            hwp.Quit()
        finally:
            pythoncom.CoUninitialize()
        return out_path
