from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from document.scene import FigureScene, Graph, Table


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    AUTO_VERIFIED = "AUTO_VERIFIED"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"
    CONFLICT = "CONFLICT"
    UNREADABLE = "UNREADABLE"


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    SUBJECTIVE = "subjective"
    DESCRIPTIVE = "descriptive"


class ATUKind(str, Enum):
    QUESTION_NUMBER = "question_number"
    TEXT_TOKEN = "text_token"
    NUMBER = "number"
    VARIABLE = "variable"
    MATH_SYMBOL = "math_symbol"
    UNIT = "unit"
    POINTS = "points"
    CHOICE = "choice"
    FIGURE_LABEL = "figure_label"
    ANGLE = "angle"
    LENGTH = "length"


class BBox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class SourceRef(BaseModel):
    page: int
    bbox: Optional[BBox] = None


class Candidate(BaseModel):
    """RecognitionCandidate (ReadDNA): a provider's claim, never a final
    value. First-class provenance fields — bbox_original (source-pixel
    space), bbox_asset (space of the derived asset actually fed to the
    engine), model_version, raw output hash, and timestamp — are the
    contract; `meta` carries provider extras."""
    provider: str
    value: Any
    confidence: float = 0.0
    meta: dict[str, Any] = Field(default_factory=dict)
    model_version: Optional[str] = None
    bbox_original: Optional[BBox] = None
    bbox_asset: Optional[BBox] = None
    raw_output_sha256: Optional[str] = None
    timestamp: Optional[float] = None


class ATU(BaseModel):
    """Atomic Truth Unit: the smallest independently verifiable value."""

    id: str = Field(default_factory=lambda: new_id("atu"))
    kind: ATUKind
    field: Optional[str] = None
    candidates: list[Candidate] = Field(default_factory=list)
    value: Any = None
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    source: Optional[SourceRef] = None
    note: Optional[str] = None


class TextSpan(BaseModel):
    text: str
    atu_ids: list[str] = Field(default_factory=list)


class Choice(BaseModel):
    label: str
    body: list[TextSpan] = Field(default_factory=list)
    atu_ids: list[str] = Field(default_factory=list)


class Equation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("eq"))
    latex: Optional[str] = None
    hwp_formula: Optional[str] = None
    atu_ids: list[str] = Field(default_factory=list)
    source: Optional[SourceRef] = None


class FigureRelation(BaseModel):
    kind: str
    elements: list[str] = Field(default_factory=list)


class Figure(BaseModel):
    id: str = Field(default_factory=lambda: new_id("fig"))
    topology: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    relations: list[FigureRelation] = Field(default_factory=list)
    atu_ids: list[str] = Field(default_factory=list)
    source: Optional[SourceRef] = None
    # Typed payloads (WP05): a scene graph is data-only — validated, never
    # executed. Legacy topology dicts stay for backward compatibility.
    scene: Optional["FigureScene"] = None
    table: Optional["Table"] = None
    graph: Optional["Graph"] = None


class Answer(BaseModel):
    value: Any = None
    atu_ids: list[str] = Field(default_factory=list)


class Solution(BaseModel):
    steps: list[TextSpan] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)


class Curriculum(BaseModel):
    grade: str = ""
    unit: str = ""
    concepts: list[str] = Field(default_factory=list)


class LogicFlag(BaseModel):
    kind: Literal[
        "missing_condition",
        "logic_conflict",
        "unsolvable_question",
        "ambiguous_answer",
        "invalid_figure",
        "math_check_failed",
    ]
    detail: str = ""


class QuestionVerification(BaseModel):
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    logic_flags: list[LogicFlag] = Field(default_factory=list)


class Question(BaseModel):
    id: str = Field(default_factory=lambda: new_id("q"))
    number: int
    label: Optional[str] = None
    parent_id: Optional[str] = None  # shared-stem group (e.g. 논술형 2 -> 2-1)
    type: QuestionType = QuestionType.MULTIPLE_CHOICE
    points: Optional[int] = None
    body: list[TextSpan] = Field(default_factory=list)
    choices: list[Choice] = Field(default_factory=list)
    equations: list[Equation] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    answer: Optional[Answer] = None
    solution: Optional[Solution] = None
    curriculum: Curriculum = Field(default_factory=Curriculum)
    source: Optional[SourceRef] = None
    # RESTORE-01/03: provenance — where in the immutable source this
    # question was detected, plus the transform chain back to source px.
    source_anchor: Optional[SourceAnchor] = None
    atus: list[ATU] = Field(default_factory=list)
    verification: QuestionVerification = Field(default_factory=QuestionVerification)


class PageImage(BaseModel):
    uri: str
    variants: dict[str, str] = Field(default_factory=dict)
    # sha256 of each derived variant — derived bytes are evidence, and the
    # hash binds crops/recognition inputs to an exact variant (RESTORE-01).
    variant_sha256: dict[str, str] = Field(default_factory=dict)


