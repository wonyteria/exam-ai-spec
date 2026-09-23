"""JEV auxiliary layer (Phase 4) — feature-flagged, schema-typed.

JEV may ONLY:
  - route work items (which stage/provider handles a case)
  - review structured candidates (a verdict on derived data)
  - gate unsafe operations (approve/deny a flagged mutation)

Hard boundaries (enforced here, not by convention):
  - NEVER receives raw exam images — payloads are typed models with no
    image/binary fields, and `_assert_sanitized` scans every payload for
    base64 blobs / data-URIs before sending.
  - NEVER generates reconstruction content — there is no "generate"
    entry point by design.
  - Disabled by default: EXAMDNA_ENABLE_JEV=1 + JEV_BASE_URL required.

Codex account/CLI usage stays a *development* worker (eval, fixture
generation) — its tokens never enter backend, logs, frontend, .env, or
any request path. This adapter is the ONLY sanctioned runtime surface.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# --- typed payloads -------------------------------------------------------------
# Fields are deliberately structural: ids, counts, text snippets, verdicts.
# There is no image/binary field anywhere in this schema.


class JevRouteRequest(BaseModel):
    """Which lane should handle a unit of work."""

    kind: Literal["route"] = "route"
    item_kind: str                    # e.g. "page", "question", "issue"
    item_id: str
    signals: dict[str, Any] = Field(default_factory=dict)
    candidates: list[str] = Field(default_factory=list)


class JevReviewRequest(BaseModel):
    """Verdict on already-derived structured candidates."""

    kind: Literal["review"] = "review"
    subject: str                      # e.g. "trace_region", "choice_parse"
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class JevGateRequest(BaseModel):
    """Approve/deny a flagged (potentially unsafe) operation."""

    kind: Literal["gate"] = "gate"
    operation: str
    target_id: str
    reason: str
    risk_signals: dict[str, Any] = Field(default_factory=dict)


class JevVerdict(BaseModel):
    verdict: Literal["ALLOW", "DENY", "NEEDS_REVIEW"] = "NEEDS_REVIEW"
    route: Optional[str] = None
    rationale: str = ""


# --- transport boundary -----------------------------------------------------------

_B64_RE = re.compile(r"[A-Za-z0-9+/]{256,}={0,2}")
_DATA_URI_RE = re.compile(r"data:image/|base64,", re.I)


def _assert_sanitized(payload: BaseModel) -> None:
    """Raw exam imagery never leaves through JEV. Scan the serialized
    payload for binary-looking content and refuse loudly — a caller bug
    must not become an exfiltration path."""
    blob = json.dumps(payload.model_dump(), ensure_ascii=False)
    if _DATA_URI_RE.search(blob) or _B64_RE.search(blob):
        raise ValueError(
            "JEV payload contains image/binary-looking data — refused"
        )


class JevAdapter:
    """Feature-flagged JEV client. Disabled without the env flag."""

    def __init__(self, base_url: Optional[str] = None, client: Any = None):
        self.enabled = os.environ.get("EXAMDNA_ENABLE_JEV") == "1"
        self.base_url = base_url or os.environ.get("JEV_BASE_URL")
        self._client = client

    def _post(self, req: BaseModel) -> JevVerdict:
        if not self.enabled or not self.base_url:
            return JevVerdict(
                verdict="NEEDS_REVIEW", rationale="jev_disabled"
            )
        _assert_sanitized(req)
        if self._client is None:
            return JevVerdict(
                verdict="NEEDS_REVIEW", rationale="jev_unconfigured"
            )
        resp = self._client.post(
            f"{self.base_url.rstrip('/')}/v1/{req.kind}",
            json=req.model_dump(),
            timeout=float(os.environ.get("JEV_TIMEOUT", "30")),
        )
        return JevVerdict.model_validate(resp.json())

    # The only three verbs — routing, review, unsafe-op gating.
    def route(self, req: JevRouteRequest) -> JevVerdict:
        return self._post(req)

    def review(self, req: JevReviewRequest) -> JevVerdict:
        return self._post(req)

    def gate(self, req: JevGateRequest) -> JevVerdict:
        return self._post(req)
