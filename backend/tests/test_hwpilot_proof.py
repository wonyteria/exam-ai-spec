"""Independent readback via hwpilot — a second observer on artifacts.

Locks: tool absence is NOT_RUN (never silently skipped); a FAILED
readback downgrades checks our own parser passed; the binary HWP path
gets NATIVE_OBJECT_INTEGRITY evidence that previously had no source.
"""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from qa import hwpilot_proof
from qa.hwpilot_proof import hwpilot_argv, hwpilot_readback, hwpilot_text
from jobs.artifact_bridge import hwp_checks, hwpx_checks
from document.models import (
    Answer,
    Choice,
    Document,
    Question,
    TextSpan,
)
from renderers.hwpx import render_hwpx


def _doc() -> Document:
    doc = Document(tenant_id="t")
    doc.questions.append(
        Question(
            number=1, label="1", points=4,
            body=[TextSpan(text="다음 중 옳은 것은?")],
            choices=[
                Choice(label="①", body=[TextSpan(text="가")]),
                Choice(label="②", body=[TextSpan(text="나")]),
            ],
            answer=Answer(value="②"),
        )
    )
    return doc


class TestArgvResolution:
    def test_env_cmd_wins(self, monkeypatch):
        monkeypatch.setenv("HWPILOT_CMD", "node /x/main.js")
        assert hwpilot_argv() == ["node", "/x/main.js"]

    def test_env_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HWPILOT_CMD", raising=False)
        entry = tmp_path / "dist" / "src" / "cli" / "main.js"
        entry.parent.mkdir(parents=True)
        entry.write_text("x")
        monkeypatch.setenv("HWPILOT_DIR", str(tmp_path))
        argv = hwpilot_argv()
        assert argv is not None and argv[-1].endswith("main.js")

    def test_unavailable_returns_none(self, monkeypatch):
        monkeypatch.delenv("HWPILOT_CMD", raising=False)
        monkeypatch.setenv("HWPILOT_DIR", "/nonexistent")
        monkeypatch.setattr(
            hwpilot_proof, "_default_checkout_dir",
            lambda: hwpilot_proof.Path("/nonexistent"),
        )
        monkeypatch.setattr(hwpilot_proof.shutil, "which", lambda _x: None)
        assert hwpilot_argv() is None


class TestTextExtraction:
    def _run(self, monkeypatch, stdout="", rc=0):
        def _fake(argv, **kw):
            return SimpleNamespace(
                returncode=rc, stdout=stdout.encode("utf-8")
            )

        monkeypatch.setattr(subprocess, "run", _fake)
        monkeypatch.setenv("HWPILOT_CMD", "fake cmd")

    def test_parses_json(self, monkeypatch):
        self._run(monkeypatch, json.dumps({"text": "1. 문제"}))
        assert hwpilot_text("x.hwpx") == "1. 문제"

    def test_nonzero_rc_is_none(self, monkeypatch):
        self._run(monkeypatch, "boom", rc=1)
        assert hwpilot_text("x.hwpx") is None

    def test_bad_json_is_none(self, monkeypatch):
        self._run(monkeypatch, "not json")
        assert hwpilot_text("x.hwpx") is None

    def test_no_tool_is_none(self, monkeypatch):
        monkeypatch.setattr(hwpilot_proof, "hwpilot_argv", lambda: None)
        assert hwpilot_text("x.hwpx") is None


class TestReadback:
    def _patch_text(self, monkeypatch, text):
        monkeypatch.setattr(hwpilot_proof, "hwpilot_text", lambda p: text)

    def test_zero_mismatch_on_full_text(self, monkeypatch, tmp_path):
        self._patch_text(
            monkeypatch, "1. (4점) 다음 중 옳은 것은? ① 가 ② 나 정답: ②"
        )
        assert hwpilot_readback(tmp_path / "x", _doc()) == 0

    def test_missing_head_counts(self, monkeypatch, tmp_path):
        self._patch_text(monkeypatch, "다음 중 옳은 것은? ① 가 ② 나")
        assert hwpilot_readback(tmp_path / "x", _doc()) >= 1

    def test_unavailable_is_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(hwpilot_proof, "hwpilot_text", lambda p: None)
        assert hwpilot_readback(tmp_path / "x", _doc()) is None


