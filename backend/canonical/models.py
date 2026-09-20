from __future__ import annotations

import hashlib
import json
import time
import uuid
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def canonical_json(value: Any) -> str:
    """Deterministic serialization for hashing: sorted keys, no spaces."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


# --- lifecycle --------------------------------------------------------------


class LifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"
    PURGED = "PURGED"


class DocumentRecord(BaseModel):
    id: str
    tenant_id: str
    head_revision_id: Optional[str] = None
    created_by: str = ""
    lifecycle_state: LifecycleState = LifecycleState.ACTIVE
    lifecycle_version: int = 1
    archived_at: Optional[float] = None
    deleted_at: Optional[float] = None
    retention_deadline: Optional[float] = None
    created_at: float = Field(default_factory=time.time)


# --- source assets / pages / manifest (WP03) -------------------------------------


class SourceAsset(BaseModel):
    """Immutable uploaded blob. Bytes never change; dedup is per-tenant by
    sha256 so a retried upload reuses the same asset."""
    id: str = Field(default_factory=lambda: new_id("asset"))
    tenant_id: str
    sha256: str
    mime: str
    byte_size: int
    original_name: str
    blob_key: str
    created_at: float = Field(default_factory=time.time)


class PageRole(str, Enum):
    """Semantic role of a source page. An answer/score sheet is NEVER a
    question page — it must surface in the manifest and be user-confirmable
    so it is never silently dropped or mis-set."""
    QUESTION = "QUESTION"
    ANSWER_KEY = "ANSWER_KEY"
    COVER = "COVER"
    BLANK = "BLANK"
    UNKNOWN = "UNKNOWN"


class SourcePage(BaseModel):
    """One logical page of the exam. Upload order and exam order are
    separate — ordering lives in the SourceManifest."""
    id: str = Field(default_factory=lambda: new_id("spage"))
    tenant_id: str
    document_id: str
    asset_id: str
    pdf_page_index: Optional[int] = None
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    original_sha256: str
    original_name: str = ""
    upload_index: int = 0
    # Page-role classification (AT-061): AUTO = heuristic suggestion,
    # USER = explicitly confirmed by the user. UNKNOWN must not be
    # silently treated as a question page downstream.
    page_role: str = PageRole.UNKNOWN.value
    role_source: str = "AUTO"  # AUTO | USER


class SourceManifest(BaseModel):
    """Ordered page list for a document. A reorder or confirmation creates
    a new manifest (digest changes when order changes); revisions bind to
    a manifest_id so rendered content always matches a page set."""
    id: str = Field(default_factory=lambda: new_id("mf"))
    tenant_id: str
    document_id: str
    page_ids_ordered: list[str] = Field(default_factory=list)
    missing_page_expectation: Optional[str] = None
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[float] = None
    digest: str = ""
    created_at: float = Field(default_factory=time.time)

    def compute_digest(self) -> str:
        return sha256_json(
            {
                "document_id": self.document_id,
                "page_ids_ordered": self.page_ids_ordered,
                "missing_page_expectation": self.missing_page_expectation,
            }
        )


# --- revisions ----------------------------------------------------------------


class RevisionMode(str, Enum):
    RESTORE = "RESTORE"  # faithful reproduction of the printed source
    EDIT = "EDIT"        # approved changes on top of a restore baseline
    UNDO = "UNDO"        # new revision restoring an older snapshot


class Revision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rev"))
    document_id: str
    revision_no: int
    parent_revision_id: Optional[str] = None
    mode: RevisionMode = RevisionMode.RESTORE
    restore_baseline_revision_id: Optional[str] = None
    restores_revision_id: Optional[str] = None
    manifest_id: Optional[str] = None
    metadata_snapshot: dict[str, Any] = Field(default_factory=dict)
    template_snapshot: dict[str, Any] = Field(default_factory=dict)
    content_json: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    style_hash: str = ""
    solution_hash: str = ""
    policy_version: str = "1"
    created_by: str = ""
    created_at: float = Field(default_factory=time.time)
    change_summary: list[dict[str, Any]] = Field(default_factory=list)


# --- checks / issues ------------------------------------------------------------


class CheckState(str, Enum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


class CheckRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("chk"))
    tenant_id: str
    revision_id: str
    check_kind: str
    input_digest: str = ""
    validator_version: str = "1"
    policy_version: str = "1"
    state: CheckState = CheckState.NOT_RUN
    result_summary: str = ""
    applicable: bool = True
    stale_reason: Optional[str] = None
    method: str = "AUTO"  # AUTO | HUMAN_ADJUDICATED
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    run_id: Optional[str] = None


class IssueState(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class Issue(BaseModel):
    id: str = Field(default_factory=lambda: new_id("iss"))
    revision_id: str
    question_ids: list[str] = Field(default_factory=list)
    object_ids: list[str] = Field(default_factory=list)
    kind: str = ""
    severity: str = "info"  # info | warning | critical
    blocking: bool = False
    state: IssueState = IssueState.OPEN
    reason: str = ""
    actor: str = ""
    created_at: float = Field(default_factory=time.time)
    resolution_change_set_id: Optional[str] = None


# --- artifacts / proofs -----------------------------------------------------------


class ArtifactState(str, Enum):
    DRAFT = "DRAFT"                    # internal/draft — watermarkable, not final
    FINAL_ELIGIBLE = "FINAL_ELIGIBLE"  # all required proofs PASSED + gate closed
    FINAL = "FINAL"                    # promoted by an authorized export


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: new_id("art"))
    tenant_id: str
    document_id: str
    revision_id: str
    format: str  # hwpx | hwp | pdf
    output_mode: str = "STUDENT_WITH_ENDNOTES"
    content_hash: str = ""
    style_hash: str = ""
    solution_hash: str = ""
    template_version: str = "1"
    renderer_version: str = "1"
    artifact_sha256: str = ""
    blob_key: str = ""
    byte_size: int = 0
    state: ArtifactState = ArtifactState.DRAFT
    created_at: float = Field(default_factory=time.time)


class ArtifactProof(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prf"))
    artifact_id: str
    artifact_sha256: str  # proof binds to exact bytes
    revision_id: str
    policy_digest: str = ""
    checks: dict[str, str] = Field(default_factory=dict)  # check_kind -> state
    worker_identity: str = ""
    created_at: float = Field(default_factory=time.time)


# --- policy -----------------------------------------------------------------


class VerificationPolicySnapshot(BaseModel):
    policy_id: str
    version: str = "1"
    mode: RevisionMode = RevisionMode.RESTORE
    output_mode: str = "STUDENT_WITH_ENDNOTES"
    required_content_checks: list[str] = Field(default_factory=list)
    required_artifact_checks_by_format: dict[str, list[str]] = Field(
        default_factory=dict
    )
    validator_versions: dict[str, str] = Field(default_factory=dict)
    minimum_solver_attempts: int = 2
    created_at: float = Field(default_factory=time.time)

    @property
    def digest(self) -> str:
        return sha256_json(
            self.model_dump(exclude={"created_at"})
        )


# --- change ops (typed union, no arbitrary JSON patch) --------------------------


class ChangeOp(BaseModel):
    """One typed mutation. `expected_old_digest` optionally pins the field
    being replaced; `reason` is recorded for audit."""

    op: Literal[
        "SetField",
        "ResolveATU",
        "SetMetadata",
        "SetAnswer",
        "SetPoints",
        "SetStyle",
        "SetBody",
        "SetChoice",
        "SetEquation",
        "AddQuestion",
        "RemoveQuestion",
        "MoveQuestion",
        "SwapQuestions",
        "ReorderQuestions",
    ]
    target_id: Optional[str] = None  # question/atu/object id where relevant
    field: Optional[str] = None
    value: Any = None
    expected_old_digest: Optional[str] = None
    reason: str = ""
    # Shared-stem groups (WP06): propagate the same field/value to direct
    # children (parent_id == target question id). Explicit opt-in per op.
    propagate: bool = False


# --- durable jobs ---------------------------------------------------------------


class JobV2State(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    WAITING_QUOTA = "WAITING_QUOTA"
    WAITING_WORKER = "WAITING_WORKER"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    COMPLETED_REVIEW_HANDOFF = "COMPLETED_REVIEW_HANDOFF"


TERMINAL_JOB_STATES = {
    JobV2State.SUCCEEDED,
    JobV2State.FAILED,
    JobV2State.CANCELLED,
    JobV2State.COMPLETED_REVIEW_HANDOFF,
}


class JobV2(BaseModel):
    id: str = Field(default_factory=lambda: new_id("job"))
    tenant_id: str
    document_id: str
    input_revision_id: Optional[str] = None
    kind: str = "restore_pipeline"
    state: JobV2State = JobV2State.QUEUED
    current_stage: Optional[str] = None
    priority: int = 0
    created_by: str = ""
    idempotency_key: Optional[str] = None
    attempt_count: int = 0
    not_before: float = 0.0
    lease_owner: Optional[str] = None
    lease_token: Optional[str] = None
    lease_expires_at: Optional[float] = None
    heartbeat_at: Optional[float] = None
    cancel_requested_at: Optional[float] = None
    last_error: Optional[str] = None
    output_revision_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)


class JobEventRecord(BaseModel):
    job_id: str
    seq: int
    ts: float = Field(default_factory=time.time)
    event: str = "stage.progress"
    state: Optional[str] = None
    stage: Optional[str] = None
    revision_id: Optional[str] = None
    completed_units: Optional[int] = None
    total_units: Optional[int] = None
    error: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


class IdempotencyRecord(BaseModel):
    tenant_id: str
    actor: str
    route: str
    key: str
    request_hash: str
    response_json: dict[str, Any] = Field(default_factory=dict)
    resource_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
