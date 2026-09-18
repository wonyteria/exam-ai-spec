from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Role(str, Enum):
    OWNER = "owner"
    TEACHER = "teacher"
    REVIEWER = "reviewer"


# What each role may do. Reviewer: review/preview only — no artifact
# download, no export/release authority.
ROLE_ACTIONS: dict[Role, set[str]] = {
    Role.OWNER: {"read", "review", "edit", "upload", "export", "download", "admin"},
    Role.TEACHER: {"read", "review", "edit", "upload", "export", "download"},
    Role.REVIEWER: {"read", "review"},
}


class Tenant(BaseModel):
    id: str = Field(default_factory=lambda: new_id("tn"))
    name: str
    created_at: float = Field(default_factory=time.time)


class User(BaseModel):
    id: str
    email: Optional[str] = None
    display_name: str = ""
    created_at: float = Field(default_factory=time.time)


class Membership(BaseModel):
    tenant_id: str
    user_id: str
    role: Role
    created_at: float = Field(default_factory=time.time)


class Invite(BaseModel):
    id: str = Field(default_factory=lambda: new_id("inv"))
    tenant_id: str
    code: str
    role: Role = Role.TEACHER
    created_by: str = ""
    created_at: float = Field(default_factory=time.time)
    expires_at: Optional[float] = None
    revoked: bool = False


class SessionRecord(BaseModel):
    token: str
    user_id: str
    tenant_id: Optional[str] = None  # active academy
    created_at: float = Field(default_factory=time.time)
    expires_at: Optional[float] = None


class DocumentGrant(BaseModel):
    """Per-document grant for users without tenant membership
    (e.g. external reviewer). Narrower than membership."""

    document_id: str
    user_id: str
    role: Role
    granted_by: str = ""
    created_at: float = Field(default_factory=time.time)


class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("aud"))
    ts: float = Field(default_factory=time.time)
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    action: str
    object_type: str = ""
    object_id: str = ""
    detail: dict = Field(default_factory=dict)
