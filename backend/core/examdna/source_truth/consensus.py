from __future__ import annotations

import re

from document.models import (
    ATU,
    ATUKind,
    Choice,
    Document,
    Equation,
    Figure,
    Question,
    TextSpan,
    VerificationStatus,
)
from ..context import PipelineContext

# RESTORE-05: a confidence number alone never settles a value, and a
# majority of correlated readings is not independent evidence.
# AUTO_VERIFIED requires >=2 independent evidence sources agreeing on the
# exact value. Independence rules (spec 3.1):
#   - the same provider reading twice / retrying = one source
#   - paired reference HWPs ("reference:*") = one evidence family — they
#     may share an upstream origin, so two matching references are still
#     a single source
#   - anything else -> UNVERIFIED (humans or more evidence decide)
MIN_INDEPENDENT_SOURCES = 2

# Critical fields demand exact agreement — no fuzzy matching, ever.
_CRITICAL_KINDS = {
    ATUKind.QUESTION_NUMBER,
    ATUKind.NUMBER,
    ATUKind.VARIABLE,
    ATUKind.MATH_SYMBOL,
    ATUKind.UNIT,
    ATUKind.POINTS,
    ATUKind.CHOICE,
    ATUKind.FIGURE_LABEL,
    ATUKind.ANGLE,
    ATUKind.LENGTH,
}


def run(ctx: PipelineContext) -> None:
    """Source Truth: turn Candidates into verified values via consensus.

    Rules:
    - >=2 independent sources agree exactly -> AUTO_VERIFIED
    - sources disagree on value             -> CONFLICT
    - a single source (any confidence)      -> stays UNVERIFIED
    - no candidates                         -> UNREADABLE
    """
    counts = {s: 0 for s in VerificationStatus}
    for atu in ctx.document.all_atus():
        _settle(atu)
        counts[atu.status] += 1

    _materialize(ctx.document)

    summary = ", ".join(f"{s.value}={n}" for s, n in counts.items() if n)
    ctx.emit("source_verification", f"원본 대조 완료 — {summary or 'ATU 없음'}")


def _settle(atu: ATU) -> None:
    """Apply the independence-aware consensus rules to one ATU, and
    record its evidence-class bundle (RESTORE-16) — a summary for
    review, never a weakening of the independence policy."""
    from document.evidence import bundle_for

    if atu.status == VerificationStatus.HUMAN_VERIFIED:
        atu.evidence = bundle_for(atu.candidates).model_dump()
        return  # human decisions are never re-litigated by machines
    atu.evidence = bundle_for(atu.candidates).model_dump()
    if not atu.candidates:
        atu.status = VerificationStatus.UNREADABLE
        return
    # value -> set of independent source keys
    by_value: dict[str, set[str]] = {}
    rep: dict[str, object] = {}
    for c in atu.candidates:
        key = _source_key(c.provider)
        v = repr(c.value)
        by_value.setdefault(v, set()).add(key)
        rep.setdefault(v, c.value)
    if len(by_value) > 1:
        atu.status = VerificationStatus.CONFLICT
        atu.note = _conflict_note(by_value)
        return
    value_repr, sources = next(iter(by_value.items()))
    if len(sources) >= MIN_INDEPENDENT_SOURCES:
        atu.value = rep[value_repr]
        atu.status = VerificationStatus.AUTO_VERIFIED
        atu.note = f"independent_sources:{len(sources)}"
    else:
        # One source — however confident — is a candidate, not a verdict.
        atu.status = VerificationStatus.UNVERIFIED
        atu.note = "single_source"


def _source_key(provider: str) -> str:
    """Collapse correlated candidates into one evidence source.

    `reference:*` providers (paired HWP/HWPX files) share one family: two
    academies' copies of the same exam are not independent proof.
    """
    name = (provider or "").strip()
    if name.startswith("reference"):
        return "reference"
    return name


def _conflict_note(by_value: dict[str, set[str]]) -> str:
    parts = []
    for v, keys in sorted(by_value.items()):
        label = v if len(v) <= 40 else v[:37] + "..."
        parts.append(f"{label}<-{'/'.join(sorted(keys))}")
    return "conflict:" + "; ".join(parts)


