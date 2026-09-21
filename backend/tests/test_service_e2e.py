"""Service-path E2E: real HTTP upload -> canonical worker -> revision ->
review items -> eligibility, exercised through the FastAPI app itself
(TestClient) rather than the legacy run_pipeline shortcut.

The upload handler spawns run_once in a daemon thread; here we intercept
that spawn and run the real worker synchronously so the test is
deterministic. Providers are the default mocks (no real OCR) so the test
stays fast — the heavy-provider variant lives in scripts/service_e2e.py.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXAMDNA_DATA", str(tmp_path / "data"))
    import app.deps as deps

    deps.reset()
    import app.api.uploads as uploads_api

    spawned: list[tuple] = []
    monkeypatch.setattr(
        uploads_api, "run_once", lambda *a, **k: spawned.append((a, k))
    )
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c, deps, spawned
    deps.reset()


def test_upload_worker_revision_review_items(env):
    client, deps, spawned = env
    h = {"X-Dev-User": "e2e"}
    tenant_id = client.post(
        "/api/tenants", json={"name": "E2E"}, headers=h
    ).json()["id"]
    h["X-Dev-Tenant"] = tenant_id

    up = client.post(
        "/api/uploads",
        files=[("files", ("p1.png", _png_bytes(), "image/png"))],
        headers=h,
    )
    assert up.status_code == 200, up.text
    doc_id = up.json()["document_id"]
    job_id = up.json()["job_id"]
    # The handler requested a worker run inside the server.
    assert spawned, "upload handler must spawn the canonical worker"

    # Run the claimed job synchronously with default (mock) providers.
    from jobs.worker import run_once

    claimed = run_once(
        deps.get_canonical(),
        deps.get_store(),
        deps.get_object_store(),
        deps.get_tenancy(),
        "test-worker",
    )
    assert claimed is True, "queued job must be claimable"

    job = client.get(f"/api/jobs/{job_id}", headers=h).json()
    assert job["state"] in {"COMPLETED", "NEEDS_REVIEW"}, job

    revs = client.get(
        f"/api/v1/tenants/{tenant_id}/documents/{doc_id}/revisions", headers=h
    ).json()["data"]["revisions"]
    assert len(revs) >= 2, "upload revision + pipeline output revision"

    review = client.get(
        f"/api/documents/{doc_id}/review-items", headers=h
    )
    assert review.status_code == 200, review.text
    body = review.json()
    assert "items" in body and "missing_numbers" in body

    # Resolving a review item is a canonical mutation: ResolveATU -> new
    # revision via the review endpoint (not a flat field update).
    if body["items"]:
        atu_id = body["items"][0]["atu_id"]
        res = client.post(
            f"/api/documents/{doc_id}/review-items/{atu_id}",
            json={"value": "1"}, headers=h,
        )
        assert res.status_code == 200, res.text
        assert res.json() == {"ok": True, "revisioned": True}
        revs2 = client.get(
            f"/api/v1/tenants/{tenant_id}/documents/{doc_id}/revisions",
            headers=h,
        ).json()["data"]["revisions"]
        assert len(revs2) == len(revs) + 1

    elig = client.get(
        f"/api/v1/tenants/{tenant_id}/documents/{doc_id}/eligibility",
        headers=h,
    ).json()["data"]
    assert elig["content_ready"] is False
    assert elig["revision_no"] >= 2


def test_review_item_resolve_over_http(env):
    """Deterministic review-resolution check: seed a doc with an
    UNVERIFIED ATU, confirm it surfaces via GET review-items, resolve it
    over POST, and assert a new canonical revision."""
    client, deps, _ = env
    h = {"X-Dev-User": "e2e"}
    tenant_id = client.post(
        "/api/tenants", json={"name": "E2E"}, headers=h
    ).json()["id"]
    h["X-Dev-Tenant"] = tenant_id

    from canonical.service import MutationService
    from document.models import ATU, ATUKind, Document, Question, TextSpan

    doc = Document(tenant_id=tenant_id)
    doc.questions.append(
        Question(
            number=1,
            label="1",
            body=[TextSpan(text="문제 본문")],
            atus=[ATU(kind=ATUKind.TEXT_TOKEN, field="body", value="본문?")],
        )
    )
    deps.get_store().save_document(doc)
    service = MutationService(deps.get_canonical(), deps.get_tenancy())
    rev1 = service.create_revision(doc, tenant_id, "e2e")
    atu_id = doc.questions[0].atus[0].id

    body = client.get(
        f"/api/documents/{doc.id}/review-items", headers=h
    ).json()
    assert [i["atu_id"] for i in body["items"]] == [atu_id]
    assert body["items"][0]["status"] == "UNVERIFIED"

    res = client.post(
        f"/api/documents/{doc.id}/review-items/{atu_id}",
        json={"value": "확정 본문"}, headers=h,
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True, "revisioned": True}

    cstore = deps.get_canonical()
    head = cstore.get_head_revision(doc.id)
    assert head.id != rev1.id and head.revision_no == 2
    resolved = Document.model_validate(head.content_json).questions[0].atus[0]
    assert resolved.value == "확정 본문"
    assert resolved.status.value == "HUMAN_VERIFIED"

    # The resolved ATU no longer appears as a review item.
    body2 = client.get(
        f"/api/documents/{doc.id}/review-items", headers=h
    ).json()
    assert body2["items"] == []


def test_renumber_masked_question_over_http(env):
    """The review UI's number-confirmation flow: SetField number via the
    canonical /changes endpoint under If-Match, then the canonical-aware
    read model must show the confirmed label everywhere."""
    client, deps, _ = env
    h = {"X-Dev-User": "e2e"}
    tenant_id = client.post(
        "/api/tenants", json={"name": "E2E"}, headers=h
    ).json()["id"]
    h["X-Dev-Tenant"] = tenant_id

    from canonical.service import MutationService
    from document.models import Document, Question, TextSpan

    doc = Document(tenant_id=tenant_id)
    doc.questions.extend(
        [
            Question(number=3, label="3", body=[TextSpan(text="앞 문항")]),
            Question(
                number=99,
                label="?mark1",
                body=[TextSpan(text="번호 가려진 문항")],
            ),
            Question(number=5, label="5", body=[TextSpan(text="뒤 문항")]),
        ]
    )
    deps.get_store().save_document(doc)
    service = MutationService(deps.get_canonical(), deps.get_tenancy())
    service.create_revision(doc, tenant_id, "e2e")

    head = client.get(
        f"/api/v1/tenants/{tenant_id}/documents/{doc.id}/revisions",
        headers=h,
    ).json()["data"]["revisions"][-1]

    # Exact op shape the frontend renumberQuestion() helper sends.
    res = client.post(
        f"/api/v1/tenants/{tenant_id}/documents/{doc.id}/changes",
        json={
            "ops": [
                {
                    "op": "SetField",
                    "target_id": "?mark1",
                    "field": "number",
                    "value": 4,
                }
            ]
        },
        headers={**h, "If-Match": head["id"]},
    )
    assert res.status_code == 200, res.text

    # Canonical-aware read model: get_document shows label 4, re-sorted.
    got = client.get(f"/api/documents/{doc.id}", headers=h).json()
    assert [q["label"] for q in got["questions"]] == ["3", "4", "5"]

    # Duplicate number is a conflict, not a silent merge.
    head2 = client.get(
        f"/api/v1/tenants/{tenant_id}/documents/{doc.id}/revisions",
        headers=h,
    ).json()["data"]["revisions"][-1]
    dup = client.post(
        f"/api/v1/tenants/{tenant_id}/documents/{doc.id}/changes",
        json={
            "ops": [
                {
                    "op": "SetField",
                    "target_id": "3",
                    "field": "number",
                    "value": 4,
                }
            ]
        },
        headers={**h, "If-Match": head2["id"]},
    )
    assert dup.status_code == 409, dup.text
