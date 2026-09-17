from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


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
    provider: str
    value: Any
    confidence: float = 0.0
    meta: dict[str, Any] = Field(default_factory=dict)


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
    ]
    detail: str = ""


class QuestionVerification(BaseModel):
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    logic_flags: list[LogicFlag] = Field(default_factory=list)


class Question(BaseModel):
    id: str = Field(default_factory=lambda: new_id("q"))
    number: int
    label: Optional[str] = None
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
    atus: list[ATU] = Field(default_factory=list)
    verification: QuestionVerification = Field(default_factory=QuestionVerification)


class PageImage(BaseModel):
    uri: str
    variants: dict[str, str] = Field(default_factory=dict)


class Page(BaseModel):
    index: int
    original: PageImage
    width: Optional[float] = None
    height: Optional[float] = None
    clean_uri: Optional[str] = None
    trace_mask_uri: Optional[str] = None


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
    metadata: ExamMetadata = Field(default_factory=ExamMetadata)
    pages: list[Page] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    brand_id: Optional[str] = None
    template_id: Optional[str] = None
    verification: DocumentVerification = Field(default_factory=DocumentVerification)
    version: int = 1

    def all_atus(self) -> list[ATU]:
        return [atu for q in self.questions for atu in q.atus]
