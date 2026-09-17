from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from jobs.models import JobState
from jobs.store import Store

from ..deps import get_store

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_TERMINAL = {JobState.COMPLETED, JobState.NEEDS_REVIEW, JobState.FAILED}


@router.get("/{job_id}")
def get_job(job_id: str, store: Store = Depends(get_store)):
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@router.get("/{job_id}/events")
async def job_events(job_id: str, store: Store = Depends(get_store)):
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
