"""Brand/template registry (WP07 / REQ-16).

Brand affects *presentation only* — fonts, header text, accent styling.
The content semantic hash is computed over questions/answers, so
switching brands must never alter content (브랜드 변경 전후 내용 동일);
renderers take a resolved BrandTemplate and cannot reach content state.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BrandTemplate:
    id: str
    version: str
    name: str
    body_font: str = "함초롬바탕"
    header_text: str = ""
    accent_color: str = "#000000"
    footer_note: str = ""


_REGISTRY: dict[str, BrandTemplate] = {
    "default": BrandTemplate(
        id="default",
        version="1",
        name="기본",
        body_font="함초롬바탕",
    ),
    "examdna": BrandTemplate(
        id="examdna",
        version="1",
        name="ExamDNA 표준",
        body_font="함초롬바탕",
        header_text="ExamDNA 복원 시험지",
        accent_color="#1a4a8a",
    ),
    "minimal": BrandTemplate(
        id="minimal",
        version="1",
        name="미니멀",
        body_font="함초롬바탕",
        accent_color="#666666",
    ),
}


def get_brand(brand_id: str | None) -> BrandTemplate:
    """Resolve a brand; unknown ids fall back to default — a typo'd
    brand_id must not corrupt output or fail rendering."""
    return _REGISTRY.get(brand_id or "default", _REGISTRY["default"])


def register_brand(template: BrandTemplate) -> None:
    """Runtime registry extension (tenant branding lands here via WP10
    ops config — never by editing this file per academy)."""
    _REGISTRY[template.id] = template


def list_brands() -> list[BrandTemplate]:
    return list(_REGISTRY.values())
