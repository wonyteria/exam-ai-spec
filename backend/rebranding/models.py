"""Data contracts for safe rebranding of existing HWP/HWPX (REQ-16).

Mirrors docs/handoff/HWP_REBRANDING_SPEC.md §4. The scanner produces a
BrandStructureManifest; the planner turns confirmed candidates into a
BrandRewritePlan whose operations are the *only* allowed mutations.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# --- candidates ---------------------------------------------------------------

class CandidateKind(str, Enum):
    # title candidates
    TITLE_HEADER_TEXT = "TITLE_HEADER_TEXT"
    TITLE_HEADER_TABLE_CELL = "TITLE_HEADER_TABLE_CELL"
    TITLE_MASTER_TEXT = "TITLE_MASTER_TEXT"
    TITLE_BODY_TOP = "TITLE_BODY_TOP"
    TITLE_IMAGE = "TITLE_IMAGE"  # academy name possibly fused into a picture
    # page-number mechanisms (spec §2 — five distinct paths)
    PAGE_NUM_CONTROL = "PAGE_NUM_CONTROL"            # dedicated 쪽번호 위치 control
    PAGE_NUM_FIELD = "PAGE_NUM_FIELD"                # autoNum PAGE inside header/footer
    PAGE_NUM_MASTER_FIELD = "PAGE_NUM_MASTER_FIELD"  # autoNum PAGE inside master page
    PRINT_PAGE_TOKEN = "PRINT_PAGE_TOKEN"            # print-only header/footer ^p token
    LITERAL_PAGE_NUMBER = "LITERAL_PAGE_NUMBER"      # digits/image baked into footer
    # watermark inventory
    EXISTING_WATERMARK = "EXISTING_WATERMARK"


PAGE_NUMBER_KINDS = {
    CandidateKind.PAGE_NUM_CONTROL,
    CandidateKind.PAGE_NUM_FIELD,
    CandidateKind.PAGE_NUM_MASTER_FIELD,
    CandidateKind.PRINT_PAGE_TOKEN,
    CandidateKind.LITERAL_PAGE_NUMBER,
}

TITLE_KINDS = {
    CandidateKind.TITLE_HEADER_TEXT,
    CandidateKind.TITLE_HEADER_TABLE_CELL,
    CandidateKind.TITLE_MASTER_TEXT,
    CandidateKind.TITLE_BODY_TOP,
    CandidateKind.TITLE_IMAGE,
}


class ControlCandidate(BaseModel):
    """One inventoried control the rewrite *may* touch. `path` is the exact
    structural address the mutator resolves — never a text search."""

    id: str = Field(default_factory=lambda: _new_id("cand"))
    kind: CandidateKind
    section: str                      # e.g. "section0.xml"
    path: str                         # exact control path, e.g. "section0/ctrl[0]/header/sublist/p[1]/run[0]"
    apply_page_type: str = "BOTH"     # BOTH | EVEN | ODD | FIRST (header/footer scope)
    layer: str = "body"               # header | footer | master_page | body | settings
    text_preview: str = ""
    bbox: Optional[dict[str, float]] = None
    confidence: float = 0.0           # 0..1 — below AUTO_MIN requires confirmation
    requires_user_confirm: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)
    digest: str = ""                  # digest of the addressed element subtree


AUTO_CONFIDENCE_MIN = 0.8


class SourceFlags(BaseModel):
    encrypted_or_password: bool = False
    corrupt_or_unreadable: bool = False
    external_link_or_ole: bool = False
    macro_or_script: bool = False
    unsupported_format: bool = False


class BrandStructureManifest(BaseModel):
    """Census of the source file — produced before any user decision."""

    id: str = Field(default_factory=lambda: _new_id("bmanifest"))
    source_name: str = ""
    source_sha256: str = ""
    source_format: str = "hwpx"       # hwpx | hwp (hwp after worker conversion)
    source_version: str = ""
    section_count: int = 0
    page_count: Optional[int] = None  # unknown until a real render exists
    control_count: int = 0
    header_variants: list[str] = Field(default_factory=list)  # e.g. ["BOTH","ODD"]
    footer_variants: list[str] = Field(default_factory=list)
    master_page_count: int = 0
    existing_watermark_count: int = 0
    candidates: list[ControlCandidate] = Field(default_factory=list)
    flags: SourceFlags = Field(default_factory=SourceFlags)
    scanner_version: str = "1"
    created_at: float = Field(default_factory=time.time)

    @property
    def digest(self) -> str:
        return _digest(self.model_dump(exclude={"id", "created_at"}))

    def title_candidates(self) -> list[ControlCandidate]:
        return [c for c in self.candidates if c.kind in TITLE_KINDS]

    def page_number_candidates(self) -> list[ControlCandidate]:
        return [c for c in self.candidates if c.kind in PAGE_NUMBER_KINDS]

    def needs_confirmation(self) -> list[ControlCandidate]:
        return [
            c for c in self.candidates
            if c.requires_user_confirm or c.confidence < AUTO_CONFIDENCE_MIN
        ]


# --- request / plan -------------------------------------------------------------

class TitlePolicy(str, Enum):
    AUTO_CONFIDENT = "AUTO_CONFIDENT"
    USER_CONFIRMED = "USER_CONFIRMED"


class WatermarkSpec(BaseModel):
    enabled: bool = True
    opacity: float = 0.30              # alpha≈76 — measured: 0.10 renders invisible on scan-real logos
    scale: float = 0.35                # fraction of page width, 0.30–0.40
    rotation: int = 0
    pages: str = "ALL"
    replace_existing: bool = False     # only with explicit user direction


class BrandRewriteRequest(BaseModel):
    tenant_id: str
    source_id: str
    source_sha256: str = ""
    academy_name: str
    brand_template_id: str = "default"
    brand_template_version: str = "1"
    logo_asset_id: Optional[str] = None
    logo_sha256: str = ""
    title_policy: TitlePolicy = TitlePolicy.USER_CONFIRMED
    watermark: WatermarkSpec = Field(default_factory=WatermarkSpec)
    remove_page_numbers: bool = True
    confirmed_candidate_ids: list[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None
    requested_by: str = ""
    base_revision: Optional[str] = None


class RebrandOpKind(str, Enum):
    REPLACE_TEXT_RUNS = "REPLACE_TEXT_RUNS"
    REPLACE_SELECTED_SHAPE = "REPLACE_SELECTED_SHAPE"
    REPLACE_CELL_BACKGROUND = "REPLACE_CELL_BACKGROUND"
    ADD_WATERMARK_SHAPE = "ADD_WATERMARK_SHAPE"
    REMOVE_PAGE_NUM_CONTROL = "REMOVE_PAGE_NUM_CONTROL"
    REMOVE_PAGE_NUM_FIELD = "REMOVE_PAGE_NUM_FIELD"
    CLEAR_PRINT_PAGE_TOKEN = "CLEAR_PRINT_PAGE_TOKEN"


class RebrandOperation(BaseModel):
    """One allowlisted mutation. The mutator may touch ONLY `paths`."""

    op: RebrandOpKind
    candidate_id: str = ""
    section: str
    paths: list[str] = Field(default_factory=list)   # exact element paths
    expected_digests: dict[str, str] = Field(default_factory=dict)  # path -> digest
    payload: dict[str, Any] = Field(default_factory=dict)           # e.g. new text
    render_mask: str = ""            # header | watermark | footer


class BrandRewritePlan(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("bplan"))
    source_sha256: str = ""
    manifest_digest: str = ""
    academy_name: str = ""
    operations: list[RebrandOperation] = Field(default_factory=list)
    expected_invariants: dict[str, Any] = Field(default_factory=dict)
    planner_version: str = "1"
    created_at: float = Field(default_factory=time.time)

    @property
    def digest(self) -> str:
        return _digest(self.model_dump(exclude={"id", "created_at"}))


class PlanError(ValueError):
    """Fail-closed: ambiguous candidates, unconfirmed required choices, or
    manifest/plan mismatch. The source is never mutated."""

    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


# --- run result -----------------------------------------------------------------

class InvariantReport(BaseModel):
    passed: bool = False
    violations: list[str] = Field(default_factory=list)
    controls_before: int = 0
    controls_after: int = 0
    removed_paths: list[str] = Field(default_factory=list)
    replaced_paths: list[str] = Field(default_factory=list)
    added_paths: list[str] = Field(default_factory=list)
    unchanged_outside_plan: int = 0


class RebrandRunResult(BaseModel):
    output_sha256: str = ""
    output_format: str = "hwpx"
    invariant: InvariantReport = Field(default_factory=InvariantReport)
    proof: dict[str, Any] = Field(default_factory=dict)
    artifact_id: Optional[str] = None
    worker_unavailable: bool = False
    hwp_process_leak: int = 0
