from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EXAMDNA_DATA", str(tmp_path / "data"))
    import app.deps as deps

    deps.reset()
    import app.api.uploads as uploads_api

    monkeypatch.setattr(uploads_api, "run_once", lambda *a, **k: False)
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
    deps.reset()


def _h(user: str, tenant: str | None = None) -> dict[str, str]:
    headers = {"x-dev-user": user}
    if tenant:
        headers["x-dev-tenant"] = tenant
    return headers


def _make_tenant(client, user: str, name: str = "학원") -> str:
    res = client.post("/api/tenants", json={"name": name}, headers=_h(user))
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _upload(client, user: str, tenant: str, filename: str = "page.png"):
    res = client.post(
        "/api/uploads",
        files=[("files", (filename, _png_bytes(), "image/png"))],
        headers=_h(user, tenant),
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_unauthenticated_is_denied(client):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/documents/doc_x").status_code == 401
    assert client.get("/api/jobs/job_x").status_code == 401
    assert client.post("/api/uploads", files=[]).status_code == 401


def test_tenant_create_and_membership(client):
    tenant = _make_tenant(client, "alice")
    res = client.get("/api/tenants", headers=_h("alice"))
    assert res.status_code == 200
    assert res.json()["tenants"][0]["id"] == tenant
    assert res.json()["tenants"][0]["role"] == "owner"
    # bob is not a member
    res = client.post(
        "/api/tenants/switch",
        json={"tenant_id": tenant},
        headers=_h("bob"),
    )
    assert res.status_code == 403


def test_upload_scopes_document_to_tenant(client):
    tenant = _make_tenant(client, "alice")
    out = _upload(client, "alice", tenant)
    doc_id, job_id = out["document_id"], out["job_id"]

    listed = client.get("/api/documents", headers=_h("alice", tenant)).json()
    assert [d["id"] for d in listed["documents"]] == [doc_id]

    # owner can read
    assert client.get(f"/api/documents/{doc_id}", headers=_h("alice")).status_code == 200
    assert client.get(f"/api/jobs/{job_id}", headers=_h("alice")).status_code == 200


def test_cross_tenant_access_denied(client):
    tenant = _make_tenant(client, "alice")
    out = _upload(client, "alice", tenant)
    doc_id, job_id = out["document_id"], out["job_id"]

    # bob: not a member anywhere — every document/job route must 404
    for url in (
        f"/api/documents/{doc_id}",
        f"/api/documents/{doc_id}/preview",
        f"/api/documents/{doc_id}/crops/0",
        f"/api/documents/{doc_id}/review-items",
        f"/api/documents/{doc_id}/files/exam.hwpx",
        f"/api/jobs/{job_id}",
        f"/api/jobs/{job_id}/events",
    ):
        res = client.get(url, headers=_h("bob"))
        assert res.status_code == 404, f"{url} -> {res.status_code}"

    for url in (
        f"/api/documents/{doc_id}/review-items/atu_x",
        f"/api/documents/{doc_id}/edits",
        f"/api/documents/{doc_id}/exports",
    ):
        res = client.post(url, json={}, headers=_h("bob"))
        assert res.status_code == 404, f"{url} -> {res.status_code}"

    # bob's library is empty
    tenant_b = _make_tenant(client, "bob", "다른학원")
    listed = client.get("/api/documents", headers=_h("bob", tenant_b)).json()
    assert listed["documents"] == []


def test_legacy_document_is_not_auto_public(client):
    tenant = _make_tenant(client, "alice")
    # document written without tenant_id (pre-WP01 shape)
    from document.models import Document
    from app.deps import get_store

    legacy = Document()
    get_store().save_document(legacy)

    res = client.get(f"/api/documents/{legacy.id}", headers=_h("alice", tenant))
    assert res.status_code == 404
    listed = client.get("/api/documents", headers=_h("alice", tenant)).json()
    assert all(d["id"] != legacy.id for d in listed["documents"])


def test_invite_and_reviewer_permissions(client):
    tenant = _make_tenant(client, "alice")
    out = _upload(client, "alice", tenant)
    doc_id = out["document_id"]

    # owner invites carol as reviewer
    inv = client.post(
        f"/api/tenants/{tenant}/invites",
        json={"role": "reviewer"},
        headers=_h("alice"),
    )
    assert inv.status_code == 200, inv.text
    code = inv.json()["code"]

    res = client.post(f"/api/invites/{code}/accept", headers=_h("carol"))
    assert res.status_code == 200, res.text
    assert res.json()["role"] == "reviewer"

    # reviewer can read/review but not mutate, export, or download binaries
    assert client.get(f"/api/documents/{doc_id}", headers=_h("carol")).status_code == 200
    assert (
        client.get(f"/api/documents/{doc_id}/review-items", headers=_h("carol")).status_code
        == 200
    )
    assert (
        client.get(f"/api/documents/{doc_id}/crops/0", headers=_h("carol")).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/documents/{doc_id}/exports",
            json={"format": "hwpx"},
            headers=_h("carol"),
        ).status_code
        == 403
    )
    assert (
        client.get(f"/api/documents/{doc_id}/files/exam.hwpx", headers=_h("carol")).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/documents/{doc_id}/review-items/atu_x",
            json={"value": "1"},
            headers=_h("carol"),
        ).status_code
        == 403
    )
    # reviewer cannot upload
    res = client.post(
        "/api/uploads",
        files=[("files", ("p.png", _png_bytes(), "image/png"))],
        headers=_h("carol", tenant),
    )
    assert res.status_code == 403


