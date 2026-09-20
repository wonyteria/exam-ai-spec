"""RESTORE-23 — AcademyDNA MVP.

Spec §38-39: Academy Profile (academy_name, logo, address, phone,
subjects, grades, brand) + StyleDNA extracted from the academy's own
uploaded exams (page size, margins, columns, fonts, header/footer,
number/choice/score style). Content and style stay separate:
Canonical Exam + Academy Style Profile -> Renderer -> Academy Exam.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from document.models import Document

EXAM_PROFILE_KINDS = {
    "weekly_test",
    "homework",
    "midterm",
    "final",
    "mock_exam",
}


class AcademyProfile(BaseModel):
    academy_id: str
    academy_name: str
    logo_uri: Optional[str] = None
    address: str = ""
    phone: str = ""
    subjects: list[str] = Field(default_factory=list)
    grades: list[str] = Field(default_factory=list)
    brand_id: Optional[str] = None


class StyleDNA(BaseModel):
    """Style extracted from an academy's own exam — never copied blindly;
    every field records which document/page produced it."""

    page_size: Optional[list[float]] = None  # [w, h] in pt
    columns: int = 2
    fonts: list[str] = Field(default_factory=list)
    header_text: Optional[str] = None
    footer_has_page_number: Optional[bool] = None
    number_style: str = "arabic_dot"     # "1." | "1)" | "[1]"
    choice_style: str = "circled"        # ①②③ | (1)(2)(3) | 1.2.3.
    score_style: str = "bracket"         # [4점] | (4점) | 4점
    evidence: dict[str, Any] = Field(default_factory=dict)


def extract_style(doc: Document) -> StyleDNA:
    """Derive StyleDNA from a restored document's measured facts —
    page inventory (fonts/size) + question numbering conventions."""
    style = StyleDNA()
    ev: dict[str, Any] = {}
    for page in doc.pages:
        inv = page.inventory
        if inv:
            if inv.width_pt and style.page_size is None:
                style.page_size = [inv.width_pt, inv.height_pt]
                ev["page_size_from"] = f"page[{page.index}].inventory"
            for f in inv.fonts:
                if f not in style.fonts:
                    style.fonts.append(f)
            if inv.fonts:
                ev["fonts_from"] = f"page[{page.index}].inventory.fonts"
    labels = [q.label or "" for q in doc.questions]
    if any(re.fullmatch(r"\d+\.", lb) for lb in labels):
        style.number_style = "arabic_dot"
    elif any(re.fullmatch(r"\d+\)", lb) for lb in labels):
        style.number_style = "paren"
    if doc.questions:
        labels0 = [c.label for c in doc.questions[0].choices]
        if labels0 and all(re.fullmatch(r"[①-⑮]", l) for l in labels0):
            style.choice_style = "circled"
        elif labels0 and all(re.fullmatch(r"\(\d+\)", l) for l in labels0):
            style.choice_style = "paren_number"
        ev["choice_style_from"] = f"question[{doc.questions[0].number}]"
    style.evidence = ev
    return style


def apply_style(
    doc: Document,
    profile: AcademyProfile,
    style: Optional[StyleDNA] = None,
    exam_kind: str = "weekly_test",
) -> dict[str, Any]:
    """Compose the render-time style bundle. Returns the parameters a
    renderer consumes — the Document itself is not mutated (content and
    style are separate; a revision records the binding)."""
    if exam_kind not in EXAM_PROFILE_KINDS:
        raise ValueError(f"unknown exam profile kind {exam_kind!r}")
    return {
        "brand_id": profile.brand_id,
        "header_text": profile.academy_name,
        "logo_uri": profile.logo_uri,
        "contact": {
            "address": profile.address,
            "phone": profile.phone,
        },
        "page_size": (style.page_size if style else None),
        "columns": style.columns if style else 2,
        "number_style": style.number_style if style else "arabic_dot",
        "choice_style": style.choice_style if style else "circled",
        "score_style": style.score_style if style else "bracket",
        "exam_kind": exam_kind,
    }
