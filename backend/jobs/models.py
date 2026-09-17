from __future__ import annotations

import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from document.models import new_id


class JobState(str, Enum):
    UPLOADED = "UPLOADED"
    PREPROCESSING = "PREPROCESSING"
    SEPARATING_TRACES = "SEPARATING_TRACES"
    RESTORING_PRINT = "RESTORING_PRINT"
    RECOGNIZING = "RECOGNIZING"
    VERIFYING_SOURCE = "VERIFYING_SOURCE"
    VERIFYING_LOGIC = "VERIFYING_LOGIC"
    SOLVING = "SOLVING"
    RENDERING = "RENDERING"
    VERIFYING_EXPORT = "VERIFYING_EXPORT"
    COMPLETED = "COMPLETED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class JobEvent(BaseModel):
    ts: float = Field(default_factory=time.time)
    stage: str
    message: str
    level: str = "info"


class Job(BaseModel):
    id: str = Field(default_factory=lambda: new_id("job"))
    document_id: str
    kind: str = "restore_pipeline"
    state: JobState = JobState.UPLOADED
    events: list[JobEvent] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    finished_at: Optional[float] = None
