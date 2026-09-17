from __future__ import annotations

from pathlib import Path

from document.models import BBox, Question, SourceRef
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
                        source=SourceRef(
                            page=page.index,
                            bbox=_to_pixels(cand.value.get("bbox"), page.width, page.height),
                        ),
                    )
                )
    ctx.document.questions = questions
    ctx.emit(
        "segmentation",
        f"{len(questions)}개 문항 영역 분리",
        "info" if questions else "warn",
    )


def _to_pixels(norm: dict | None, width: float | None, height: float | None) -> BBox | None:
    """Provider boxes are normalized to a 1000x1000 grid."""
    if not norm or not width or not height:
        return None
    return BBox(
        x=norm["xmin"] / 1000 * width,
        y=norm["ymin"] / 1000 * height,
        w=(norm["xmax"] - norm["xmin"]) / 1000 * width,
        h=(norm["ymax"] - norm["ymin"]) / 1000 * height,
    )
