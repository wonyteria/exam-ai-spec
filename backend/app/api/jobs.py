from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from canonical.models import JobV2, JobV2State
from canonical.store import CanonicalStore
from tenancy.auth import AuthContext, require_auth
from tenancy.db import TenancyDB
from tenancy.models import ROLE_ACTIONS

from ..deps import get_canonical, get_tenancy

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_TERMINAL = {
    JobV2State.SUCCEEDED,
    JobV2State.FAILED,
    JobV2State.CANCELLED,
    JobV2State.COMPLETED_REVIEW_HANDOFF,
}

# v2 state -> legacy JobState value the existing UI understands
_STATE_MAP = {
    JobV2State.QUEUED: "UPLOADED",
    JobV2State.RETRY_SCHEDULED: "UPLOADED",
    JobV2State.WAITING_QUOTA: "UPLOADED",
    JobV2State.WAITING_WORKER: "UPLOADED",
    JobV2State.RUNNING: "RUNNING",
    JobV2State.CANCEL_REQUESTED: "RUNNING",
    JobV2State.SUCCEEDED: "COMPLETED",
    JobV2State.FAILED: "FAILED",
    JobV2State.CANCELLED: "CANCELLED",
    JobV2State.COMPLETED_REVIEW_HANDOFF: "NEEDS_REVIEW",
}


def _resolve_job_access(
    job_id: str, action: str, request: Request, cstore: CanonicalStore
) -> tuple[AuthContext, JobV2]:
    """Load a v2 job and verify tenant access. Cross-tenant and unknown
    jobs return 404 so existence is not leaked."""
    ctx = require_auth(request)
    db: TenancyDB = get_tenancy()
    job = cstore.get_job(job_id)
    if job is None:
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


def _to_legacy(job: JobV2, events: list[dict]) -> dict:
    return {
        "id": job.id,
        "document_id": job.document_id,
        "state": _STATE_MAP.get(job.state, job.state.value),
        "events": events,
        "error": job.last_error,
    }


def _event_payload(cstore: CanonicalStore, job_id: str) -> list[dict]:
    return [
        {
            "ts": e.ts,
            "stage": e.stage or "pipeline",
            "message": e.data.get("message") or e.event,
            "level": e.data.get("level", "info"),
        }
        for e in cstore.events_since(job_id, 0)
    ]


@router.get("/{job_id}")
def get_job(
    job_id: str, request: Request, cstore: CanonicalStore = Depends(get_canonical)
):
    _, job = _resolve_job_access(job_id, "read", request, cstore)
    return _to_legacy(job, _event_payload(cstore, job_id))


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str, request: Request, cstore: CanonicalStore = Depends(get_canonical)
):
    from canonical.store import ConflictError, NotFoundError

    _, job = _resolve_job_access(job_id, "edit", request, cstore)
    try:
        job = cstore.request_cancel(job_id)
    except ConflictError as exc:
        raise HTTPException(409, {"code": exc.code, "message": str(exc)})
    except NotFoundError:
        raise HTTPException(404, "job not found")
    return _to_legacy(job, _event_payload(cstore, job_id))


@router.get("/{job_id}/events")
async def job_events(
    job_id: str, request: Request, cstore: CanonicalStore = Depends(get_canonical)
):
    _, job = _resolve_job_access(job_id, "read", request, cstore)

    async def stream():
        sent = 0
        while True:
            job = cstore.get_job(job_id)
            if job is None:
                yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                return
            events = cstore.events_since(job_id, sent)
            for e in events:
                yield f"data: {json.dumps({'ts': e.ts, 'stage': e.stage or 'pipeline', 'message': e.data.get('message') or e.event, 'level': e.data.get('level', 'info')})}\n\n"
                sent = e.seq
            if job.state in _TERMINAL and sent >= cstore.max_event_seq(job_id):
                yield f"data: {json.dumps({'done': True, 'state': _STATE_MAP.get(job.state, job.state.value)})}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream")
