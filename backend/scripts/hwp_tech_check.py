"""WP00 minimal HWP technical validation.

Creates a document containing 1 equation object, 1 vector drawing object,
and 1 real endnote via the actual HWP COM automation, saves to .hwpx/.hwp,
reopens the file, and verifies the objects round-trip.

Usage: python backend/scripts/hwp_tech_check.py [out_dir]
"""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path


def _open_hwp():
    import win32com.client

    try:
        hwp = win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")
    except Exception:
        hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
    return hwp


def probe_actions(hwp) -> dict:
    """Report which parameter sets / create-action names resolve."""
    report = {}
    for name in ("HEqEdit", "HShapeObject", "HInsertText", "HTableCreation",
                 "HLineShape", "HInsertShape"):
        try:
            getattr(hwp.HParameterSet, name)
            report[f"paramset.{name}"] = True
        except Exception as exc:
            report[f"paramset.{name}"] = f"FAIL {exc}"
    for name in ("InsertEquation", "InsertEndnote", "InsertFootnote",
                 "InsertLine", "InsertRectangle", "InsertShape",
                 "Equation", "InsertText"):
        try:
            act = hwp.CreateAction(name)
            report[f"action.{name}"] = act is not None
        except Exception as exc:
            report[f"action.{name}"] = f"FAIL {exc}"
    return report


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="hwp_check_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"out_dir": str(out_dir), "steps": {}}

    hwp = _open_hwp()
    try:
        result["version"] = hwp.Version
        try:
            # EquationCreate hangs when the document window is hidden.
            hwp.XHwpWindows.Item(0).Visible = True
        except Exception:
            pass
        print("step: probe", file=sys.stderr, flush=True)
        result["steps"]["probe"] = probe_actions(hwp)

        # --- plain text -----------------------------------------------------
        print("step: text", file=sys.stderr, flush=True)
        hwp.HAction.GetDefault("InsertText", hwp.HParameterSet.HInsertText.HSet)
        hwp.HParameterSet.HInsertText.Text = "기술 검증 문단\r\n"
        hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)
        result["steps"]["text"] = "ok"

        # --- equation object -------------------------------------------------
        try:
            print("step: equation", file=sys.stderr, flush=True)
            hwp.HAction.GetDefault("EquationCreate", hwp.HParameterSet.HEqEdit.HSet)
            eq = hwp.HParameterSet.HEqEdit
            eq.string = "left ( 1 + {1} over {2} right ) times 3 rm ~cm"
            eq.BaseUnit = 1100  # 11pt (HWP baseUnit: 100 units = 1pt)
            hwp.HAction.Execute("EquationCreate", hwp.HParameterSet.HEqEdit.HSet)
            result["steps"]["equation"] = "ok"
        except Exception as exc:
            result["steps"]["equation"] = f"FAIL {exc}"

        # --- vector figure (line shape) --------------------------------------
        try:
            print("step: figure", file=sys.stderr, flush=True)
            hwp.HAction.GetDefault("InsertLine", hwp.HParameterSet.HShapeObject.HSet)
            hwp.HAction.Execute("InsertLine", hwp.HParameterSet.HShapeObject.HSet)
            result["steps"]["figure"] = "ok"
        except Exception as exc:
            result["steps"]["figure"] = f"FAIL {exc}"

        # --- endnote ----------------------------------------------------------
        try:
            print("step: endnote", file=sys.stderr, flush=True)
            hwp.HAction.Run("InsertEndnote")
            hwp.HAction.GetDefault("InsertText", hwp.HParameterSet.HInsertText.HSet)
            hwp.HParameterSet.HInsertText.Text = "미주 본문: 정답 ④, 풀이 예시"
            hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)
            hwp.HAction.Run("CloseEx")
            result["steps"]["endnote"] = "ok"
        except Exception as exc:
            result["steps"]["endnote"] = f"FAIL {exc}"

        # --- save -------------------------------------------------------------
        hwpx_path = out_dir / "tech_check.hwpx"
        hwp_path = out_dir / "tech_check.hwp"
        try:
            print("step: save_hwpx", file=sys.stderr, flush=True)
            hwp.SaveAs(str(hwpx_path), "HWPX", "")
            result["steps"]["save_hwpx"] = "ok"
        except Exception as exc:
            result["steps"]["save_hwpx"] = f"FAIL {exc}"
        try:
            print("step: save_hwp", file=sys.stderr, flush=True)
            hwp.SaveAs(str(hwp_path), "HWP", "")
            result["steps"]["save_hwp"] = "ok"
        except Exception as exc:
            result["steps"]["save_hwp"] = f"FAIL {exc}"

        # --- reopen + object inspection ---------------------------------------
        try:
            print("step: reopen", file=sys.stderr, flush=True)
            hwp.Open(str(hwp_path), "HWP", "versioncheck:false")
            texts = hwp.GetText()
            result["steps"]["reopen_hwp"] = "ok"
            result["reopen_text_head"] = texts[:200]
        except Exception as exc:
            result["steps"]["reopen_hwp"] = f"FAIL {exc}"

        # --- hwpx XML inspection ------------------------------------------------
        try:
            with zipfile.ZipFile(hwpx_path) as zf:
                names = zf.namelist()
                section = zf.read("Contents/section0.xml").decode("utf-8", "replace")
            result["steps"]["hwpx_zip"] = "ok"
            result["hwpx"] = {
                "entries": names,
                "has_equation": "<hp:equation" in section or "equation" in section.lower(),
                "has_endnote": "endnote" in section.lower(),
                "has_line_or_drawing": ("<hp:line" in section
                                        or "drawing" in section.lower()
                                        or "<hp:shape" in section.lower()),
            }
        except Exception as exc:
            result["steps"]["hwpx_zip"] = f"FAIL {exc}"
    finally:
        try:
            hwp.Quit()
        except Exception:
            pass

    print(json.dumps(result, ensure_ascii=False, indent=2))
    (out_dir / "tech_check_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failed = [k for k, v in result["steps"].items() if isinstance(v, str) and v.startswith("FAIL")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