def _materialize(document: Document) -> None:
    """Populate final fields and an inspectable draft from ATU candidates.

    Verified ATUs populate final fields. A single-source, non-conflicting
    candidate may also populate a *draft* field so a reviewer can inspect the
    restoration before confirmation. Draft content never changes ATU status,
    so it cannot make ZERO TYPO GATE pass.

    `number` stays the stable positional index; the extracted printed
    number/label (e.g. "13", "논술형 2", "2-1") goes to `label`.
    """
    verified = {VerificationStatus.AUTO_VERIFIED, VerificationStatus.HUMAN_VERIFIED}
    for q in document.questions:
        draft_body: list[TextSpan] = []
        draft_choices: dict[str, str] = {}
        choices: dict[str, str] = {}
        for atu in q.atus:
            if atu.field is None:
                continue
            is_verified = atu.status in verified
            source_atu = atu if is_verified else _safe_draft_atu(atu)
            if source_atu is None:
                continue
            value = (
                atu.value
                if is_verified and atu.value is not None
                else source_atu.candidates[0].value
            )
            if atu.field == "number":
                if is_verified:
                    extracted = str(value)
                    if not q.label or (q.label.isdigit() and not extracted.isdigit()):
                        q.label = extracted
            elif atu.field == "body":
                span = TextSpan(text=str(value), atu_ids=[atu.id])
                if is_verified:
                    q.body.append(span)
                else:
                    draft_body.append(span)
            elif atu.field == "figure":
                if is_verified:
                    q.figures.append(_materialize_figure(atu, q))
            elif atu.field == "points":
                try:
                    q.points = int(value)
                except (TypeError, ValueError):
                    pass
            elif atu.field == "type":
                try:
                    q.type = type(q.type)(value)
                except ValueError:
                    pass
            elif atu.field.startswith("choice:"):
                target = choices if is_verified else draft_choices
                target[atu.field.split(":", 1)[1]] = str(value)
            elif atu.field.startswith("equation:"):
                if is_verified:
                    q.equations.append(Equation(latex=str(value), source=atu.source))
        if not q.body and draft_body:
            q.body = draft_body
        if not choices and draft_choices:
            choices = draft_choices
        q.choices = [
            Choice(label=label, body=[TextSpan(text=text)]) for label, text in choices.items()
        ]
    _sort_questions(document)
    _link_subquestions(document)


def _safe_draft_atu(atu: ATU) -> ATU | None:
    """Use an unverified ATU in a draft only when all readings agree."""
    if atu.status != VerificationStatus.UNVERIFIED or not atu.candidates:
        return None
    # Keep weak/low-confidence readings in the review package without
    # presenting them as usable draft text. Strong local-VLM page candidates
    # are emitted at >=0.7; the threshold also preserves the existing
    # low-confidence OCR contract.
    if max((candidate.confidence for candidate in atu.candidates), default=0.0) < 0.7:
        return None
    if len({repr(candidate.value) for candidate in atu.candidates}) != 1:
        return None
    return atu


def _materialize_figure(atu: ATU, q: Question) -> Figure:
    """Build the Figure for a verified figure ATU.

    A dict value carrying a `scene` payload is parsed as a FigureScene and
    checked twice — structural validation plus semantic consistency —
    before it is attached. Any defect flags the question `invalid_figure`
    so the gate can never pass a malformed or self-contradictory figure
    (RESTORE-06); the figure is still attached so review can inspect it.
    """
    from document.models import LogicFlag
    from document.scene import FigureScene, validate_scene
    from document.scene_semantics import check_scene

    value = atu.value
    if not isinstance(value, dict) or "scene" not in value:
        return Figure(topology={"description": str(value)}, source=atu.source)

    fig = Figure(
        topology={"description": str(value.get("description") or "")},
        source=atu.source,
    )
    try:
        scene = FigureScene(**value["scene"])
    except Exception as exc:  # noqa: BLE001 — malformed payload is data
        q.verification.logic_flags.append(
            LogicFlag(kind="invalid_figure", detail=f"scene parse: {exc}")
        )
        return fig
    errors = validate_scene(scene)
    errors += [f"{i.kind}: {i.detail}" for i in check_scene(scene)]
    fig.scene = scene
    if errors:
        fig.topology["issues"] = errors
        q.verification.logic_flags.append(
            LogicFlag(
                kind="invalid_figure",
                detail="; ".join(errors[:5]),
            )
        )
    return fig


_SUBQ = re.compile(r"^(\d+)-(\d+)$")


def _link_subquestions(document: Document) -> None:
    """Link 'N-M' sub-questions to their shared-stem group question.

    The group stem (e.g. '논술형 2') is a separate detected region; the
    sub-question needs its body/figures as context for solving and render.
    """
    by_label = {q.label: q for q in document.questions if q.label}
    for q in document.questions:
        m = _SUBQ.match(q.label or "")
        if not m:
            continue
        group = m.group(1)
        candidates = [
            p
            for label, p in by_label.items()
            if p is not q and "-" not in label and group in re.findall(r"\d+", label)
        ]
        # A group stem like "논술형 2" outranks a plain numbered question "2".
        parent = next(
            (p for p in candidates if not (p.label or "").replace(" ", "").isdigit()),
            candidates[0] if candidates else None,
        )
        if parent:
            q.parent_id = parent.id


def _sort_questions(document: Document) -> None:
    """Reading-order sort: page -> column -> top-to-bottom, then renumber."""
    def key(q: Question):
        page = q.source.page if q.source else 0
        bbox = q.source.bbox if q.source else None
        width = document.pages[page].width if page < len(document.pages) else 0
        col = 1 if bbox and width and bbox.x + bbox.w / 2 > width / 2 else 0
        return (page, col, bbox.y if bbox else 0.0, bbox.x if bbox else 0.0)

    document.questions.sort(key=key)
    for i, q in enumerate(document.questions, 1):
        q.number = i
