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
    """Apply the independence-aware consensus rules to one ATU."""
    if atu.status == VerificationStatus.HUMAN_VERIFIED:
        return  # human decisions are never re-litigated by machines
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
    """Populate question fields from verified ATUs only.

    `number` stays the stable positional index; the extracted printed
    number/label (e.g. "13", "논술형 2", "2-1") goes to `label`.
    """
    verified = {VerificationStatus.AUTO_VERIFIED, VerificationStatus.HUMAN_VERIFIED}
    for q in document.questions:
        choices: dict[str, str] = {}
        for atu in q.atus:
            if atu.status not in verified or atu.field is None:
                continue
            if atu.field == "number":
                extracted = str(atu.value)
                if not q.label or (q.label.isdigit() and not extracted.isdigit()):
                    q.label = extracted
            elif atu.field == "body":
                q.body.append(TextSpan(text=str(atu.value), atu_ids=[atu.id]))
            elif atu.field == "figure":
                q.figures.append(Figure(topology={"description": str(atu.value)}))
            elif atu.field == "points":
                try:
                    q.points = int(atu.value)
                except (TypeError, ValueError):
                    pass
            elif atu.field == "type":
                try:
                    q.type = type(q.type)(atu.value)
                except ValueError:
                    pass
            elif atu.field.startswith("choice:"):
                choices[atu.field.split(":", 1)[1]] = str(atu.value)
            elif atu.field.startswith("equation:"):
                q.equations.append(Equation(latex=str(atu.value), source=atu.source))
        q.choices = [
            Choice(label=label, body=[TextSpan(text=text)]) for label, text in choices.items()
        ]
    _sort_questions(document)
    _link_subquestions(document)


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
