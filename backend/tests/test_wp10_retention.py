"""WP10 — retention sweep + backup verification."""
from __future__ import annotations

import time

from canonical.models import LifecycleState
from canonical.store import CanonicalStore
from canonical.service import MutationService
from document.models import Document, Question
from tenancy.db import TenancyDB
from tenancy.retention import create_backup, sweep_expired, verify_backup


def _setup(tmp_path):
    store = CanonicalStore(tmp_path / "c.db")
    svc = MutationService(store, TenancyDB(tmp_path / "t.db"))
    doc = Document(tenant_id="t1")
    doc.questions = [Question(number=1)]
    svc.create_revision(doc, "t1", "a")
    return store, doc


def test_expired_deleted_doc_is_purged(tmp_path):
    store, doc = _setup(tmp_path)
    store.set_lifecycle_state(
        doc.id, LifecycleState.DELETED, retention_deadline=time.time() - 1
    )
    purged = sweep_expired(store)
    assert purged == [doc.id]
    rec = store.get_document(doc.id)
    assert rec.lifecycle_state == LifecycleState.PURGED
    # revision rows survive but payloads are stripped
    rev = store.get_head_revision(doc.id)
    assert rev.content_json == {}


def test_active_or_future_deadline_untouched(tmp_path):
    store, doc = _setup(tmp_path)
    # ACTIVE doc must never purge
    assert sweep_expired(store) == []
    # DELETED but deadline in the future — retained
    store.set_lifecycle_state(
        doc.id, LifecycleState.DELETED,
        retention_deadline=time.time() + 3600,
    )
    assert sweep_expired(store) == []
    assert store.get_document(doc.id).lifecycle_state == LifecycleState.DELETED
    assert store.get_head_revision(doc.id).content_json != {}


def test_backup_roundtrip_verify(tmp_path):
    src = tmp_path / "data"
    (src / "jobs").mkdir(parents=True)
    (src / "jobs" / "j1.json").write_text('{"a":1}', encoding="utf-8")
    (src / "canonical.db").write_bytes(b"dbbytes")
    dst = tmp_path / "backup1"
    manifest = create_backup(src, dst)
    assert "jobs/j1.json" in manifest or "jobs\\j1.json" in manifest
    result = verify_backup(dst)
    assert result["valid"] and result["ok"] == 2


def test_backup_detects_corruption(tmp_path):
    src = tmp_path / "data"
    src.mkdir()
    (src / "f.bin").write_bytes(b"original")
    dst = tmp_path / "backup2"
    create_backup(src, dst)
    (dst / "f.bin").write_bytes(b"tampered")
    result = verify_backup(dst)
    assert not result["valid"]
    assert "f.bin" in result["mismatched"]
