from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path

from canonical.service import MutationService
from canonical.store import (
    CanonicalStore,
    ConflictError,
    StaleWorkerError,
)
from canonical.models import JobV2State, RevisionMode
from core.examdna import STAGES, PipelineContext
from core.examdna.context import Providers
from document.models import VerificationStatus
from jobs.models import Job
from jobs.runner import default_providers
from jobs.store import Store

HEARTBEAT_SECONDS = 20.0


def run_once(
    cstore: CanonicalStore,
    store: Store,
    objects,
    tenancy,
    worker_id: str,
    providers: Providers | None = None,
) -> bool:
    """Claim one job and run the pipeline under its lease.

    Every write is fenced by the job's lease token: a stale worker that
    lost its lease cannot commit stage output, mark success, or revive a
    cancelled job (INV-11).
    """
    job = cstore.claim_job(worker_id)
    if job is None:
        return False
    token = job.lease_token
    assert token is not None

    stop = threading.Event()

    def _heartbeat() -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                cstore.heartbeat(job.id, token)
            except StaleWorkerError:
                return

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()
    try:
        _execute(cstore, store, objects, tenancy, job, token, providers)
    finally:
        stop.set()
        hb.join(timeout=1)
    return True


def _execute(
    cstore: CanonicalStore,
    store: Store,
    objects,
    tenancy,
    job,
    token: str,
    providers: Providers | None,
) -> None:
    def sink(stage: str, message: str, level: str = "info") -> None:
        try:
            cstore.commit_job_stage(
                job.id,
                token,
                stage,
                data={"message": message, "level": level},
            )
        except (StaleWorkerError, ConflictError):
            raise _FenceLost()

    try:
        shim = Job(id=job.id, document_id=job.document_id, tenant_id=job.tenant_id)
        ctx = PipelineContext(
            document=store.load_document(job.document_id),
            job=shim,
            store=store,
            workdir=Path(store.job_dir(job.id)),
            providers=providers or default_providers(),
            objects=objects,
            event_sink=sink,
        )
        for _state, stage_name, fn in STAGES:
            if cstore.is_cancel_requested(job.id):
                cstore.finish_job(job.id, token, JobV2State.CANCELLED)
                return
            cstore.commit_job_stage(
                job.id,
                token,
                stage_name,
                data={"message": f"단계 시작: {stage_name}", "level": "info"},
                event="stage.started",
            )
            fn(ctx)
            store.save_document(ctx.document)

        # Commit the restored document as a canonical RESTORE revision and
        # run the implemented validators. Unimplemented required checks stay
        # NOT_RUN — the final gate is fail-closed.
        service = MutationService(cstore, tenancy)
        rev = service.create_revision(
            ctx.document,
            tenant_id=job.tenant_id,
            actor=job.created_by or "pipeline",
            mode=RevisionMode.RESTORE,
            ops_summary=[{"op": "pipeline_restore"}],
        )
        service.run_checks(rev.id, providers=ctx.providers)

        needs_review = any(
            atu.status
            in (
                VerificationStatus.UNVERIFIED,
                VerificationStatus.CONFLICT,
                VerificationStatus.UNREADABLE,
            )
            for atu in ctx.document.all_atus()
        ) or ctx.document.verification.status != "VERIFIED_FINAL"
        if needs_review:
            # Terminal review handoff: job closes, slots/lease released; the
            # document carries the open review state (02 §9).
            cstore.finish_job(
                job.id,
                token,
                JobV2State.COMPLETED_REVIEW_HANDOFF,
                output_revision_id=rev.id,
            )
        else:
            cstore.finish_job(
                job.id, token, JobV2State.SUCCEEDED, output_revision_id=rev.id
            )
    except _FenceLost:
        return  # stale worker: leave raw evidence, commit nothing
    except Exception as exc:  # noqa: BLE001
        try:
            cstore.finish_job(
                job.id,
                token,
                JobV2State.FAILED,
                error=f"{exc}\n{traceback.format_exc(limit=5)}",
            )
        except (StaleWorkerError, ConflictError):
            pass


class _FenceLost(Exception):
    pass
