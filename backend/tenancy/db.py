from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .models import (
    AuditEvent,
    DocumentGrant,
    Invite,
    Membership,
    Role,
    SessionRecord,
    Tenant,
    User,
    new_id,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT,
    display_name TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (tenant_id, user_id)
);
CREATE TABLE IF NOT EXISTS invites (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    code TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    expires_at REAL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    tenant_id TEXT,
    created_at REAL NOT NULL,
    expires_at REAL
);
CREATE TABLE IF NOT EXISTS document_grants (
    document_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL,
    granted_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    PRIMARY KEY (document_id, user_id)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    tenant_id TEXT,
    user_id TEXT,
    action TEXT NOT NULL,
    object_type TEXT NOT NULL DEFAULT '',
    object_id TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id, ts);
CREATE INDEX IF NOT EXISTS idx_audit_object ON audit_log(object_type, object_id);
"""

SESSION_TTL = 60 * 60 * 24 * 14  # 14 days


class TenancyDB:
    """SQLite-backed tenant/membership/session/grant/audit store.

    Dev-local adapter for the central-DB contract (ADR-0001): the same
    interface is intended to move to PostgreSQL in WP02+ without callers
    changing.
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
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- tenants -----------------------------------------------------

    def create_tenant(self, name: str, owner: Optional[User] = None) -> Tenant:
        tenant = Tenant(name=name)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO tenants (id, name, created_at) VALUES (?,?,?)",
                (tenant.id, tenant.name, tenant.created_at),
            )
        if owner is not None:
            self.add_membership(tenant.id, owner.id, Role.OWNER)
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        row = self._conn.execute(
            "SELECT * FROM tenants WHERE id=?", (tenant_id,)
        ).fetchone()
        return Tenant(**dict(row)) if row else None

    # ---- users ---------------------------------------------------------

    def upsert_user(
        self, user_id: str, display_name: str = "", email: Optional[str] = None
    ) -> User:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO users (id, email, display_name, created_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                       display_name=excluded.display_name,
                       email=COALESCE(excluded.email, users.email)""",
                (user_id, email, display_name, time.time()),
            )
        return self.get_user(user_id)  # type: ignore[return-value]

    def get_user(self, user_id: str) -> Optional[User]:
        row = self._conn.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone()
        return User(**dict(row)) if row else None

    # ---- memberships ---------------------------------------------------

    def add_membership(self, tenant_id: str, user_id: str, role: Role) -> Membership:
        m = Membership(tenant_id=tenant_id, user_id=user_id, role=role)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO memberships (tenant_id, user_id, role, created_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(tenant_id, user_id) DO UPDATE SET role=excluded.role""",
                (m.tenant_id, m.user_id, m.role.value, m.created_at),
            )
        return m

    def get_membership(self, tenant_id: str, user_id: str) -> Optional[Membership]:
        row = self._conn.execute(
            "SELECT * FROM memberships WHERE tenant_id=? AND user_id=?",
            (tenant_id, user_id),
        ).fetchone()
        if not row:
            return None
        return Membership(**dict(row))

    def list_memberships_for_user(self, user_id: str) -> list[Membership]:
        rows = self._conn.execute(
            "SELECT * FROM memberships WHERE user_id=?", (user_id,)
        ).fetchall()
        return [Membership(**dict(r)) for r in rows]

    def list_members(self, tenant_id: str) -> list[Membership]:
        rows = self._conn.execute(
            "SELECT * FROM memberships WHERE tenant_id=?", (tenant_id,)
        ).fetchall()
        return [Membership(**dict(r)) for r in rows]

    # ---- invites ---------------------------------------------------------

    def create_invite(
        self, tenant_id: str, role: Role, created_by: str, ttl: float = 86400 * 7
    ) -> Invite:
        inv = Invite(
            tenant_id=tenant_id,
            code=secrets.token_urlsafe(16),
            role=role,
            created_by=created_by,
            expires_at=time.time() + ttl,
        )
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO invites
                   (id, tenant_id, code, role, created_by, created_at, expires_at, revoked)
                   VALUES (?,?,?,?,?,?,?,0)""",
                (
                    inv.id,
                    inv.tenant_id,
                    inv.code,
                    inv.role.value,
                    inv.created_by,
                    inv.created_at,
                    inv.expires_at,
                ),
            )
        return inv

    def get_invite_by_code(self, code: str) -> Optional[Invite]:
        row = self._conn.execute(
            "SELECT * FROM invites WHERE code=?", (code,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["revoked"] = bool(data["revoked"])
        return Invite(**data)

    # ---- sessions ---------------------------------------------------------

    def create_session(self, user_id: str, tenant_id: Optional[str] = None) -> SessionRecord:
        s = SessionRecord(
            token=secrets.token_urlsafe(32),
            user_id=user_id,
            tenant_id=tenant_id,
            expires_at=time.time() + SESSION_TTL,
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO sessions (token, user_id, tenant_id, created_at, expires_at)"
                " VALUES (?,?,?,?,?)",
                (s.token, s.user_id, s.tenant_id, s.created_at, s.expires_at),
            )
        return s

    def get_session(self, token: str) -> Optional[SessionRecord]:
        if not token:
            return None
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE token=?", (token,)
        ).fetchone()
        if not row:
            return None
        s = SessionRecord(**dict(row))
        if s.expires_at is not None and s.expires_at < time.time():
            self.delete_session(token)
            return None
        return s

    def set_session_tenant(self, token: str, tenant_id: Optional[str]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET tenant_id=? WHERE token=?", (tenant_id, token)
            )

    def delete_session(self, token: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM sessions WHERE token=?", (token,))

    # ---- document grants ---------------------------------------------------

    def add_document_grant(
        self, document_id: str, user_id: str, role: Role, granted_by: str = ""
    ) -> DocumentGrant:
        g = DocumentGrant(
            document_id=document_id, user_id=user_id, role=role, granted_by=granted_by
        )
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO document_grants
                   (document_id, user_id, role, granted_by, created_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(document_id, user_id) DO UPDATE SET role=excluded.role""",
                (g.document_id, g.user_id, g.role.value, g.granted_by, g.created_at),
            )
        return g

    def get_document_grant(
        self, document_id: str, user_id: str
    ) -> Optional[DocumentGrant]:
        row = self._conn.execute(
            "SELECT * FROM document_grants WHERE document_id=? AND user_id=?",
            (document_id, user_id),
        ).fetchone()
        return DocumentGrant(**dict(row)) if row else None

    # ---- audit --------------------------------------------------------------

    def audit(self, event: AuditEvent) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO audit_log
                   (id, ts, tenant_id, user_id, action, object_type, object_id, detail)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    event.id or new_id("aud"),
                    event.ts,
                    event.tenant_id,
                    event.user_id,
                    event.action,
                    event.object_type,
                    event.object_id,
                    json.dumps(event.detail, ensure_ascii=False),
                ),
            )

    def list_audit(self, tenant_id: str, limit: int = 200) -> list[AuditEvent]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE tenant_id=? ORDER BY ts DESC LIMIT ?",
            (tenant_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d["detail"] or "{}")
            out.append(AuditEvent(**d))
        return out
