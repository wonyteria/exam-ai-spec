from __future__ import annotations

from pathlib import Path

from document.models import ATU, ATUKind, Candidate, Question
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Multi-recognition: providers produce Candidates, never final values."""
    for question in ctx.document.questions:
        image, region = _question_image(ctx, question)
        if image is None:
            continue
        for provider in ctx.providers.ocr:
            for cand in provider.recognize_text(image, region):
                _ingest(question, provider.name, cand)
        for provider in ctx.providers.math_ocr:
            for cand in provider.recognize_math(image, region):
                _ingest(question, provider.name, cand)

    atu_count = sum(len(q.atus) for q in ctx.document.questions)
    ctx.emit("recognition", f"{atu_count}개 ATU 후보 수집")


def _question_image(ctx: PipelineContext, question: Question):
    if not question.source or question.source.page >= len(ctx.document.pages):
        return None, None
    page = ctx.document.pages[question.source.page]
    return Path(page.clean_uri or page.original.uri), question.source.bbox


def _ingest(question: Question, provider_name: str, cand: Candidate) -> None:
    if cand.meta.get("structured") and isinstance(cand.value, dict):
        for kind, field, value in _decompose(cand.value):
            atu = ATU(kind=kind, field=field, source=question.source)
            atu.candidates.append(
                Candidate(
                    provider=provider_name,
                    value=value,
                    confidence=cand.confidence,
                    meta=cand.meta,
                )
            )
            question.atus.append(atu)
        return

    kind = cand.meta.get("atu_kind", ATUKind.TEXT_TOKEN)
    atu = ATU(kind=ATUKind(kind), source=question.source)
    atu.candidates.append(
        Candidate(
            provider=provider_name,
            value=cand.value,
            confidence=cand.confidence,
            meta=cand.meta,
        )
    )
    question.atus.append(atu)


def _decompose(data: dict):
    """Structured extraction -> per-field ATU specs (kind, field, value)."""
    if data.get("number") is not None:
        yield ATUKind.QUESTION_NUMBER, "number", data["number"]
    if data.get("type"):
        yield ATUKind.TEXT_TOKEN, "type", data["type"]
    if data.get("points") is not None:
        yield ATUKind.POINTS, "points", data["points"]
    if data.get("body"):
        yield ATUKind.TEXT_TOKEN, "body", data["body"]
    for label, text in (data.get("choices") or {}).items():
        yield ATUKind.CHOICE, f"choice:{label}", text
    for i, latex in enumerate(data.get("equations") or []):
        yield ATUKind.MATH_SYMBOL, f"equation:{i}", latex
