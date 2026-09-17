from __future__ import annotations

from pathlib import Path

from document.models import Question, SourceRef
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Question segmentation: find question regions on each page."""
    questions: list[Question] = []
    for page in ctx.document.pages:
        image = Path(page.clean_uri or page.original.uri)
        for provider in ctx.providers.vision:
            for cand in provider.detect_regions(image):
                questions.append(
                    Question(
                        number=int(cand.value.get("number", len(questions) + 1)),
                        source=SourceRef(page=page.index, bbox=cand.value.get("bbox")),
                    )
                )
    ctx.document.questions = questions
    ctx.emit(
        "segmentation",
        f"{len(questions)}개 문항 영역 분리",
        "info" if questions else "warn",
    )
