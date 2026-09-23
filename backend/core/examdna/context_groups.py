"""Context groups + bounded per-unit execution (Phase 1).

A shared stem, table, graph, multipart, or cross-page question is one
context group — its members must be solved/verified with shared context
and fail together. Ordinary questions are singleton groups: restored
independently so one pathological item cannot sink the document, and so
units can be retried, cached, and parallelized by the scheduler
(Phase 3) without re-running the whole exam.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from document.models import Document, Question


@dataclass
class ContextGroup:
    id: str
    question_ids: list[str]
    reason: str                      # singleton | shared_stem | cross_page
    page_indexes: list[int] = field(default_factory=list)


def build_context_groups(doc: Document) -> list[ContextGroup]:
    """Group canonical questions into independent units of work.

    - children sharing a parent stem -> one group (shared_stem)
    - questions spanning multiple pages -> one group (cross_page)
    - everything else -> singleton
    Parent (stem-only) questions are not solved alone — they ride along
    as context in their children's payloads.
    """
    groups: list[ContextGroup] = []
    parent_children: dict[str, list[str]] = {}
    for q in doc.questions:
        if q.parent_id:
            parent_children.setdefault(q.parent_id, []).append(q.id)

    grouped: set[str] = set()
    for parent_id, children in parent_children.items():
        pages = sorted(
            {
                (q.source.page if q.source else -1)
                for q in doc.questions
                if q.id in children or q.id == parent_id
            }
        )
        groups.append(
            ContextGroup(
                id=f"grp_{parent_id}",
                question_ids=children,
                reason="shared_stem" + ("+cross_page" if len(pages) > 1 else ""),
                page_indexes=pages,
            )
        )
        grouped.update(children)
        grouped.add(parent_id)

    for q in doc.questions:
        if q.id in grouped:
            continue
        page = q.source.page if q.source else -1
        groups.append(
            ContextGroup(
                id=f"grp_{q.id}",
                question_ids=[q.id],
                reason="singleton",
                page_indexes=[page] if page >= 0 else [],
            )
        )
    return groups


@dataclass
class UnitResult:
    """Outcome of one context group — evidence and timing, never a
    swallowed exception."""

    group_id: str
    status: str            # SUCCEEDED | FAILED | NEEDS_REVIEW
    duration_s: float
    result: Any = None
    error: Optional[str] = None
    evidence: dict[str, Any] = field(default_factory=dict)


def run_units(
    groups: list[ContextGroup],
    fn: Callable[[ContextGroup], Any],
) -> list[UnitResult]:
    """Run `fn` per group with isolation: one group's exception is
    recorded as a FAILED unit, not a pipeline crash. Sequential here —
    Phase 3's scheduler owns concurrency, fairness, and cancellation."""
    out: list[UnitResult] = []
    for g in groups:
        t0 = time.time()
        try:
            res = fn(g)
            status = (
                res.status
                if isinstance(res, UnitResult)
                else "SUCCEEDED"
            )
            out.append(
                UnitResult(
                    group_id=g.id,
                    status=status,
                    duration_s=time.time() - t0,
                    result=None if isinstance(res, UnitResult) else res,
                    evidence=(res.evidence if isinstance(res, UnitResult) else {}),
                )
            )
        except Exception as exc:  # noqa: BLE001 — isolation boundary
            out.append(
                UnitResult(
                    group_id=g.id,
                    status="FAILED",
                    duration_s=time.time() - t0,
                    error=f"{type(exc).__name__}: {exc}"[:300],
                )
            )
    return out


def questions_of(group: ContextGroup, doc: Document) -> list[Question]:
    by_id = {q.id: q for q in doc.questions}
    return [by_id[i] for i in group.question_ids if i in by_id]
