from __future__ import annotations

import os
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv

from core.examdna import STAGES, PipelineContext, Providers
from jobs.models import JobState
from jobs.store import Store
from providers import llm, math_ocr, ocr, solver, vision

load_dotenv()


def default_providers() -> Providers:
    providers = Providers(
        ocr=[ocr.get_provider()],
        vision=[vision.get_provider()],
        math_ocr=[math_ocr.get_provider()],
        reasoning=[llm.get_provider()],
        solver=[solver.get_provider()],
    )
    gemini = _gemini_provider()
    if gemini is not None:
        providers.ocr.insert(0, gemini)
        providers.vision.insert(0, gemini)
        providers.math_ocr.insert(0, gemini)
        providers.reasoning.insert(0, gemini)
        providers.solver.insert(0, _gemini_provider("GEMINI_MODEL_SOLVER") or gemini)
    return providers


def _gemini_provider(model_env: str = "GEMINI_MODEL"):
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        from providers.gemini import GeminiProvider
    except ImportError:
        return None
    model = os.environ.get(model_env) or None
    return GeminiProvider(model=model)


def run_pipeline(store: Store, job_id: str) -> None:
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(f"unknown job {job_id}")

    workdir = Path(store.job_dir(job_id))
    ctx = PipelineContext(
        document=store.load_document(job.document_id),
        job=job,
        store=store,
        workdir=workdir,
        providers=default_providers(),
    )

    try:
        for state, stage_name, fn in STAGES:
            job.state = state
            store.update_job(job)
            store.emit(job, stage_name, f"단계 시작: {stage_name}")
            fn(ctx)
            store.save_document(ctx.document)

        job.state = (
            JobState.COMPLETED
            if ctx.document.verification.status == "VERIFIED_FINAL"
            else JobState.NEEDS_REVIEW
        )
        job.finished_at = time.time()
        store.update_job(job)
        store.emit(job, "pipeline", f"파이프라인 종료 — {job.state.value}")
    except Exception as exc:  # noqa: BLE001
        job.state = JobState.FAILED
        job.error = f"{exc}\n{traceback.format_exc()}"
        job.finished_at = time.time()
        store.update_job(job)
        store.emit(job, "pipeline", f"파이프라인 실패: {exc}", "error")
