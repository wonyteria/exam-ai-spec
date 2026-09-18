from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from jobs.models import Job, JobState
from jobs.store import Store
from tenancy.auth import AuthContext, require_auth
from tenancy.db import TenancyDB
from tenancy.models import ROLE_ACTIONS

from ..deps import get_store, get_tenancy

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_TERMINAL = {JobState.COMPLETED, JobState.NEEDS_REVIEW, JobState.FAILED}


def _resolve_job_access(
    job_id: str, action: str, request: Request, store: Store
) -> tuple[AuthContext, Job]:
    """Load a job and verify tenant access. Cross-tenant and unmigrated
    jobs return 404 so existence is not leaked."""
    ctx = require_auth(request)
    db: TenancyDB = get_tenancy()
    job = store.get_job(job_id)
    if job is None or job.tenant_id is None:
        raise HTTPException(404, "job not found")
    m = db.get_membership(job.tenant_id, ctx.user_id)
    if m is None:
        g = db.get_document_grant(job.document_id, ctx.user_id)
        if g is None:
            raise HTTPException(404, "job not found")
        role = g.role
    else:
        role = m.role
    if action not in ROLE_ACTIONS[role]:
        raise HTTPException(403, f"role {role.value} cannot {action}")
    ctx.tenant_id = job.tenant_id
    ctx.role = role
    return ctx, job


@router.get("/{job_id}")
def get_job(job_id: str, request: Request, store: Store = Depends(get_store)):
    _, job = _resolve_job_access(job_id, "read", request, store)
    return job


@router.get("/{job_id}/events")
async def job_events(
    job_id: str, request: Request, store: Store = Depends(get_store)
):
    _resolve_job_access(job_id, "read", request, store)

    async def stream():
        sent = 0
        while True:
            job = store.get_job(job_id)
            if job is None:
                yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                return
            while sent < len(job.events):
                yield f"data: {job.events[sent].model_dump_json()}\n\n"
                sent += 1
            if job.state in _TERMINAL and sent >= len(job.events):
                yield f"data: {json.dumps({'done': True, 'state': job.state.value})}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream")
