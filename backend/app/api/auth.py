from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from tenancy.auth import (
    SESSION_COOKIE,
    AuthContext,
    audit,
    dev_auth_enabled,
    require_auth,
    require_tenant,
)
from tenancy.db import TenancyDB
from tenancy.models import AuditEvent, Role

from ..deps import get_tenancy

router = APIRouter(prefix="/api", tags=["auth"])


class DevLoginRequest(BaseModel):
    user_id: str
    display_name: str = ""


@router.post("/auth/dev-login")
def dev_login(
    req: DevLoginRequest,
    response: Response,
    db: TenancyDB = Depends(get_tenancy),
):
    """Development stub login (ADR-0002). Disabled when
    EXAMDNA_ENV=production. Real IdP integration is RG-02."""
    if not dev_auth_enabled():
        raise HTTPException(404, "not found")
    user = db.upsert_user(req.user_id, display_name=req.display_name or req.user_id)
    session = db.create_session(user.id)
    response.set_cookie(
        SESSION_COOKIE,
        session.token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )
    db.audit(
        AuditEvent(user_id=user.id, action="auth.dev_login", object_type="user", object_id=user.id)
    )
    return {"user_id": user.id, "display_name": user.display_name, "tenant_id": session.tenant_id}


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: TenancyDB = Depends(get_tenancy)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.delete_session(token)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request, db: TenancyDB = Depends(get_tenancy)):
    from tenancy.auth import get_auth

    ctx = get_auth(request)
    if ctx is None:
        return {"authenticated": False}
    tenants = []
    for m in db.list_memberships_for_user(ctx.user_id):
        t = db.get_tenant(m.tenant_id)
        if t:
            tenants.append({"id": t.id, "name": t.name, "role": m.role.value})
    return {
        "authenticated": True,
        "user_id": ctx.user_id,
        "display_name": ctx.display_name,
        "tenant_id": ctx.tenant_id,
        "role": ctx.role.value if ctx.role else None,
        "tenants": tenants,
        "via_dev_stub": ctx.via_dev_stub,
    }


class CreateTenantRequest(BaseModel):
    name: str


@router.get("/tenants")
def list_tenants(ctx: AuthContext = Depends(require_auth), db: TenancyDB = Depends(get_tenancy)):
    out = []
    for m in db.list_memberships_for_user(ctx.user_id):
        t = db.get_tenant(m.tenant_id)
        if t:
            out.append({"id": t.id, "name": t.name, "role": m.role.value})
    return {"tenants": out}


@router.post("/tenants")
def create_tenant(
    req: CreateTenantRequest,
    request: Request,
    ctx: AuthContext = Depends(require_auth),
    db: TenancyDB = Depends(get_tenancy),
):
    user = db.get_user(ctx.user_id)
    tenant = db.create_tenant(req.name, owner=user)
    db.audit(
        AuditEvent(
            tenant_id=tenant.id,
            user_id=ctx.user_id,
            action="tenant.create",
            object_type="tenant",
            object_id=tenant.id,
            detail={"name": req.name},
        )
    )
    # make the new academy active for this session
    if ctx.session_token:
        db.set_session_tenant(ctx.session_token, tenant.id)
    return {"id": tenant.id, "name": tenant.name, "role": Role.OWNER.value}


class SwitchTenantRequest(BaseModel):
    tenant_id: str


@router.post("/tenants/switch")
def switch_tenant(
    req: SwitchTenantRequest,
    request: Request,
    ctx: AuthContext = Depends(require_auth),
    db: TenancyDB = Depends(get_tenancy),
):
    m = db.get_membership(req.tenant_id, ctx.user_id)
    if m is None:
        raise HTTPException(403, "not a member of this academy")
    if ctx.session_token:
        db.set_session_tenant(ctx.session_token, req.tenant_id)
    return {"tenant_id": req.tenant_id, "role": m.role.value}


class CreateInviteRequest(BaseModel):
    role: Role = Role.TEACHER


@router.post("/tenants/{tenant_id}/invites")
def create_invite(
    tenant_id: str,
    req: CreateInviteRequest,
    request: Request,
    db: TenancyDB = Depends(get_tenancy),
):
    ctx = require_auth(request)
    m = db.get_membership(tenant_id, ctx.user_id)
    if m is None:
        raise HTTPException(404, "academy not found")
    if m.role not in {Role.OWNER}:
        raise HTTPException(403, "only the academy owner can invite")
    inv = db.create_invite(tenant_id, req.role, created_by=ctx.user_id)
    ctx.tenant_id = tenant_id
    audit(request, ctx, "tenant.invite", "tenant", tenant_id, {"role": req.role.value})
    return {"code": inv.code, "role": inv.role.value, "expires_at": inv.expires_at}


@router.post("/invites/{code}/accept")
def accept_invite(
    code: str,
    request: Request,
    db: TenancyDB = Depends(get_tenancy),
):
    import time

    ctx = require_auth(request)
    inv = db.get_invite_by_code(code)
    if inv is None or inv.revoked or (inv.expires_at and inv.expires_at < time.time()):
        raise HTTPException(404, "invite not found or expired")
    db.add_membership(inv.tenant_id, ctx.user_id, inv.role)
    if ctx.session_token:
        db.set_session_tenant(ctx.session_token, inv.tenant_id)
    ctx.tenant_id = inv.tenant_id
    audit(request, ctx, "tenant.join", "tenant", inv.tenant_id, {"via": "invite"})
    return {"tenant_id": inv.tenant_id, "role": inv.role.value}


@router.get("/tenants/{tenant_id}/audit")
def list_audit(
    tenant_id: str,
    request: Request,
    db: TenancyDB = Depends(get_tenancy),
):
    ctx = require_auth(request)
    m = db.get_membership(tenant_id, ctx.user_id)
    if m is None:
        raise HTTPException(404, "academy not found")
    if m.role != Role.OWNER:
        raise HTTPException(403, "owner only")
    return {"events": [e.model_dump() for e in db.list_audit(tenant_id)]}
