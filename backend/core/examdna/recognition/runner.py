from __future__ import annotations

from pathlib import Path

from document.models import ATU, ATUKind, Candidate
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Multi-recognition: providers produce Candidates, never final values."""
    for page in ctx.document.pages:
        image = Path(page.clean_uri or page.original.uri)
        for question in ctx.document.questions:
            region = question.source.bbox if question.source else None
            _collect(
                question,
                image,
                region,
                ctx.providers.ocr,
                lambda p: p.recognize_text(image, region),
            )
            _collect(
                question,
                image,
                region,
                ctx.providers.math_ocr,
                lambda p: p.recognize_math(image, region),
            )

    atu_count = sum(len(q.atus) for q in ctx.document.questions)
    ctx.emit("recognition", f"{atu_count}개 ATU 후보 수집")


def _collect(question, image: Path, region, providers, call) -> None:
    for provider in providers:
        for cand in call(provider):
            kind = cand.meta.get("atu_kind", ATUKind.TEXT_TOKEN)
            atu = ATU(kind=ATUKind(kind), source=question.source)
            atu.candidates.append(
                Candidate(
                    provider=provider.name,
                    value=cand.value,
                    confidence=cand.confidence,
                    meta=cand.meta,
                )
            )
            question.atus.append(atu)