class PdfPageInventory(BaseModel):
    """Per-page census of a PDF's native content — recorded before any
    image-recognition runs. An image-only page is the scan path; a page
    with a real text layer also keeps native text/vector extraction as
    separate evidence (RESTORE-01)."""

    page_index: int
    width_pt: float = 0.0
    height_pt: float = 0.0
    rotation: int = 0
    mediabox: list[float] = Field(default_factory=list)
    cropbox: list[float] = Field(default_factory=list)
    text_chars: int = 0
    text_objects: int = 0
    image_objects: int = 0
    path_objects: int = 0
    form_objects: int = 0
    shading_objects: int = 0
    other_objects: int = 0
    image_bounds_pt: list[list[float]] = Field(default_factory=list)
    image_only: bool = False          # no text layer — scan path
    text_layer_sparse: bool = False   # some text but too thin to trust
    # RESTORE-14: three-way source classification and bounded native
    # evidence — DIGITAL pages keep their text layer as an independent
    # evidence stream, SCANNED pages go through recognition only.
    pdf_class: str = "UNKNOWN"        # DIGITAL | SCANNED | HYBRID | UNKNOWN
    native_fragments: list[dict[str, Any]] = Field(default_factory=list)
    native_fragments_truncated: bool = False
    fonts: list[str] = Field(default_factory=list)


class TransformStep(BaseModel):
    """One recorded, invertible transform applied to source pixels."""

    kind: str                        # pdf_raster | exif_orientation | ...
    params: dict[str, Any] = Field(default_factory=dict)


class SourceAnchor(BaseModel):
    """Binds a derived region/crop back to source coordinates — every
    recognized candidate must be able to state where it came from."""

    source_sha256: str = ""
    page_index: int = -1
    bbox_px: Optional[BBox] = None        # working-pixel bbox as detected
    source_bbox: Optional[BBox] = None    # mapped back through the chain
    transform_chain: list[TransformStep] = Field(default_factory=list)
    crop_sha256: Optional[str] = None


class Page(BaseModel):
    index: int
    original: PageImage
    width: Optional[float] = None
    height: Optional[float] = None
    clean_uri: Optional[str] = None
    trace_mask_uri: Optional[str] = None
    # Source linkage (WP03): upload order and exam order are separate.
    source_asset_id: Optional[str] = None
    source_page_id: Optional[str] = None
    pdf_page_index: Optional[int] = None
    sha256: Optional[str] = None
    original_name: Optional[str] = None
    # Coordinate transform applied to derive working pixels from the
    # original (EXIF orientation, crop). Anchors stay in original pixels;
    # clean/crop coordinates must be invertible (02 SourceAnchor).
    transform: Optional[dict[str, Any]] = None
    # Regions where trace removal could not be separated from print with
    # confidence — kept for original comparison / human review (S01).
    uncertain_regions: list[dict[str, Any]] = Field(default_factory=list)
    # Semantic role from the source manifest (AT-061): QUESTION |
    # ANSWER_KEY | COVER | BLANK | UNKNOWN. An answer/score page is never
    # silently treated as a question page; UNKNOWN forces confirmation.
    page_role: str = "UNKNOWN"
    role_source: str = "AUTO"  # AUTO | USER
    # RESTORE-01 source evidence: native PDF census, ordered invertible
    # transforms, and an explicit failure marker — a page that could not
    # be rasterized is never silently skipped.
    inventory: Optional[PdfPageInventory] = None
    transform_chain: list[TransformStep] = Field(default_factory=list)
    processing_error: Optional[str] = None
    # RegionDNA (RESTORE-14): typed regions with evidence — header/footer
    # bands, question bodies, tables, answer space. Typed for routing;
    # never silently dropped.
    regions: list[dict[str, Any]] = Field(default_factory=list)


class ExamMetadata(BaseModel):
    school: str = ""
    year: Optional[int] = None
    grade: str = ""
    semester: Optional[int] = None
    exam_type: str = ""
    subject: str = "mathematics"


class DocumentVerification(BaseModel):
    status: Literal["IN_PROGRESS", "NEEDS_REVIEW", "VERIFIED_FINAL", "FAILED"] = (
        "IN_PROGRESS"
    )
    gate: Optional[dict[str, Any]] = None


class Document(BaseModel):
    """Source of Truth. HWP/PDF are render targets, never the truth."""

    id: str = Field(default_factory=lambda: new_id("doc"))
    tenant_id: Optional[str] = None
    metadata: ExamMetadata = Field(default_factory=ExamMetadata)
    pages: list[Page] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    brand_id: Optional[str] = None
    template_id: Optional[str] = None
    verification: DocumentVerification = Field(default_factory=DocumentVerification)
    version: int = 1

    def all_atus(self) -> list[ATU]:
        return [atu for q in self.questions for atu in q.atus]
