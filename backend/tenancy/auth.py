from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from jobs.store import Store

from .db import TenancyDB
from .models import ROLE_ACTIONS, AuditEvent, Role

SESSION_COOKIE = "examdna_session"
DEV_USER_HEADER = "x-dev-user"
DEV_TENANT_HEADER = "x-dev-tenant"
TENANT_HEADER = "x-tenant-id"


def dev_auth_enabled() -> bool:
    """Dev-header auth is a development stub only (ADR-0002). It is always
    disabled when EXAMDNA_ENV=production."""
    if os.environ.get("EXAMDNA_ENV", "").lower() == "production":
        return False
    return os.environ.get("EXAMDNA_DEV_AUTH", "1") not in {"0", "false", "no"}


class AuthContext(BaseModel):
    user_id: str
    display_name: str = ""
    tenant_id: Optional[str] = None  # active academy
    role: Optional[Role] = None
    session_token: Optional[str] = None
    via_dev_stub: bool = False


def get_auth(request: Request) -> Optional[AuthContext]:
    """Resolve caller identity: session cookie first, then dev headers."""
    from app.deps import get_tenancy  # local import to avoid cycle

    db: TenancyDB = get_tenancy()

    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.get_session(token)
        if session:
            user = db.get_user(session.user_id)
            ctx = AuthContext(
                user_id=session.user_id,
                display_name=(user.display_name if user else ""),
                tenant_id=session.tenant_id,
                session_token=token,
            )
            if ctx.tenant_id:
                m = db.get_membership(ctx.tenant_id, ctx.user_id)
                ctx.role = m.role if m else None
                if ctx.role is None:
                    ctx.tenant_id = None  # membership revoked
            return ctx

    if dev_auth_enabled():
        dev_user = request.headers.get(DEV_USER_HEADER)
        if dev_user:
            user = db.upsert_user(
                dev_user, display_name=request.headers.get("x-dev-name", dev_user)
            )
            tenant_id = request.headers.get(DEV_TENANT_HEADER)
            ctx = AuthContext(
                user_id=user.id,
                display_name=user.display_name,
                tenant_id=tenant_id,
                via_dev_stub=True,
            )
            if tenant_id:
                m = db.get_membership(tenant_id, user.id)
                ctx.role = m.role if m else None
                if ctx.role is None:
                    ctx.tenant_id = None
            return ctx
    return None


def require_auth(request: Request) -> AuthContext:
    ctx = get_auth(request)
    if ctx is None:
        raise HTTPException(401, "authentication required")
    return ctx


def require_tenant(request: Request) -> AuthContext:
    """Require an authenticated user with an active tenant membership."""
    ctx = require_auth(request)
    tenant_id = request.headers.get(TENANT_HEADER) or ctx.tenant_id
    if not tenant_id:
        raise HTTPException(400, "no active academy; select a tenant first")
    from app.deps import get_tenancy

    db = get_tenancy()
    m = db.get_membership(tenant_id, ctx.user_id)
    if m is None:
        raise HTTPException(403, "not a member of this academy")
    ctx.tenant_id = tenant_id
    ctx.role = m.role
    return ctx


def require_action(action: str):
    """Dependency factory: membership role must allow `action` on the
    caller's active tenant."""

    def dep(request: Request) -> AuthContext:
        ctx = require_tenant(request)
        assert ctx.role is not None
        if action not in ROLE_ACTIONS[ctx.role]:
            raise HTTPException(403, f"role {ctx.role.value} cannot {action}")
        return ctx

    return dep


def resolve_document_access(
    doc_id: str,
    action: str,
    request: Request,
    store: Store,
) -> tuple[AuthContext, object]:
    """Load a document and verify the caller may perform `action` on it.

    Returns (auth_ctx, document). Cross-tenant and unmigrated documents
    return 404 so existence is not leaked (REQ-25)."""
    ctx = require_auth(request)
    from app.deps import get_tenancy

    db = get_tenancy()
    try:
        doc = store.load_document(doc_id)
    except FileNotFoundError:
        raise HTTPException(404, "document not found")

    tenant_id = getattr(doc, "tenant_id", None)
    if tenant_id is None:
        # Legacy unmigrated document: never auto-public (WP01 contract).
        raise HTTPException(404, "document not found")

    allowed_role: Optional[Role] = None
    m = db.get_membership(tenant_id, ctx.user_id)
    if m is not None:
        allowed_role = m.role
    else:
        g = db.get_document_grant(doc_id, ctx.user_id)
        if g is not None:
            allowed_role = g.role
    if allowed_role is None:
        raise HTTPException(404, "document not found")
    if action not in ROLE_ACTIONS[allowed_role]:
        raise HTTPException(403, f"role {allowed_role.value} cannot {action}")

    ctx.tenant_id = tenant_id
    ctx.role = allowed_role
    return ctx, doc


def audit(
    request: Request,
    ctx: AuthContext,
    action: str,
    object_type: str = "",
    object_id: str = "",
    detail: Optional[dict] = None,
) -> None:
    from app.deps import get_tenancy

    get_tenancy().audit(
        AuditEvent(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            detail=detail or {},
        )
    )
