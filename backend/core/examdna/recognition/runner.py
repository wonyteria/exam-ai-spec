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
            for attempt in range(3):
                before = len(question.atus)
                for cand in provider.recognize_text(image, region):
                    _ingest(question, provider.name, cand)
                if _extraction_adequate(question, before):
                    break
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


def _extraction_adequate(question: Question, before: int) -> bool:
    if len(question.atus) == before:
        return False
    fields = {a.field for a in question.atus}
    if "type" in fields and "choice:1" not in fields:
        mc = any(
            a.field == "type" and a.candidates and a.candidates[0].value == "multiple_choice"
            for a in question.atus
        )
        if mc and not any(f.startswith("choice:") for f in fields):
            return False
    return True


_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


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
    choices = data.get("choices")
    if isinstance(choices, dict):
        items = list(choices.items())
    elif isinstance(choices, list):
        items = [
            (_CIRCLED[i] if i < len(_CIRCLED) else str(i + 1), text)
            for i, text in enumerate(choices)
        ]
    else:
        items = []
    for label, text in items:
        yield ATUKind.CHOICE, f"choice:{label}", text
    for i, latex in enumerate(data.get("equations") or []):
        yield ATUKind.MATH_SYMBOL, f"equation:{i}", latex
    if data.get("figure"):
        yield ATUKind.TEXT_TOKEN, "figure", data["figure"]