class TestBridgeIntegration:
    def test_hwp_native_integrity_filled_by_readback(self, tmp_path, monkeypatch):
        hwp = tmp_path / "a.hwp"
        hwp.write_bytes(b"\xd0\xcf\x11\xe0fake")
        monkeypatch.setattr(
            "jobs.artifact_bridge.hwpilot_readback", lambda p, d: 0
        )
        checks = hwp_checks(hwp, tmp_path / "none.pdf", _doc(), {"checks": {}})
        assert checks["NATIVE_OBJECT_INTEGRITY"] == "PASSED"
        # binary coverage passes via direct readback even without a pdf
        assert checks["ARTIFACT_SEMANTIC_COVERAGE"] == "PASSED"

    def test_readback_failure_downgrades(self, tmp_path, monkeypatch):
        hwp = tmp_path / "a.hwp"
        hwp.write_bytes(b"\xd0\xcf\x11\xe0fake")
        monkeypatch.setattr(
            "jobs.artifact_bridge.hwpilot_readback", lambda p, d: 3
        )
        checks = hwp_checks(hwp, tmp_path / "none.pdf", _doc(), {"checks": {}})
        assert checks["NATIVE_OBJECT_INTEGRITY"] == "FAILED"
        assert checks["ARTIFACT_SEMANTIC_COVERAGE"] == "FAILED"

    def test_no_tool_keeps_not_run(self, tmp_path, monkeypatch):
        hwp = tmp_path / "a.hwp"
        hwp.write_bytes(b"\xd0\xcf\x11\xe0fake")
        monkeypatch.setattr(
            "jobs.artifact_bridge.hwpilot_readback", lambda p, d: None
        )
        checks = hwp_checks(hwp, tmp_path / "none.pdf", _doc(), {"checks": {}})
        assert checks["NATIVE_OBJECT_INTEGRITY"] == "NOT_RUN"

    def test_hwpx_independent_failure_downgrades(self, tmp_path, monkeypatch):
        p = tmp_path / "exam.hwpx"
        p.write_bytes(render_hwpx(_doc()))
        monkeypatch.setattr(
            "jobs.artifact_bridge.hwpilot_readback", lambda pth, d: 1
        )
        checks = hwpx_checks(p, _doc())
        assert checks["ARTIFACT_SEMANTIC_COVERAGE"] == "FAILED"


@pytest.mark.skipif(hwpilot_argv() is None, reason="hwpilot not installed")
def test_real_readback_on_rendered_hwpx(tmp_path):
    """Env-dependent: actual hwpilot on an actually-rendered artifact —
    the anti-pattern guard (our writer vs their parser)."""
    p = tmp_path / "exam.hwpx"
    p.write_bytes(render_hwpx(_doc()))
    assert hwpilot_readback(p, _doc()) == 0


class TestRebrandHwpFallback:
    """Binary .hwp imports: Hancom unavailable -> hwpilot converts for
    the scan/mutate work file, with provenance recorded; total absence
    still fails closed (503), never a fake scan."""

    def _setup(self, tmp_path, monkeypatch, convert_result):
        import zipfile as zf
        from fastapi import HTTPException
        from storage.local import LocalObjectStore
        from app.api import rebrand as rebrand_api
        from renderers.hwp import HWPWorkerUnavailable

        objects = LocalObjectStore(tmp_path / "objs")
        objects.put(
            "imports/t1/d1/source.hwp",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,
        )
        cstore = SimpleNamespace(
            list_source_pages=lambda d: [SimpleNamespace(asset_id="a1")],
            get_source_asset=lambda a: SimpleNamespace(
                blob_key="imports/t1/d1/source.hwp"
            ),
        )

        def _no_worker(self, src, dst, operation_kind=""):
            raise HWPWorkerUnavailable("no hancom")

        monkeypatch.setattr(
            rebrand_api.WindowsHWPWorker, "convert_to_hwpx", _no_worker
        )

        if convert_result:
            def _conv(src, dst):
                buf = tmp_path / "fake.hwpx"
                with zf.ZipFile(dst, "w") as z:
                    z.writestr("mimetype", "application/hwpx")
                return True
        else:
            def _conv(src, dst):
                return False

        monkeypatch.setattr(rebrand_api, "hwpilot_convert", _conv)
        return cstore, objects

    def test_hwpilot_converts_when_hancom_absent(self, tmp_path, monkeypatch):
        cstore, objects = self._setup(tmp_path, monkeypatch, True)
        from app.api.rebrand import _work_hwpx

        data = _work_hwpx("t1", "d1", cstore, objects)
        assert data.startswith(b"PK")
        conv = objects.open(
            "local://rebrand/t1/d1/work-converter.txt"
        ).read_text()
        assert conv == "hwpilot"

    def test_no_converter_fails_closed(self, tmp_path, monkeypatch):
        cstore, objects = self._setup(tmp_path, monkeypatch, False)
        from app.api.rebrand import _work_hwpx
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _work_hwpx("t1", "d1", cstore, objects)
        assert exc.value.status_code == 503
