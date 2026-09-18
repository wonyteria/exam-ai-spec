from __future__ import annotations

from pathlib import Path

from document.models import ATU, ATUKind, Candidate, Question
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Multi-recognition: providers produce Candidates, never final values.

    Cost-efficient path: one extract_page call per page covers detection and
    extraction. Per-question recognize_text retries only for inadequate
    fields (missing body/choices).
    """
    page_items = _page_extractions(ctx)
    for question in ctx.document.questions:
        for provider_name, item in page_items.get(_page_of(question), []):
            if _label_matches(item.get("label"), question):
                _ingest_fields(question, provider_name, item)
        for provider in ctx.providers.math_ocr:
            image, region = _question_image(ctx, question)
            if image is None:
                continue
            for cand in provider.recognize_math(image, region):
                _ingest(question, provider.name, cand)

    # Targeted fallback: only questions still missing fields get per-region calls
    for question in ctx.document.questions:
        if _extraction_adequate(question, -1):
            continue
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

    atu_count = sum(len(q.atus) for q in ctx.document.questions)
    ctx.emit("recognition", f"{atu_count}개 ATU 후보 수집")


def _page_of(question: Question) -> int:
    return question.source.page if question.source else -1


def _page_extractions(ctx: PipelineContext) -> dict[int, list[tuple[str, dict]]]:
    """extract_page results keyed by page index — reused from segmentation
    when available so the provider is only called once per page."""
    stashed = getattr(ctx, "page_extractions", None)
    if stashed is not None:
        return stashed
    out: dict[int, list[tuple[str, dict]]] = {}
    for page in ctx.document.pages:
        image = Path(page.clean_uri or page.original.uri)
        for provider in ctx.providers.vision:
            if not hasattr(provider, "extract_page"):
                continue
            for cand in provider.extract_page(image):
                if isinstance(cand.value, list) and cand.value:
                    out.setdefault(page.index, []).extend(
                        (provider.name, i) for i in cand.value if isinstance(i, dict)
                    )
    return out


def _label_matches(item_label, question: Question) -> bool:
    item = str(item_label or "")
    return item == (question.label or str(question.number))


def _ingest_fields(question: Question, provider_name: str, item: dict) -> None:
    data = dict(item)
    data.pop("bbox", None)
    data["number"] = data.pop("label", None)
    for kind, field, value in _decompose(data):
        atu = ATU(kind=kind, field=field, source=question.source)
        atu.candidates.append(
            Candidate(provider=provider_name, value=value, confidence=0.9, meta={})
        )
        question.atus.append(atu)


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
    if len(question.atus) == before or not question.atus:
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
