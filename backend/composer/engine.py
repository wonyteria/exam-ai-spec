"""RESTORE-28 — Exam Composer.

Compose a new exam from a question pool using QuestionDNA features:
difficulty mix ("상 5 / 중 7 / 하 3"), unit/concept filters, and a
time budget. A/B/C형 versions are produced by deterministic order +
choice permutation (Variation Engine), each with its own answer key.

Selection never fabricates questions — it only picks from the pool;
an unfillable spec reports the shortfall explicitly.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Any, Optional

from document.models import Document, Question
from question_dna.dna import derive_dna
from variation.engine import shuffle_choices


@dataclass
class ComposeSpec:
    count: Optional[int] = None
    difficulty_mix: dict[str, int] = field(default_factory=dict)  # 상/중/하
    units: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    time_budget_min: Optional[float] = None
    versions: int = 1
    seed: Optional[int] = None


@dataclass
class ComposeResult:
    exams: list[Document]
    answer_keys: list[dict[int, str]]  # per-version {number: answer}
    unfilled: dict[str, int]           # requested-but-unavailable slots
    total_estimated_minutes: float


def _dna(q: Question) -> dict[str, Any]:
    if q.question_dna is None:
        q.question_dna = derive_dna(q)
    return q.question_dna


def select_questions(
    pool: list[Question], spec: ComposeSpec
) -> tuple[list[Question], dict[str, int]]:
    """Pick questions satisfying the spec; returns (picked, unfilled)."""
    rng = random.Random(spec.seed)
    candidates = list(pool)
    if spec.units:
        candidates = [
            q for q in candidates if _dna(q).get("unit") in spec.units
        ]
    if spec.concepts:
        want = set(spec.concepts)
        candidates = [
            q for q in candidates
            if want & set(_dna(q).get("concepts", []))
        ]
    rng.shuffle(candidates)

    picked: list[Question] = []
    unfilled: dict[str, int] = {}
    if spec.difficulty_mix:
        for band, n in spec.difficulty_mix.items():
            have = [
                q for q in candidates
                if _dna(q).get("difficulty_band") == band
                and q not in picked
            ]
            take = have[:n]
            picked.extend(take)
            if len(take) < n:
                unfilled[band] = n - len(take)
    if spec.count is not None and not spec.difficulty_mix:
        picked = candidates[: spec.count]
        if len(picked) < spec.count:
            unfilled["count"] = spec.count - len(picked)
    elif spec.count is not None:
        picked = picked[: spec.count]
        if len(picked) < spec.count:
            unfilled["count"] = spec.count - len(picked)

    if spec.time_budget_min is not None:
        kept: list[Question] = []
        total = 0.0
        for q in sorted(
            picked, key=lambda x: _dna(x).get("estimated_time", 0)
        ):
            t = _dna(q).get("estimated_time", 0)
            if total + t <= spec.time_budget_min:
                kept.append(q)
                total += t
        dropped = len(picked) - len(kept)
        if dropped:
            unfilled["time_budget"] = dropped
        picked = kept
    return picked, unfilled


def compose_exam(
    pool_doc: Document, spec: ComposeSpec, title: str = ""
) -> ComposeResult:
    """Build `spec.versions` exams from the pool. Each version permutes
    question order and choice order deterministically; per-version
    answer keys reflect the permuted labels."""
    picked, unfilled = select_questions(pool_doc.questions, spec)
    total_min = sum(_dna(q).get("estimated_time", 0) for q in picked)

    exams: list[Document] = []
    keys: list[dict[int, str]] = []
    for v in range(spec.versions):
        rng = random.Random((spec.seed or 0) + v * 7919)
        doc = Document()
        doc.tenant_id = pool_doc.tenant_id
        doc.metadata = copy.deepcopy(pool_doc.metadata)
        if title:
            doc.metadata.title = f"{title} {chr(65 + v)}형"
        order = list(picked)
        rng.shuffle(order)
        key: dict[int, str] = {}
        for i, src in enumerate(order, start=1):
            q = copy.deepcopy(src)
            q.number = i
            q.label = str(i)
            # choice permutation per version
            if len(q.choices) >= 2:
                variant = shuffle_choices(q, seed=(spec.seed or 0) + v * 97 + i)
                perm = variant.params["permutation"]
                q.choices = [q.choices[j] for j in perm]
                if variant.new_answer is not None:
                    q.answer.value = variant.new_answer
            key[i] = (
                str(q.answer.value)
                if q.answer is not None and q.answer.value is not None
                else "(미확정)"
            )
            doc.questions.append(q)
        exams.append(doc)
        keys.append(key)
    return ComposeResult(
        exams=exams,
        answer_keys=keys,
        unfilled=unfilled,
        total_estimated_minutes=round(total_min, 1),
    )
