from __future__ import annotations

from pathlib import Path

from document.models import BBox, Question, SourceRef
from ..context import PipelineContext


def run(ctx: PipelineContext) -> None:
    """Question segmentation: find question regions on each page."""
    questions: list[Question] = []
    ctx.page_extractions = {}  # page index -> [(provider name, item)] for runner
    for page in ctx.document.pages:
        image = ctx.resolve_uri(page.clean_uri or page.original.uri)
        page_questions: list[Question] = []
        for provider in ctx.providers.vision:
            for cand in _region_candidates(provider, image, page.index, ctx):
                position = len(questions) + len(page_questions) + 1
                label = str(cand.get("label") or cand.get("number") or position)
                page_questions.append(
                    Question(
                        number=position,
                        label=label,
                        source=SourceRef(
                            page=page.index,
                            bbox=_to_pixels(cand.get("bbox"), page.width, page.height),
                        ),
                    )
                )
        _extend_regions(page_questions, page)
        questions.extend(page_questions)
    ctx.document.questions = questions
    ctx.emit(
        "segmentation",
        f"{len(questions)}개 문항 영역 분리",
        "info" if questions else "warn",
    )


GAP = 6.0


def _region_candidates(provider, image: Path, page_index: int, ctx) -> list[dict]:
    """Prefer one-call page extraction (bbox + content); fall back to
    region-only detection for providers that lack it. Extraction items are
    stashed on the context so recognition doesn't re-call the provider."""
    if hasattr(provider, "extract_page"):
        for cand in provider.extract_page(image):
            items = cand.value if isinstance(cand.value, list) else []
            if items:
                ctx.page_extractions.setdefault(page_index, []).extend(
                    (provider.name, i) for i in items if isinstance(i, dict)
                )
                return items
    return [c.value for c in provider.detect_regions(image) if isinstance(c.value, dict)]


def _extend_regions(questions: list[Question], page) -> None:
    """Extend each region's bottom to the next question's top in the same
    column. Detected boxes often clip trailing choice lines."""
    if page.width is None or page.height is None:
        return
    columns: dict[int, list[Question]] = {}
    for q in questions:
        b = q.source.bbox if q.source else None
        if b is None:
            continue
        col = 1 if b.x + b.w / 2 > page.width / 2 else 0
        columns.setdefault(col, []).append(q)
    for col_questions in columns.values():
        col_questions.sort(key=lambda q: q.source.bbox.y)
        for i, q in enumerate(col_questions):
            b = q.source.bbox
            if i + 1 < len(col_questions):
                bottom = col_questions[i + 1].source.bbox.y - GAP
            else:
                bottom = min(page.height - GAP, b.y + b.h * 3)
            if bottom > b.y + b.h:
                b.h = bottom - b.y


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
