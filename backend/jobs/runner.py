from __future__ import annotations

import os
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv

from core.examdna import PipelineContext, Providers
from jobs.models import JobState
from jobs.store import Store
from providers import llm, math_ocr, ocr, solver, vision

load_dotenv()


def default_providers() -> Providers:
    """Operational provider chain (WP04): OpenAI is the default server-side
    adapter when OPENAI_API_KEY is configured. Gemini is NOT auto-inserted —
    it is an opt-in fallback (EXAMDNA_ENABLE_GEMINI=1) and developer Codex
    usage stays a separate QA tool, not an operational dependency."""
    providers = Providers(
        ocr=ocr.get_providers(),
        vision=[vision.get_provider()],
        math_ocr=[math_ocr.get_provider()],
        reasoning=[llm.get_provider()],
        solver=[solver.get_provider()],
    )
    for page_extractor in vision.get_page_extractors():
        providers.vision.insert(0, page_extractor)
    openai = _openai_provider()
    if openai is not None:
        # Text roles only by default: solver/reasoning receive structured
        # problem JSON, never page pixels. Image-capable roles (ocr,
        # vision, math_ocr — extract_page/recognize_text/describe all
        # upload the raw exam image) require the explicit opt-in flag,
        # the same bar as the local-vision URL guard: a stray
        # OPENAI_API_KEY must never cause image upload.
        providers.reasoning.insert(0, openai)
        providers.solver.insert(
            0, _openai_provider("OPENAI_MODEL_SOLVER") or openai
        )
        if os.environ.get("EXAMDNA_ENABLE_OPENAI_VISION") == "1":
            providers.ocr.insert(0, openai)
            providers.vision.insert(0, openai)
            providers.math_ocr.insert(0, openai)
    if os.environ.get("EXAMDNA_ENABLE_GEMINI") == "1":
        gemini = _gemini_provider()
        if gemini is not None:
            providers.ocr.insert(0, gemini)
            providers.vision.insert(0, gemini)
            providers.math_ocr.insert(0, gemini)
            providers.reasoning.insert(0, gemini)
            providers.solver.insert(
                0, _gemini_provider("GEMINI_MODEL_SOLVER") or gemini
            )
    if os.environ.get("EXAMDNA_ENABLE_LOCAL_LLM") == "1":
        local = _local_provider()
        if local is not None:
            # Text-only roles only — image roles (ocr/vision/math_ocr)
            # need a real vision model and stay with their providers.
            # Routing: local-large handles ordinary/formula/figure
            # questions; LOCAL_LLM_MODEL_LONG (local-long) receives only
            # long descriptive items. local-small is never a solver.
            long_model = os.environ.get("LOCAL_LLM_MODEL_LONG", "local-long")
            long_provider = None
            if long_model and long_model != getattr(local, "model", None):
                long_provider = _local_provider(
                    model=long_model, name=f"local-llm/{long_model}"
                )
            try:
                from providers.local.router import LocalLLMRouter

                router = LocalLLMRouter(local, long_provider)
            except ImportError:
                router = local
            providers.solver.insert(0, router)
            providers.reasoning.insert(0, router)
            # Independent second slot: LOCAL_LLM_MODEL_ALT registers
            # another model as its own evidence source. Same model as
            # the primary = same source, so it is skipped — a shared
            # cache replay is never counted as independent agreement.
            # (ALT==long_model still registers: the slot answers every
            # problem, the router only sends descriptive ones — same
            # provider name on a descriptive item just collapses to one
            # source, which is correct.)
            alt_model = os.environ.get("LOCAL_LLM_MODEL_ALT")
            if alt_model and alt_model != getattr(local, "model", None):
                alt = _local_provider(
                    model=alt_model, name=f"local-llm/{alt_model}"
                )
                if alt is not None:
                    providers.solver.insert(1, alt)
                    providers.reasoning.insert(1, alt)
    if os.environ.get("EXAMDNA_ENABLE_LOCAL_VISION") == "1":
        tv = _local_vision_provider()
        if tv is not None:
            providers.trace.append(tv)
    return providers


def _local_vision_provider():
    """Local VLM trace detector — opt-in, needs a vision-capable model."""
    if not os.environ.get("LOCAL_LLM_BASE_URL"):
        return None
    try:
        from providers.local.trace import LocalVisionTraceProvider

        return LocalVisionTraceProvider()
    except (ImportError, KeyError):
        return None
    except ValueError as exc:
        # Non-local base URL configured — refuse loudly but keep the job
        # alive on the heuristic path.
        import warnings

        warnings.warn(f"local vision provider disabled: {exc}")
        return None


def _local_provider(model: str | None = None, name: str | None = None):
    if not os.environ.get("LOCAL_LLM_BASE_URL"):
        return None
    try:
        from providers.local import LocalLLMProvider

        return LocalLLMProvider(
            model=model
            or os.environ.get("LOCAL_LLM_MODEL")
            or os.environ.get("LOCAL_LLM_MODEL_LARGE")
            or "local-large",
            name=name,
        )
    except (ImportError, KeyError):
        return None


def _openai_provider(model_env: str = "OPENAI_MODEL"):
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:
        from providers.openai import OpenAIProvider

        model = os.environ.get(model_env) or None
        return OpenAIProvider(model=model)
    except ImportError:
        return None


def _gemini_provider(model_env: str = "GEMINI_MODEL"):
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        from providers.gemini import GeminiProvider

        model = os.environ.get(model_env) or None
        return GeminiProvider(model=model)
    except ImportError:
        return None


def run_pipeline(store: Store, job_id: str) -> None:
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(f"unknown job {job_id}")

    workdir = Path(store.job_dir(job_id))
    from app.deps import get_object_store

    ctx = PipelineContext(
        document=store.load_document(job.document_id),
        job=job,
        store=store,
        workdir=workdir,
        providers=default_providers(),
        objects=get_object_store(),
    )

    from jobs.metrics import JobMetrics
    from core.examdna.executor import run_stages

    metrics = JobMetrics(workdir)

    def _on_start(contract) -> None:
        job.state = contract.job_state
        store.update_job(job)
        metrics.stage_start(contract.name)

    def _on_end(contract, record) -> None:
        metrics.stage_end(
            contract.name,
            ok=record.status.value == "SUCCEEDED",
            extra=ctx.stage_metrics.get(contract.name),
        )
        store.save_document(ctx.document)

    try:
        run_stages(ctx, on_stage_start=_on_start, on_stage_end=_on_end)

        job.state = (
            JobState.COMPLETED
            if (
                ctx.document.verification.status == "VERIFIED_FINAL"
                and not ctx.stage_blocked
            )
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