def test_teacher_can_edit_and_export(client):
    tenant = _make_tenant(client, "alice")
    out = _upload(client, "alice", tenant)
    doc_id = out["document_id"]

    inv = client.post(
        f"/api/tenants/{tenant}/invites",
        json={"role": "teacher"},
        headers=_h("alice"),
    )
    code = inv.json()["code"]
    client.post(f"/api/invites/{code}/accept", headers=_h("dave"))

    res = client.post(
        f"/api/documents/{doc_id}/exports",
        json={"format": "hwpx"},
        headers=_h("dave"),
    )
    assert res.status_code == 200, res.text
    # and the generated file downloads for a teacher
    res = client.get(f"/api/documents/{doc_id}/files/exam.hwpx", headers=_h("dave"))
    assert res.status_code == 200


def test_audit_log_written(client):
    tenant = _make_tenant(client, "alice")
    out = _upload(client, "alice", tenant)

    res = client.get(f"/api/tenants/{tenant}/audit", headers=_h("alice"))
    assert res.status_code == 200
    actions = [e["action"] for e in res.json()["events"]]
    assert "tenant.create" in actions
    assert "document.upload" in actions

    # non-owner cannot read the audit log
    inv = client.post(
        f"/api/tenants/{tenant}/invites",
        json={"role": "teacher"},
        headers=_h("alice"),
    ).json()
    client.post(f"/api/invites/{inv['code']}/accept", headers=_h("dave"))
    assert (
        client.get(f"/api/tenants/{tenant}/audit", headers=_h("dave")).status_code == 403
    )


def test_upload_filename_sanitized(client):
    tenant = _make_tenant(client, "alice")
    res = client.post(
        "/api/uploads",
        files=[("files", ("../../../evil.png", _png_bytes(), "image/png"))],
        headers=_h("alice", tenant),
    )
    assert res.status_code == 200, res.text
    # nothing may land outside the object store root
    import os

    data = Path(os.environ["EXAMDNA_DATA"])
    objects = data / "objects"
    assert objects.exists()
    for p in data.rglob("*.png"):
        assert objects in p.parents, f"unsafe write outside object store: {p}"


def test_no_active_tenant_rejected(client):
    _make_tenant(client, "alice")
    res = client.post(
        "/api/uploads",
        files=[("files", ("p.png", _png_bytes(), "image/png"))],
        headers=_h("alice"),  # authenticated but no active tenant
    )
    assert res.status_code == 400
