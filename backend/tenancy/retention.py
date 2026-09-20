"""WP10 — retention sweep + backup snapshot.

Retention: documents in DELETED state whose retention_deadline has
passed transition to PURGED — revision payloads are stripped, but
revision rows + hashes remain so the purge is itself auditable.
Nothing is ever purged while ACTIVE or before its deadline.

Backup: file-level snapshot of the canonical DB and job/object data
with per-file SHA-256 manifest — verification re-hashes the copy.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from canonical.models import LifecycleState
from canonical.store import CanonicalStore


def sweep_expired(
    store: CanonicalStore, now: float | None = None
) -> list[str]:
    """Purge DELETED documents past their retention deadline.
    Returns the purged document ids."""
    now = time.time() if now is None else now
    purged: list[str] = []
    for rec in store.list_documents_by_state(LifecycleState.DELETED):
        if rec.retention_deadline is None or rec.retention_deadline > now:
            continue
        store.purge_revision_payloads(rec.id)
        store.set_lifecycle_state(rec.id, LifecycleState.PURGED)
        purged.append(rec.id)
    return purged


def create_backup(src_dir: Path, dst_dir: Path) -> dict:
    """Copy a data directory into a timestamped backup with a SHA-256
    manifest. Returns the manifest {files: {relpath: sha256}}."""
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    for path in sorted(Path(src_dir).rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src_dir)
        target = dst_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        manifest[str(rel)] = hashlib.sha256(
            target.read_bytes()
        ).hexdigest()
    manifest["_created_at"] = str(time.time())
    (dst_dir / "BACKUP_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def verify_backup(backup_dir: Path) -> dict:
    """Re-hash every file against the manifest — a corrupted copy is
    reported, never silently trusted."""
    backup_dir = Path(backup_dir)
    manifest = json.loads(
        (backup_dir / "BACKUP_MANIFEST.json").read_text(encoding="utf-8")
    )
    ok, mismatched, missing = [], [], []
    for rel, sha in manifest.items():
        if rel == "_created_at":
            continue
        target = backup_dir / rel
        if not target.exists():
            missing.append(rel)
        elif hashlib.sha256(target.read_bytes()).hexdigest() == sha:
            ok.append(rel)
        else:
            mismatched.append(rel)
    return {
        "ok": len(ok),
        "missing": missing,
        "mismatched": mismatched,
        "valid": not missing and not mismatched,
    }
