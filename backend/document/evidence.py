"""EvidenceDNA — evidence classification for candidates (RESTORE-16).

Every candidate carries one evidence class, and an ATU's bundle
summarizes which classes contributed:

    SOURCE       — the source document itself: paired reference HWP/HWPX
                   files, the native PDF text layer. Multiple reference
                   files are ONE source (they may share an upstream
                   origin).
    OBSERVATION  — provider readings: OCR lines, layout detections,
                   solver outputs. Different provider names are
                   independent observations of the same ink.
    CONSISTENCY  — deterministic checks: SymPy equivalence, manifest
                   reconciliation, hash matches. Corroborates, never
                   originates a value.
    HUMAN        — explicit user confirmation. Outranks everything;
                   machine logic never re-litigates it.

A bundle is a summary for review — it does not change consensus rules,
which stay provider-key-based and conservative.
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable

from pydantic import BaseModel, Field


class EvidenceClass(str, Enum):
    SOURCE = "SOURCE"
    OBSERVATION = "OBSERVATION"
    CONSISTENCY = "CONSISTENCY"
    HUMAN = "HUMAN"


_SOURCE_PREFIXES = ("reference", "native_pdf", "pdf_text")
_HUMAN_PREFIXES = ("human", "user", "reviewer")
_CONSISTENCY_PREFIXES = ("math_checker", "sympy", "manifest", "hash")


def classify_candidate(candidate) -> EvidenceClass:
    """Map a candidate's provider to its evidence class."""
    name = (getattr(candidate, "provider", "") or "").strip().lower()
    if name.startswith(_HUMAN_PREFIXES):
        return EvidenceClass.HUMAN
    if name.startswith(_SOURCE_PREFIXES):
        return EvidenceClass.SOURCE
    if name.startswith(_CONSISTENCY_PREFIXES):
        return EvidenceClass.CONSISTENCY
    return EvidenceClass.OBSERVATION


class EvidenceBundle(BaseModel):
    """Per-ATU summary: which evidence classes backed the value."""

    source: int = 0
    observation: int = 0
    consistency: int = 0
    human: int = 0

    def classes_present(self) -> list[EvidenceClass]:
        return [
            cls
            for cls in EvidenceClass
            if getattr(self, cls.value.lower()) > 0
        ]


def bundle_for(candidates: Iterable) -> EvidenceBundle:
    bundle = EvidenceBundle()
    for c in candidates:
        key = classify_candidate(c).value.lower()
        setattr(bundle, key, getattr(bundle, key) + 1)
    return bundle
