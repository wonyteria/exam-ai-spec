"""Import legacy file-JSON documents into an academy (WP01).

Documents stored before tenancy have no tenant_id. They are invisible to
the API until an operator explicitly maps them to an academy — this script
is that explicit step. It never auto-assigns ownership.

Usage:
    python backend/scripts/import_legacy.py --data DIR [--tenant TENANT_ID] [--apply]

Without --apply it only reports. With --apply it:
  1. backs up every document JSON to <data>/legacy_backup_<ts>/
  2. sets tenant_id on each unmigrated document
  3. writes an audit event per document
  4. re-reads every file and verifies the mapping
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from document.models import Document
from jobs.store import Store
from tenancy.db import TenancyDB
from tenancy.models import AuditEvent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="backend data dir")
    ap.add_argument("--tenant", help="tenant id to assign (required with --apply)")
    ap.add_argument("--apply", action="store_true", help="perform the mapping")
    args = ap.parse_args()

    data_dir = Path(args.data)
    store = Store(data_dir)
    db = TenancyDB(data_dir / "tenancy.db")

    unmigrated = store.list_unmigrated()
    print(f"unmigrated documents: {len(unmigrated)}")
    for d in unmigrated:
        print(f"  {d.id} pages={len(d.pages)} questions={len(d.questions)}")

    if not args.apply:
        print("dry run — pass --apply --tenant <id> to map these documents")
        return 0

    if not args.tenant:
        print("error: --tenant is required with --apply", file=sys.stderr)
        return 2
    if db.get_tenant(args.tenant) is None:
        print(f"error: tenant {args.tenant} does not exist", file=sys.stderr)
        return 2

    backup = data_dir / f"legacy_backup_{int(time.time())}"
    backup.mkdir(parents=True)
    docs_dir = data_dir / "documents"

    for d in unmigrated:
        src = docs_dir / f"{d.id}.json"
        shutil.copy2(src, backup / src.name)
        d.tenant_id = args.tenant
        src.write_text(d.model_dump_json(indent=2), encoding="utf-8")
        db.audit(
            AuditEvent(
                tenant_id=args.tenant,
                user_id="import_legacy",
                action="document.migrate",
                object_type="document",
                object_id=d.id,
                detail={"backup": str(backup)},
            )
        )

    # verification pass: every file must re-parse with the right tenant
    failures = []
    for d in unmigrated:
        loaded = Document.model_validate_json(
            (docs_dir / f"{d.id}.json").read_text(encoding="utf-8")
        )
        if loaded.tenant_id != args.tenant:
            failures.append(d.id)

    remaining = store.list_unmigrated()
    print(f"mapped: {len(unmigrated) - len(remaining)}")
    print(f"backup: {backup}")
    if failures or remaining:
        print(f"FAILED: failures={failures} remaining={[d.id for d in remaining]}")
        return 1
    print("verification ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
