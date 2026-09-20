"""Pipeline → canonical artifact bridge: proof-bound registration.

Locks: every registered artifact carries a proof; checks are PASSED only
when actually verified (else NOT_RUN/FAILED), so nothing reaches
FINAL_ELIGIBLE on inference; an unavailable Hancom worker leaves hwp/pdf
unregistered — fail-closed, not silently claimed.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from canonical.policy import ARTIFACT_CHECKS_BY_FORMAT_V1
from document.models import (
    Answer,
    Choice,
    Document,
    Equation,
    Question,
    TextSpan,
)
from jobs.artifact_bridge import (
    hwpx_checks,
    hwp_checks,
    pdf_checks,
    register_pipeline_artifacts,
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
            equations=[Equation(latex="x^2")],
            answer=Answer(value="②"),
        )
    )
    return doc


def _hwpx(tmp_path) -> Path:
    p = tmp_path / "exam.hwpx"
    p.write_bytes(render_hwpx(_doc()))
    return p


class TestHwpxChecks:
    def test_complete_artifact_passes_verifiable_checks(self, tmp_path):
        checks = hwpx_checks(_hwpx(tmp_path), _doc())
        assert checks["FORMAT_OPEN_VALIDITY"] == "PASSED"
        assert checks["NATIVE_OBJECT_INTEGRITY"] == "PASSED"
        assert checks["ARTIFACT_SEMANTIC_COVERAGE"] == "PASSED"
        assert checks["ARTIFACT_HASH_BINDING"] == "PASSED"
        # render-dependent checks are honestly unproven
        assert checks["RENDERED_TEXT_VISUAL_MATCH"] == "NOT_RUN"
        assert checks["LAYOUT_STYLE_BOUNDS"] == "NOT_RUN"

    def test_broken_artifact_fails_validity(self, tmp_path):
        bad = tmp_path / "bad.hwpx"
        bad.write_bytes(b"not a zip")
        checks = hwpx_checks(bad, _doc())
        assert checks["FORMAT_OPEN_VALIDITY"] == "FAILED"
        assert checks["NATIVE_OBJECT_INTEGRITY"] == "NOT_RUN"

    def test_content_gap_fails_coverage(self, tmp_path):
        checks = hwpx_checks(_hwpx(tmp_path), _doc_with_extra_claim())
        assert checks["ARTIFACT_SEMANTIC_COVERAGE"] == "FAILED"


def _doc_with_extra_claim() -> Document:
    doc = _doc()
    doc.questions[0].choices.append(
        Choice(label="⑤", body=[TextSpan(text="없는선지")])
    )
    return doc


class TestPdfChecks:
    def test_missing_pdf_is_failed_not_run(self, tmp_path):
        checks = pdf_checks(tmp_path / "none.pdf", _doc())
        assert checks["FORMAT_OPEN_VALIDITY"] == "FAILED"

    def test_all_required_keys_present(self, tmp_path):
        checks = pdf_checks(tmp_path / "none.pdf", _doc())
        assert set(checks) == set(ARTIFACT_CHECKS_BY_FORMAT_V1["pdf"])


class TestHwpChecks:
    def test_proof_steps_merge_with_pdf_evidence(self, tmp_path):
        proof = {"checks": {"HWP_ACTUAL_REOPEN": "PASSED",
                            "FORMAT_OPEN_VALIDITY": "PASSED"}}
        checks = hwp_checks(tmp_path / "a.hwp", tmp_path / "a.pdf", _doc(), proof)
        assert checks["HWP_ACTUAL_REOPEN"] == "PASSED"
        # no pdf render → coverage unproven
        assert checks["ARTIFACT_SEMANTIC_COVERAGE"] == "NOT_RUN"

    def test_worker_proof_keys_not_in_schema_ignored(self, tmp_path):
        proof = {"checks": {"UNKNOWN_CHECK": "PASSED"}}
        checks = hwp_checks(tmp_path / "a.hwp", tmp_path / "a.pdf", _doc(), proof)
        assert set(checks) == set(ARTIFACT_CHECKS_BY_FORMAT_V1["hwp"])


class _FakeService:
    def __init__(self):
        self.artifacts = []
        self.proofs = {}

    def register_draft_artifact(self, tenant_id, doc_id, rev_id, fmt,
                                blob_key, sha, size, output_mode="M"):
        art = SimpleNamespace(
            id=f"art-{fmt}", tenant_id=tenant_id, document_id=doc_id,
            revision_id=rev_id, format=fmt, artifact_sha256=sha,
        )
        self.artifacts.append(art)
        return art

    def record_proof(self, artifact_id, checks, worker_identity=""):
        self.proofs[artifact_id] = {"checks": checks, "worker": worker_identity}


class _FakeObjects:
    def __init__(self, root):
        self.root = root

    def put(self, key, data):
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key


class _FakeStore:
    def __init__(self, export_dir):
        self._dir = export_dir

    def export_dir(self, doc_id):
        return self._dir


def _ctx(tmp_path):
    export = tmp_path / "export"
    export.mkdir()
    (export / "exam.hwpx").write_bytes(render_hwpx(_doc()))
    doc = _doc()
    doc.id = "d1"
    return SimpleNamespace(document=doc), _FakeStore(export)


def test_register_pipeline_artifacts_no_worker(tmp_path, monkeypatch):
    """Hancom unavailable → hwpx registered, hwp/pdf absent, nothing
    silently claimed."""
    from renderers.hwp.worker import WindowsHWPWorker

    monkeypatch.setattr(WindowsHWPWorker, "is_available", staticmethod(lambda: False))
    ctx, store = _ctx(tmp_path)
    service = _FakeService()
    objects = _FakeObjects(tmp_path / "objs")
    job = SimpleNamespace(tenant_id="t1")

    arts = register_pipeline_artifacts(service, objects, store, ctx, job,
                                       rev=SimpleNamespace(id="r1"))
    assert [a.format for a in arts] == ["hwpx"]
    proof = service.proofs["art-hwpx"]
    assert proof["checks"]["FORMAT_OPEN_VALIDITY"] == "PASSED"
    assert proof["checks"]["RENDERED_TEXT_VISUAL_MATCH"] == "NOT_RUN"


def test_register_pipeline_artifacts_with_worker(tmp_path, monkeypatch):
    """A real worker path registers all three formats with bound proofs."""
    from renderers.hwp.worker import WindowsHWPWorker

    def _fake(self, hwpx_path, out_hwp, out_pdf, request_revision=""):
        out_hwp.write_bytes(b"HWP_BINARY")
        out_pdf.write_bytes(b"%PDF-1.4 fake")
        return {"checks": {"HWP_ACTUAL_REOPEN": "PASSED",
                           "FORMAT_OPEN_VALIDITY": "PASSED"},
                "worker_identity": "w1"}

    monkeypatch.setattr(WindowsHWPWorker, "is_available", staticmethod(lambda: True))
    monkeypatch.setattr(WindowsHWPWorker, "convert_with_proof", _fake)
    ctx, store = _ctx(tmp_path)
    service = _FakeService()
    objects = _FakeObjects(tmp_path / "objs")
    job = SimpleNamespace(tenant_id="t1")

    arts = register_pipeline_artifacts(service, objects, store, ctx, job,
                                       rev=SimpleNamespace(id="r1"))
    assert sorted(a.format for a in arts) == ["hwp", "hwpx", "pdf"]
    assert service.proofs["art-hwp"]["checks"]["HWP_ACTUAL_REOPEN"] == "PASSED"
    # the fake pdf has no real text → coverage not claimed as PASSED
    assert service.proofs["art-pdf"]["checks"]["ARTIFACT_SEMANTIC_COVERAGE"] != "PASSED"


def test_no_hwpx_registers_nothing(tmp_path):
    ctx, store = _ctx(tmp_path)
    (store._dir / "exam.hwpx").unlink()
    service = _FakeService()
    arts = register_pipeline_artifacts(
        service, _FakeObjects(tmp_path / "o"), store, ctx,
        SimpleNamespace(tenant_id="t"), SimpleNamespace(id="r"))
    assert arts == []
    assert service.artifacts == []
