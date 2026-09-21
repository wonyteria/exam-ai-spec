from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .models import (
    Artifact,
    ArtifactProof,
    ArtifactState,
    CheckRun,
    CheckState,
    DocumentRecord,
    IdempotencyRecord,
    Issue,
    IssueState,
    JobEventRecord,
    JobV2,
    JobV2State,
    LifecycleState,
    Revision,
    RevisionMode,
    SourceAsset,
    SourceManifest,
    SourcePage,
    TERMINAL_JOB_STATES,
    canonical_json,
    new_id,
    sha256_json,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    head_revision_id TEXT,
    created_by TEXT NOT NULL DEFAULT '',
    lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE',
    lifecycle_version INTEGER NOT NULL DEFAULT 1,
    archived_at REAL,
    deleted_at REAL,
    retention_deadline REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents(tenant_id, lifecycle_state);
CREATE TABLE IF NOT EXISTS revisions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    revision_no INTEGER NOT NULL,
    parent_revision_id TEXT,
    mode TEXT NOT NULL,
    restore_baseline_revision_id TEXT,
    restores_revision_id TEXT,
    manifest_id TEXT,
    metadata_snapshot TEXT NOT NULL DEFAULT '{}',
    template_snapshot TEXT NOT NULL DEFAULT '{}',
    content_json TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL DEFAULT '',
    style_hash TEXT NOT NULL DEFAULT '',
    solution_hash TEXT NOT NULL DEFAULT '',
    policy_version TEXT NOT NULL DEFAULT '1',
    created_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    change_summary TEXT NOT NULL DEFAULT '[]',
    UNIQUE (document_id, revision_no)
);
CREATE INDEX IF NOT EXISTS idx_revisions_doc ON revisions(document_id, revision_no);
CREATE TABLE IF NOT EXISTS source_assets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    mime TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    original_name TEXT NOT NULL DEFAULT '',
    blob_key TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (tenant_id, sha256)
);
CREATE TABLE IF NOT EXISTS source_pages (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES documents(id),
    asset_id TEXT NOT NULL REFERENCES source_assets(id),
    pdf_page_index INTEGER,
    width_px INTEGER,
    height_px INTEGER,
    original_sha256 TEXT NOT NULL,
    original_name TEXT NOT NULL DEFAULT '',
    upload_index INTEGER NOT NULL DEFAULT 0,
    page_role TEXT NOT NULL DEFAULT 'UNKNOWN',
    role_source TEXT NOT NULL DEFAULT 'AUTO'
);
CREATE INDEX IF NOT EXISTS idx_source_pages_doc ON source_pages(document_id);
CREATE TABLE IF NOT EXISTS source_manifests (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES documents(id),
    page_ids_ordered TEXT NOT NULL DEFAULT '[]',
    missing_page_expectation TEXT,
    confirmed_by TEXT,
    confirmed_at REAL,
    digest TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_manifests_doc
    ON source_manifests(document_id, created_at);
CREATE TABLE IF NOT EXISTS checks (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    revision_id TEXT NOT NULL REFERENCES revisions(id),
    check_kind TEXT NOT NULL,
    input_digest TEXT NOT NULL DEFAULT '',
    validator_version TEXT NOT NULL DEFAULT '1',
    policy_version TEXT NOT NULL DEFAULT '1',
    state TEXT NOT NULL DEFAULT 'NOT_RUN',
    result_summary TEXT NOT NULL DEFAULT '',
    applicable INTEGER NOT NULL DEFAULT 1,
    stale_reason TEXT,
    method TEXT NOT NULL DEFAULT 'AUTO',
    started_at REAL,
    finished_at REAL,
    run_id TEXT,
    UNIQUE (revision_id, check_kind)
);
CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES revisions(id),
    question_ids TEXT NOT NULL DEFAULT '[]',
    object_ids TEXT NOT NULL DEFAULT '[]',
    kind TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'info',
    blocking INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'OPEN',
    reason TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    resolution_change_set_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_issues_revision ON issues(revision_id, state);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES documents(id),
    revision_id TEXT NOT NULL REFERENCES revisions(id),
    format TEXT NOT NULL,
    output_mode TEXT NOT NULL DEFAULT 'STUDENT_WITH_ENDNOTES',
    content_hash TEXT NOT NULL DEFAULT '',
    style_hash TEXT NOT NULL DEFAULT '',
    solution_hash TEXT NOT NULL DEFAULT '',
    template_version TEXT NOT NULL DEFAULT '1',
    renderer_version TEXT NOT NULL DEFAULT '1',
    artifact_sha256 TEXT NOT NULL DEFAULT '',
    blob_key TEXT NOT NULL DEFAULT '',
    byte_size INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'DRAFT',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_doc ON artifacts(document_id, revision_id);
CREATE TABLE IF NOT EXISTS artifact_proofs (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    artifact_sha256 TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    policy_digest TEXT NOT NULL DEFAULT '',
    checks TEXT NOT NULL DEFAULT '{}',
    worker_identity TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    input_revision_id TEXT,
    kind TEXT NOT NULL DEFAULT 'restore_pipeline',
    state TEXT NOT NULL DEFAULT 'QUEUED',
    current_stage TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    not_before REAL NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at REAL,
    heartbeat_at REAL,
    cancel_requested_at REAL,
    last_error TEXT,
    output_revision_id TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_claim
    ON jobs(state, not_before, priority, created_at);
CREATE TABLE IF NOT EXISTS job_events (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    seq INTEGER NOT NULL,
    ts REAL NOT NULL,
    event TEXT NOT NULL DEFAULT 'stage.progress',
    state TEXT,
    stage TEXT,
    revision_id TEXT,
    completed_units INTEGER,
    total_units INTEGER,
    error TEXT,
    data TEXT NOT NULL DEFAULT '{}',
    UNIQUE (job_id, seq)
);
CREATE TABLE IF NOT EXISTS idempotency (
    tenant_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    route TEXT NOT NULL,
    key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL DEFAULT '{}',
    resource_id TEXT,
    created_at REAL NOT NULL,
    PRIMARY KEY (tenant_id, actor, route, key)
);
"""

LEASE_SECONDS = 90.0


class ConflictError(Exception):
    """Expected-head / CAS mismatch -> HTTP 409."""

    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class PreconditionError(Exception):
    """Missing If-Match / precondition -> HTTP 428."""


class NotFoundError(Exception):
    pass


class ValidationError(Exception):
    """Bad request shape -> HTTP 422."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.details = details or {}


class IdempotencyConflictError(ConflictError):
    pass


class StaleWorkerError(ConflictError):
    pass


class CanonicalStore:
    """SQLite-backed canonical store: documents/revisions/checks/issues/
    artifacts/proofs/durable jobs/events/idempotency.

    This is the dev adapter for the contract in 02_ARCHITECTURE_CONTRACTS
    §4–§11 (ADR-0001): every mutation goes through the same transaction
    steps a Postgres implementation would use.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Additive column migrations for databases created before a
        schema version introduced them."""
        cols = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(revisions)")
        }
        if "manifest_id" not in cols:
            self._conn.execute(
                "ALTER TABLE revisions ADD COLUMN manifest_id TEXT"
            )
        sp_cols = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(source_pages)")
        }
        if "page_role" not in sp_cols:
            self._conn.execute(
                "ALTER TABLE source_pages ADD COLUMN page_role TEXT NOT NULL DEFAULT 'UNKNOWN'"
            )
        if "role_source" not in sp_cols:
            self._conn.execute(
                "ALTER TABLE source_pages ADD COLUMN role_source TEXT NOT NULL DEFAULT 'AUTO'"
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- document records -------------------------------------------------

    def create_document(self, tenant_id: str, created_by: str, doc_id: Optional[str] = None) -> DocumentRecord:
        rec = DocumentRecord(id=doc_id or new_id("doc"), tenant_id=tenant_id, created_by=created_by)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO documents
                   (id, tenant_id, head_revision_id, created_by, lifecycle_state,
                    lifecycle_version, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    rec.id,
                    rec.tenant_id,
                    rec.head_revision_id,
                    rec.created_by,
                    rec.lifecycle_state.value,
                    rec.lifecycle_version,
                    rec.created_at,
                ),
            )
        return rec

    def get_document(self, doc_id: str) -> Optional[DocumentRecord]:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["lifecycle_state"] = LifecycleState(d["lifecycle_state"])
        return DocumentRecord(**d)

    def get_head_revision(self, doc_id: str) -> Optional[Revision]:
        rec = self.get_document(doc_id)
        if rec is None or rec.head_revision_id is None:
            return None
        return self.get_revision(rec.head_revision_id)

    def set_lifecycle_state(
        self,
        doc_id: str,
        state: LifecycleState,
        retention_deadline: Optional[float] = None,
    ) -> None:
        """Lifecycle transition bumps lifecycle_version — the audit row
        records when the state actually changed."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                """UPDATE documents
                   SET lifecycle_state=?, lifecycle_version=lifecycle_version+1,
                       retention_deadline=COALESCE(?, retention_deadline)
                   WHERE id=?""",
                (state.value, retention_deadline, doc_id),
            )
            if cur.rowcount == 0:
                raise NotFoundError(f"document {doc_id} not found")

    def list_documents_by_state(
        self, state: LifecycleState
    ) -> list[DocumentRecord]:
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE lifecycle_state=?",
            (state.value,),
        ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["lifecycle_state"] = LifecycleState(d["lifecycle_state"])
            out.append(DocumentRecord(**d))
        return out

    def purge_revision_payloads(self, doc_id: str) -> int:
        """PURGED lifecycle: strip content_json from every revision —
        question content is gone, but the revision hash + audit chain
        survives so the purge itself is provable."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                """UPDATE revisions SET content_json='{}'
                   WHERE document_id=?""",
                (doc_id,),
            )
            return cur.rowcount

    def _cas_head(self, doc_id: str, expected_head: Optional[str], new_head: str) -> None:
        """Compare-and-swap the head pointer. Raises ConflictError on mismatch."""
        if expected_head is None:
            cur = self._conn.execute(
                "UPDATE documents SET head_revision_id=? WHERE id=? AND head_revision_id IS NULL",
                (new_head, doc_id),
            )
        else:
            cur = self._conn.execute(
                "UPDATE documents SET head_revision_id=? WHERE id=? AND head_revision_id=?",
                (new_head, doc_id, expected_head),
            )
        if cur.rowcount == 0:
            actual = self.get_document(doc_id)
            raise ConflictError(
                "REVISION_CONFLICT",
                "document head changed during mutation",
                {"current_revision_id": actual.head_revision_id if actual else None},
            )

    # ---- revisions -----------------------------------------------------------

    def insert_revision(self, rev: Revision, expected_head: Optional[str]) -> Revision:
        """Insert a revision and CAS the document head inside one transaction."""
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """INSERT INTO revisions
                       (id, document_id, revision_no, parent_revision_id, mode,
                        restore_baseline_revision_id, restores_revision_id,
                        manifest_id,
                        metadata_snapshot, template_snapshot, content_json,
                        content_hash, style_hash, solution_hash, policy_version,
                        created_by, created_at, change_summary)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        rev.id,
                        rev.document_id,
                        rev.revision_no,
                        rev.parent_revision_id,
                        rev.mode.value,
                        rev.restore_baseline_revision_id,
                        rev.restores_revision_id,
                        rev.manifest_id,
                        canonical_json(rev.metadata_snapshot),
                        canonical_json(rev.template_snapshot),
                        canonical_json(rev.content_json),
                        rev.content_hash,
                        rev.style_hash,
                        rev.solution_hash,
                        rev.policy_version,
                        rev.created_by,
                        rev.created_at,
                        canonical_json(rev.change_summary),
                    ),
                )
                self._cas_head(rev.document_id, expected_head, rev.id)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return rev

    def get_revision(self, revision_id: str) -> Optional[Revision]:
        row = self._conn.execute(
            "SELECT * FROM revisions WHERE id=?", (revision_id,)
        ).fetchone()
        return self._row_to_revision(row) if row else None

    def list_revisions(self, doc_id: str) -> list[Revision]:
        rows = self._conn.execute(
            "SELECT * FROM revisions WHERE document_id=? ORDER BY revision_no",
            (doc_id,),
        ).fetchall()
        return [self._row_to_revision(r) for r in rows]

    def _row_to_revision(self, row: sqlite3.Row) -> Revision:
        d = dict(row)
        d["mode"] = RevisionMode(d["mode"])
        for k in ("metadata_snapshot", "template_snapshot", "content_json", "change_summary"):
            d[k] = json.loads(d[k] or "{}")
        return Revision(**d)

    # ---- source assets / pages / manifests (WP03) --------------------------------

    def put_source_asset(self, asset: SourceAsset) -> SourceAsset:
        """Insert a source asset; identical bytes for the same tenant reuse
        the existing asset row (UNIQUE tenant+sha256 -> dedup/retry-safe)."""
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR IGNORE INTO source_assets
                   (id, tenant_id, sha256, mime, byte_size, original_name,
                    blob_key, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    asset.id,
                    asset.tenant_id,
                    asset.sha256,
                    asset.mime,
                    asset.byte_size,
                    asset.original_name,
                    asset.blob_key,
                    asset.created_at,
                ),
            )
            row = self._conn.execute(
                "SELECT * FROM source_assets WHERE tenant_id=? AND sha256=?",
                (asset.tenant_id, asset.sha256),
            ).fetchone()
        return SourceAsset(**dict(row))

    def get_source_asset(self, asset_id: str) -> Optional[SourceAsset]:
        row = self._conn.execute(
            "SELECT * FROM source_assets WHERE id=?", (asset_id,)
        ).fetchone()
        return SourceAsset(**dict(row)) if row else None

    def find_source_asset(
        self, tenant_id: str, sha256: str
    ) -> Optional[SourceAsset]:
        row = self._conn.execute(
            "SELECT * FROM source_assets WHERE tenant_id=? AND sha256=?",
            (tenant_id, sha256),
        ).fetchone()
        return SourceAsset(**dict(row)) if row else None

    def put_source_page(self, page: SourcePage) -> SourcePage:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO source_pages
                   (id, tenant_id, document_id, asset_id, pdf_page_index,
                    width_px, height_px, original_sha256, original_name,
                    upload_index, page_role, role_source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    page.id,
                    page.tenant_id,
                    page.document_id,
                    page.asset_id,
                    page.pdf_page_index,
                    page.width_px,
                    page.height_px,
                    page.original_sha256,
                    page.original_name,
                    page.upload_index,
                    page.page_role,
                    page.role_source,
                ),
            )
        return page

    def set_source_page_size(
        self, page_id: str, width_px: int, height_px: int
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE source_pages SET width_px=?, height_px=? WHERE id=?",
                (width_px, height_px, page_id),
            )

    def set_source_page_role(
        self, page_id: str, role: str, source: str
    ) -> Optional[SourcePage]:
        """User-confirmed (or re-classified) page role. Returns the updated
        row; role changes are recorded, never silently overwritten."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE source_pages SET page_role=?, role_source=? WHERE id=?",
                (role, source, page_id),
            )
        return self.get_source_page(page_id)

    def get_source_page(self, page_id: str) -> Optional[SourcePage]:
        row = self._conn.execute(
            "SELECT * FROM source_pages WHERE id=?", (page_id,)
        ).fetchone()
        return SourcePage(**dict(row)) if row else None

    def list_source_pages(self, doc_id: str) -> list[SourcePage]:
        rows = self._conn.execute(
            "SELECT * FROM source_pages WHERE document_id=? ORDER BY upload_index",
            (doc_id,),
        ).fetchall()
        return [SourcePage(**dict(r)) for r in rows]

    def create_manifest(self, manifest: SourceManifest) -> SourceManifest:
        """Persist a new manifest. The digest covers page order +
        expectation so any reorder produces a different digest."""
        manifest.digest = manifest.compute_digest()
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO source_manifests
                   (id, tenant_id, document_id, page_ids_ordered,
                    missing_page_expectation, confirmed_by, confirmed_at,
                    digest, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    manifest.id,
                    manifest.tenant_id,
                    manifest.document_id,
                    canonical_json(manifest.page_ids_ordered),
                    manifest.missing_page_expectation,
                    manifest.confirmed_by,
                    manifest.confirmed_at,
                    manifest.digest,
                    manifest.created_at,
                ),
            )
        return manifest

    def get_manifest(self, manifest_id: str) -> Optional[SourceManifest]:
        row = self._conn.execute(
            "SELECT * FROM source_manifests WHERE id=?", (manifest_id,)
        ).fetchone()
        return self._row_to_manifest(row) if row else None

    def latest_manifest(self, doc_id: str) -> Optional[SourceManifest]:
        row = self._conn.execute(
            """SELECT * FROM source_manifests
               WHERE document_id=? ORDER BY created_at DESC LIMIT 1""",
            (doc_id,),
        ).fetchone()
        return self._row_to_manifest(row) if row else None

    def _row_to_manifest(self, row: sqlite3.Row) -> SourceManifest:
        d = dict(row)
        d["page_ids_ordered"] = json.loads(d["page_ids_ordered"] or "[]")
        return SourceManifest(**d)

    # ---- checks -----------------------------------------------------------------

    def upsert_check(self, check: CheckRun) -> CheckRun:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO checks
                   (id, tenant_id, revision_id, check_kind, input_digest,
                    validator_version, policy_version, state, result_summary,
                    applicable, stale_reason, method, started_at, finished_at, run_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(revision_id, check_kind) DO UPDATE SET
                       input_digest=excluded.input_digest,
                       validator_version=excluded.validator_version,
                       policy_version=excluded.policy_version,
                       state=excluded.state,
                       result_summary=excluded.result_summary,
                       applicable=excluded.applicable,
                       stale_reason=excluded.stale_reason,
                       method=excluded.method,
                       started_at=excluded.started_at,
                       finished_at=excluded.finished_at,
                       run_id=excluded.run_id""",
                (
                    check.id,
                    check.tenant_id,
                    check.revision_id,
                    check.check_kind,
                    check.input_digest,
                    check.validator_version,
                    check.policy_version,
                    check.state.value,
                    check.result_summary,
                    1 if check.applicable else 0,
                    check.stale_reason,
                    check.method,
                    check.started_at,
                    check.finished_at,
                    check.run_id,
                ),
            )
        return check

    def get_checks(self, revision_id: str) -> list[CheckRun]:
        rows = self._conn.execute(
            "SELECT * FROM checks WHERE revision_id=?", (revision_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["state"] = CheckState(d["state"])
            d["applicable"] = bool(d["applicable"])
            out.append(CheckRun(**d))
        return out

    def mark_checks_stale(self, revision_id: str, kinds: list[str], reason: str) -> int:
        """Dependency invalidation: checks for invalidated inputs stay
        recorded but are marked stale — never silently deleted."""
        if not kinds:
            return 0
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"""UPDATE checks SET applicable=0, stale_reason=?
                    WHERE revision_id=? AND check_kind IN ({','.join('?' * len(kinds))})
                    AND applicable=1""",
                [reason, revision_id, *kinds],
            )
            return cur.rowcount

    # ---- issues ----------------------------------------------------------------

    def create_issue(self, issue: Issue) -> Issue:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO issues
                   (id, revision_id, question_ids, object_ids, kind, severity,
                    blocking, state, reason, actor, created_at, resolution_change_set_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    issue.id,
                    issue.revision_id,
                    canonical_json(issue.question_ids),
                    canonical_json(issue.object_ids),
                    issue.kind,
                    issue.severity,
                    1 if issue.blocking else 0,
                    issue.state.value,
                    issue.reason,
                    issue.actor,
                    issue.created_at,
                    issue.resolution_change_set_id,
                ),
            )
        return issue

    def get_issue(self, issue_id: str) -> Optional[Issue]:
        row = self._conn.execute(
            "SELECT * FROM issues WHERE id=?", (issue_id,)
        ).fetchone()
        return self._row_to_issue(row) if row else None

    def list_issues(
        self,
        revision_id: str,
        state: Optional[IssueState] = None,
        blocking_only: bool = False,
    ) -> list[Issue]:
        q = "SELECT * FROM issues WHERE revision_id=?"
        params: list[Any] = [revision_id]
        if state is not None:
            q += " AND state=?"
            params.append(state.value)
        if blocking_only:
            q += " AND blocking=1"
        rows = self._conn.execute(q, params).fetchall()
        return [self._row_to_issue(r) for r in rows]

    def set_issue_state(
        self, issue_id: str, state: IssueState, change_set_id: Optional[str] = None
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE issues SET state=?, resolution_change_set_id=? WHERE id=?",
                (state.value, change_set_id, issue_id),
            )

    def _row_to_issue(self, row: sqlite3.Row) -> Issue:
        d = dict(row)
        d["question_ids"] = json.loads(d["question_ids"] or "[]")
        d["object_ids"] = json.loads(d["object_ids"] or "[]")
        d["blocking"] = bool(d["blocking"])
        d["state"] = IssueState(d["state"])
        return Issue(**d)

    # ---- artifacts ---------------------------------------------------------------

    def create_artifact(self, art: Artifact) -> Artifact:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO artifacts
                   (id, tenant_id, document_id, revision_id, format, output_mode,
                    content_hash, style_hash, solution_hash, template_version,
                    renderer_version, artifact_sha256, blob_key, byte_size, state, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    art.id,
                    art.tenant_id,
                    art.document_id,
                    art.revision_id,
                    art.format,
                    art.output_mode,
                    art.content_hash,
                    art.style_hash,
                    art.solution_hash,
                    art.template_version,
                    art.renderer_version,
                    art.artifact_sha256,
                    art.blob_key,
                    art.byte_size,
                    art.state.value,
                    art.created_at,
                ),
            )
        return art

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE id=?", (artifact_id,)
        ).fetchone()
        return self._row_to_artifact(row) if row else None

    def list_artifacts(self, doc_id: str, revision_id: Optional[str] = None) -> list[Artifact]:
        if revision_id:
            rows = self._conn.execute(
                "SELECT * FROM artifacts WHERE document_id=? AND revision_id=?",
                (doc_id, revision_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM artifacts WHERE document_id=?", (doc_id,)
            ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def set_artifact_state(self, artifact_id: str, state: ArtifactState) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE artifacts SET state=? WHERE id=?", (state.value, artifact_id)
            )

    def _row_to_artifact(self, row: sqlite3.Row) -> Artifact:
        d = dict(row)
        d["state"] = ArtifactState(d["state"])
        return Artifact(**d)

    # ---- proofs ------------------------------------------------------------------

    def create_proof(self, proof: ArtifactProof) -> ArtifactProof:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO artifact_proofs
                   (id, artifact_id, artifact_sha256, revision_id, policy_digest,
                    checks, worker_identity, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    proof.id,
                    proof.artifact_id,
                    proof.artifact_sha256,
                    proof.revision_id,
                    proof.policy_digest,
                    canonical_json(proof.checks),
                    proof.worker_identity,
                    proof.created_at,
                ),
            )
        return proof

    def get_proof_for_artifact(self, artifact_id: str) -> Optional[ArtifactProof]:
        row = self._conn.execute(
            "SELECT * FROM artifact_proofs WHERE artifact_id=? ORDER BY created_at DESC LIMIT 1",
            (artifact_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["checks"] = json.loads(d["checks"] or "{}")
        return ArtifactProof(**d)

    # ---- durable jobs ---------------------------------------------------------------

    def create_job(self, job: JobV2) -> JobV2:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO jobs
                   (id, tenant_id, document_id, input_revision_id, kind, state,
                    current_stage, priority, created_by, idempotency_key,
                    attempt_count, not_before, lease_owner, lease_token,
                    lease_expires_at, heartbeat_at, cancel_requested_at,
                    last_error, output_revision_id, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job.id,
                    job.tenant_id,
                    job.document_id,
                    job.input_revision_id,
                    job.kind,
                    job.state.value,
                    job.current_stage,
                    job.priority,
                    job.created_by,
                    job.idempotency_key,
                    job.attempt_count,
                    job.not_before,
                    job.lease_owner,
                    job.lease_token,
                    job.lease_expires_at,
                    job.heartbeat_at,
                    job.cancel_requested_at,
                    job.last_error,
                    job.output_revision_id,
                    job.created_at,
                ),
            )
        return job

    def get_job(self, job_id: str) -> Optional[JobV2]:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, tenant_id: str, limit: int = 50) -> list[JobV2]:
        """Tenant-scoped job listing, newest first — for the library's
        in-flight work view. Never returns other tenants' jobs."""
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?",
            (tenant_id, limit),
        ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def claim_job(
        self, worker: str, kinds: Optional[list[str]] = None, lease_seconds: float = LEASE_SECONDS
    ) -> Optional[JobV2]:
        """Atomically claim the oldest runnable job. Returns the job with a
        fresh fencing token (lease_token) — every later write must present it."""
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                # RUNNING is included so a job whose lease expired (crashed or
                # stalled worker) can be reclaimed atomically without waiting
                # for the recovery sweeper.
                q = """SELECT * FROM jobs
                       WHERE state IN ('QUEUED','RETRY_SCHEDULED','WAITING_WORKER','RUNNING')
                         AND not_before <= ?
                         AND (lease_expires_at IS NULL OR lease_expires_at < ?)"""
                params: list[Any] = [now, now]
                if kinds:
                    q += f" AND kind IN ({','.join('?' * len(kinds))})"
                    params += kinds
                q += " ORDER BY priority DESC, created_at LIMIT 1"
                row = self._conn.execute(q, params).fetchone()
                if not row:
                    self._conn.execute("COMMIT")
                    return None
                job = self._row_to_job(row)
                token = new_id("lease")
                cur = self._conn.execute(
                    """UPDATE jobs SET state='RUNNING', lease_owner=?, lease_token=?,
                           lease_expires_at=?, heartbeat_at=?, attempt_count=attempt_count+1
                       WHERE id=? AND attempt_count=?""",
                    (
                        worker,
                        token,
                        now + lease_seconds,
                        now,
                        job.id,
                        job.attempt_count,
                    ),
                )
                if cur.rowcount == 0:
                    self._conn.execute("ROLLBACK")
                    return None
                self._conn.execute("COMMIT")
                job.state = JobV2State.RUNNING
                job.lease_owner = worker
                job.lease_token = token
                job.attempt_count += 1
                return job
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def heartbeat(self, job_id: str, lease_token: str, lease_seconds: float = LEASE_SECONDS) -> None:
        now = time.time()
        with self._lock, self._conn:
            cur = self._conn.execute(
                """UPDATE jobs SET heartbeat_at=?, lease_expires_at=?
                   WHERE id=? AND lease_token=? AND state='RUNNING'""",
                (now, now + lease_seconds, job_id, lease_token),
            )
            if cur.rowcount == 0:
                raise StaleWorkerError(
                    "STALE_LEASE", "lease token mismatch or job not running"
                )

    def _check_write_fence(self, job_id: str, lease_token: str) -> sqlite3.Row:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"job {job_id}")
        job = self._row_to_job(row)
        if job.lease_token != lease_token or job.state != JobV2State.RUNNING:
            raise StaleWorkerError(
                "STALE_LEASE",
                "write rejected: lease token mismatch or job no longer running",
                {"state": job.state.value},
            )
        if job.cancel_requested_at is not None:
            raise ConflictError(
                "ALREADY_CANCELLED",
                "cancel was requested before this commit; late output is not final",
            )
        return row

    def commit_job_stage(
        self,
        job_id: str,
        lease_token: str,
        stage: str,
        data: Optional[dict] = None,
        event: str = "stage.progress",
    ) -> JobEventRecord:
        """Stage checkpoint + event in one transaction, fenced by lease."""
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._check_write_fence(job_id, lease_token)
                self._conn.execute(
                    "UPDATE jobs SET current_stage=? WHERE id=?",
                    (stage, job_id),
                )
                rec = self._emit_event(job_id, event, stage=stage, data=data or {})
                self._conn.execute("COMMIT")
                return rec
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def finish_job(
        self,
        job_id: str,
        lease_token: str,
        state: JobV2State,
        error: Optional[str] = None,
        output_revision_id: Optional[str] = None,
    ) -> None:
        """Terminal transition. Fenced: a stale worker cannot mark success,
        and a cancelled job cannot be revived by late output."""
        if state not in (
            JobV2State.SUCCEEDED,
            JobV2State.FAILED,
            JobV2State.CANCELLED,
            JobV2State.COMPLETED_REVIEW_HANDOFF,
        ):
            raise ValidationError(f"not a terminal state: {state}")
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM jobs WHERE id=?", (job_id,)
                ).fetchone()
                if row is None:
                    raise NotFoundError(f"job {job_id}")
                job = self._row_to_job(row)
                if job.lease_token != lease_token:
                    raise StaleWorkerError(
                        "STALE_LEASE", "write rejected: lease token mismatch"
                    )
                if state == JobV2State.CANCELLED:
                    # The worker that still owns the lease may close a job it
                    # observed as cancel-requested. Terminal states are final.
                    if job.state in TERMINAL_JOB_STATES:
                        raise ConflictError(
                            "ALREADY_COMPLETED", f"job already {job.state.value}"
                        )
                else:
                    # Success/failure/handoff after a cancel request must not
                    # become final; the cancellation wins the race.
                    if job.cancel_requested_at is not None:
                        raise ConflictError(
                            "ALREADY_CANCELLED",
                            "cancel was requested before this commit; "
                            "late output is not final",
                        )
                    if job.state != JobV2State.RUNNING:
                        raise StaleWorkerError(
                            "STALE_LEASE",
                            "job no longer running",
                            {"state": job.state.value},
                        )
                self._conn.execute(
                    """UPDATE jobs SET state=?, last_error=?, output_revision_id=?,
                           lease_owner=NULL, lease_token=NULL, lease_expires_at=NULL
                       WHERE id=?""",
                    (state.value, error, output_revision_id, job_id),
                )
                self._emit_event(
                    job_id,
                    "job.completed" if state == JobV2State.SUCCEEDED else "job.state",
                    state=state.value,
                    error=error,
                    revision_id=output_revision_id,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def request_cancel(self, job_id: str) -> JobV2:
        """Cancel vs completion serializes on the same row lock: if the job
        already reached a terminal state this is a 409."""
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM jobs WHERE id=?", (job_id,)
                ).fetchone()
                if row is None:
                    raise NotFoundError(f"job {job_id}")
                job = self._row_to_job(row)
                if job.state in (
                    JobV2State.SUCCEEDED,
                    JobV2State.FAILED,
                    JobV2State.CANCELLED,
                    JobV2State.COMPLETED_REVIEW_HANDOFF,
                ):
                    raise ConflictError(
                        "ALREADY_COMPLETED", f"job already {job.state.value}"
                    )
                self._conn.execute(
                    """UPDATE jobs SET cancel_requested_at=?, state='CANCEL_REQUESTED'
                       WHERE id=? AND state='RUNNING'""",
                    (time.time(), job_id),
                )
                self._conn.execute(
                    "UPDATE jobs SET cancel_requested_at=? WHERE id=? AND state!='RUNNING'",
                    (time.time(), job_id),
                )
                self._emit_event(job_id, "job.state", state="CANCEL_REQUESTED")
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return self.get_job(job_id)  # type: ignore[return-value]

    def is_cancel_requested(self, job_id: str) -> bool:
        row = self._conn.execute(
            "SELECT cancel_requested_at FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        return bool(row and row["cancel_requested_at"])

    def recover_expired_leases(self) -> int:
        """Restart path: jobs whose lease expired mid-RUNNING go back to the
        queue; their checkpoints let a new worker resume."""
        now = time.time()
        with self._lock, self._conn:
            cur = self._conn.execute(
                """UPDATE jobs SET state='RETRY_SCHEDULED', last_error='lease expired',
                       lease_owner=NULL, lease_token=NULL, lease_expires_at=NULL
                   WHERE state='RUNNING' AND lease_expires_at IS NOT NULL
                     AND lease_expires_at < ?""",
                (now,),
            )
            return cur.rowcount

    # ---- job events ------------------------------------------------------------

    def _emit_event(
        self,
        job_id: str,
        event: str,
        state: Optional[str] = None,
        stage: Optional[str] = None,
        revision_id: Optional[str] = None,
        completed_units: Optional[int] = None,
        total_units: Optional[int] = None,
        error: Optional[str] = None,
        data: Optional[dict] = None,
    ) -> JobEventRecord:
        """Must be called inside an open transaction — the event lands in the
        same commit as the state change (outbox pattern)."""
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM job_events WHERE job_id=?",
            (job_id,),
        ).fetchone()
        seq = int(row["next_seq"])
        rec = JobEventRecord(
            job_id=job_id,
            seq=seq,
            event=event,
            state=state,
            stage=stage,
            revision_id=revision_id,
            completed_units=completed_units,
            total_units=total_units,
            error=error,
            data=data or {},
        )
        self._conn.execute(
            """INSERT INTO job_events
               (job_id, seq, ts, event, state, stage, revision_id,
                completed_units, total_units, error, data)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec.job_id,
                rec.seq,
                rec.ts,
                rec.event,
                rec.state,
                rec.stage,
                rec.revision_id,
                rec.completed_units,
                rec.total_units,
                rec.error,
                canonical_json(rec.data),
            ),
        )
        return rec

    def emit_event(self, job_id: str, event: str, **kwargs: Any) -> JobEventRecord:
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rec = self._emit_event(job_id, event, **kwargs)
                self._conn.execute("COMMIT")
                return rec
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def events_since(self, job_id: str, after_seq: int = 0) -> list[JobEventRecord]:
        rows = self._conn.execute(
            "SELECT * FROM job_events WHERE job_id=? AND seq>? ORDER BY seq",
            (job_id, after_seq),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d.pop("rowid", None)
            d["data"] = json.loads(d["data"] or "{}")
            out.append(JobEventRecord(**d))
        return out

    def max_event_seq(self, job_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq),0) AS m FROM job_events WHERE job_id=?",
            (job_id,),
        ).fetchone()
        return int(row["m"])

    # ---- idempotency --------------------------------------------------------------

    def idempotency_lookup(
        self, tenant_id: str, actor: str, route: str, key: str
    ) -> Optional[IdempotencyRecord]:
        row = self._conn.execute(
            """SELECT * FROM idempotency
               WHERE tenant_id=? AND actor=? AND route=? AND key=?""",
            (tenant_id, actor, route, key),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["response_json"] = json.loads(d["response_json"] or "{}")
        return IdempotencyRecord(**d)

    def idempotency_store(self, rec: IdempotencyRecord) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO idempotency
                   (tenant_id, actor, route, key, request_hash, response_json,
                    resource_id, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    rec.tenant_id,
                    rec.actor,
                    rec.route,
                    rec.key,
                    rec.request_hash,
                    canonical_json(rec.response_json),
                    rec.resource_id,
                    rec.created_at,
                ),
            )

    def _row_to_job(self, row: sqlite3.Row) -> JobV2:
        d = dict(row)
        d["state"] = JobV2State(d["state"])
        return JobV2(**d)
