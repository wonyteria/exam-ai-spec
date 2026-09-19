from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canonical.models import CheckRun, CheckState
from canonical.policy import restore_policy


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXAMDNA_DATA", str(tmp_path / "data"))
    import app.deps as deps

    deps.reset()
    import app.api.uploads as uploads_api

    monkeypatch.setattr(uploads_api, "run_once", lambda *a, **k: False)
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c, deps, monkeypatch
    deps.reset()


def _setup_doc(client):
    h = {"X-Dev-User": "u1"}
    client.post("/api/auth/dev-login", json={"user_id": "u1", "name": "Alice"})
    tid = client.post("/api/tenants", json={"name": "A"}, headers=h).json()["id"]
    up = client.post(
        "/api/uploads",
        files=[("files", ("p1.png", _png_bytes(), "image/png"))],
        headers=h,
    )
    assert up.status_code == 200, up.text
    return tid, up.json()["document_id"], h


def _pass_content_checks(cstore, rev, tenant_id):
    for kind in restore_policy().required_content_checks:
        cstore.upsert_check(
            CheckRun(
                tenant_id=tenant_id,
                revision_id=rev.id,
                check_kind=kind,
                input_digest=rev.content_hash,
                state=CheckState.PASSED,
            )
        )


def test_wp08_hwp_worker_artifact_proof_and_final_download(env):
    client, deps, monkeypatch = env
    tenant_id, doc_id, h = _setup_doc(client)
    cstore = deps.get_canonical()
    rev = cstore.get_head_revision(doc_id)
    _pass_content_checks(cstore, rev, tenant_id)

    required = restore_policy().required_artifact_checks_by_format["hwp"]

    def _fake_convert(self, hwpx, out_hwp, out_pdf, request_revision=""):
        out_hwp.write_bytes(b"HWP_BINARY")
        out_pdf.write_bytes(b"%PDF-1.4\n%FAKE")
        return {
            "checks": {k: "PASSED" for k in required},
            "worker_identity": "fake-hwp-worker",
            "request_revision": request_revision,
            "step_returns": {
                "open_hwpx": True,
                "saveas_hwp": True,
                "reopen_hwp": True,
                "saveas_pdf": True,
            },
        }

    from renderers.hwp.worker import WindowsHWPWorker

    monkeypatch.setattr(WindowsHWPWorker, "is_available", staticmethod(lambda: True))
    monkeypatch.setattr(WindowsHWPWorker, "convert_with_proof", _fake_convert)

    r = client.post(
        f"/api/v1/tenants/{tenant_id}/documents/{doc_id}/artifacts",
        json={"revision_id": rev.id, "format": "hwp"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    art = r.json()["data"]["artifact"]
    proof = cstore.get_proof_for_artifact(art["id"])
    assert proof is not None
    assert proof.revision_id == rev.id
    assert proof.checks["HWP_ACTUAL_REOPEN"] == "PASSED"
    proof_out = r.json()["data"]["proof"]
    assert proof_out["request_revision"] == rev.id
    assert proof_out["step_returns"]["open_hwpx"] is True
    manifest_key = proof_out["manifest_blob_key"]
    manifest = json.loads(deps.get_object_store().open(manifest_key).read_text(encoding="utf-8"))
    assert manifest["tenant_id"] == tenant_id
    assert manifest["request_revision_id"] == rev.id
    assert manifest["artifact_revision_id"] == rev.id
    assert manifest["artifact_sha256"] == art["artifact_sha256"]
    assert manifest["content_hash"] == art["content_hash"]

    exp = client.post(
        f"/api/v1/tenants/{tenant_id}/documents/{doc_id}/exports",
        json={"revision_id": rev.id, "artifact_ids": [art["id"]]},
        headers=h,
    )
    assert exp.status_code == 200, exp.text
    dl = client.get(exp.json()["data"]["artifacts"][0]["download_url"], headers=h)
    assert dl.status_code == 200
    assert dl.content == b"HWP_BINARY"


def test_wp08_hwp_worker_unavailable_blocks_format(env, monkeypatch):
    client, deps, _ = env
    tenant_id, doc_id, h = _setup_doc(client)
    cstore = deps.get_canonical()
    rev = cstore.get_head_revision(doc_id)
    from renderers.hwp.worker import WindowsHWPWorker

    monkeypatch.setattr(WindowsHWPWorker, "is_available", staticmethod(lambda: False))
    r = client.post(
        f"/api/v1/tenants/{tenant_id}/documents/{doc_id}/artifacts",
        json={"revision_id": rev.id, "format": "hwp"},
        headers=h,
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error"]["code"] == "HWP_WORKER_UNAVAILABLE"


def test_wp08_stale_hash_blocks_final_download(env):
    client, deps, monkeypatch = env
    tenant_id, doc_id, h = _setup_doc(client)
    cstore = deps.get_canonical()
    rev = cstore.get_head_revision(doc_id)
    _pass_content_checks(cstore, rev, tenant_id)
    required = restore_policy().required_artifact_checks_by_format["hwp"]

    def _fake_convert(self, hwpx, out_hwp, out_pdf, request_revision=""):
        out_hwp.write_bytes(b"HWP_BINARY")
        out_pdf.write_bytes(b"%PDF-1.4\n%FAKE")
        return {"checks": {k: "PASSED" for k in required}, "worker_identity": "fake"}

    from renderers.hwp.worker import WindowsHWPWorker

    monkeypatch.setattr(WindowsHWPWorker, "is_available", staticmethod(lambda: True))
    monkeypatch.setattr(WindowsHWPWorker, "convert_with_proof", _fake_convert)
    r = client.post(
        f"/api/v1/tenants/{tenant_id}/documents/{doc_id}/artifacts",
        json={"revision_id": rev.id, "format": "hwp"},
        headers=h,
    )
    art = r.json()["data"]["artifact"]
    exp = client.post(
        f"/api/v1/tenants/{tenant_id}/documents/{doc_id}/exports",
        json={"revision_id": rev.id, "artifact_ids": [art["id"]]},
        headers=h,
    )
    assert exp.status_code == 200, exp.text
    blob = deps.get_object_store().open(art["blob_key"])
    blob.write_bytes(b"TAMPERED")
    dl = client.get(exp.json()["data"]["artifacts"][0]["download_url"], headers=h)
    assert dl.status_code == 409
    assert dl.json()["detail"]["error"]["code"] == "HASH_MISMATCH"


def test_wp08_cross_tenant_manifest_inaccessible(env):
    client, deps, monkeypatch = env
    tenant_a, doc_id, h = _setup_doc(client)
    cstore = deps.get_canonical()
    rev = cstore.get_head_revision(doc_id)
    _pass_content_checks(cstore, rev, tenant_a)
    required = restore_policy().required_artifact_checks_by_format["hwp"]

    def _fake_convert(self, hwpx, out_hwp, out_pdf, request_revision=""):
        out_hwp.write_bytes(b"HWP_BINARY")
        out_pdf.write_bytes(b"%PDF-1.4\n%FAKE")
        return {"checks": {k: "PASSED" for k in required}, "worker_identity": "fake"}

    from renderers.hwp.worker import WindowsHWPWorker

    monkeypatch.setattr(WindowsHWPWorker, "is_available", staticmethod(lambda: True))
    monkeypatch.setattr(WindowsHWPWorker, "convert_with_proof", _fake_convert)
    r = client.post(
        f"/api/v1/tenants/{tenant_a}/documents/{doc_id}/artifacts",
        json={"revision_id": rev.id, "format": "hwp"},
        headers=h,
    )
    art = r.json()["data"]["artifact"]
    exp = client.post(
        f"/api/v1/tenants/{tenant_a}/documents/{doc_id}/exports",
        json={"revision_id": rev.id, "artifact_ids": [art["id"]]},
        headers=h,
    )
    url = exp.json()["data"]["artifacts"][0]["download_url"]
    client.post("/api/auth/dev-login", json={"user_id": "u2", "name": "Bob"})
    tenant_b = client.post("/api/tenants", json={"name": "B"}, headers={"X-Dev-User": "u2"}).json()["id"]
    denied = client.get(url, headers={"X-Dev-User": "u2", "X-Dev-Tenant": tenant_b})
    assert denied.status_code == 404
