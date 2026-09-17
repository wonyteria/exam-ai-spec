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
                label = str(cand.value.get("label", len(questions) + 1))
                number, parsed_label = _parse_label(label, len(questions) + 1)
                questions.append(
                    Question(
                        number=number,
                        label=parsed_label,
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


def _parse_label(label: str, fallback: int) -> tuple[int, str | None]:
    try:
        return int(label), None
    except ValueError:
        return fallback, label


PAD = 0.04


def _to_pixels(norm: dict | None, width: float | None, height: float | None) -> BBox | None:
    """Provider boxes are normalized to a 1000x1000 grid.

    Boxes get padded: detected regions tend to clip trailing choice lines.
    """
    if not norm or not width or not height:
        return None
    x = max(0.0, norm["xmin"] / 1000 * width - PAD * width)
    y = max(0.0, norm["ymin"] / 1000 * height - PAD * height)
    x2 = min(width, norm["xmax"] / 1000 * width + PAD * width)
    y2 = min(height, norm["ymax"] / 1000 * height + PAD * height)
    return BBox(x=x, y=y, w=x2 - x, h=y2 - y)
