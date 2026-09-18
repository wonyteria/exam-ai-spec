"""Per-call AI telemetry + budget enforcement (WP04 / REQ-21, A11/A12).

Every operational provider call is logged with model, prompt hash, input
hash, schema version, actual token usage, latency and outcome. A cache
hit is recorded as `cache` — it is never counted as an independent
verification round (02: replayed output is not a second opinion).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = "wp04.v1"


class BudgetExceeded(RuntimeError):
    """Raised before a provider call when the configured budget is spent."""


@dataclass
class CallRecord:
    ts: float
    provider: str
    model: str
    method: str
    prompt_sha256: str
    input_sha256: str
    schema_version: str = SCHEMA_VERSION
    run_id: Optional[str] = None
    outcome: str = "ok"  # ok | cache | retry | error | refused | budget_exceeded
    attempts: int = 1
    latency_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error_class: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


def hash_payload(parts: list[Any]) -> str:
    """Deterministic hash of prompt+input parts for the call log. Image
    bytes hash to their digest — never the bytes themselves."""
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, str):
            h.update(p.encode())
        elif isinstance(p, (bytes, bytearray)):
            h.update(bytes(p))
        else:
            data = getattr(getattr(p, "inline_data", None), "data", None)
            if isinstance(data, bytes):
                h.update(data)
            else:
                h.update(repr(p).encode())
    return h.hexdigest()


class Telemetry:
    """Append-only call log with a spending cap.

    max_calls=0 disables the cap; log_path=None disables persistence
    (records still kept in memory for tests/introspection)."""

    def __init__(
        self,
        log_path: Optional[Path] = None,
        max_calls: Optional[int] = None,
    ):
        self.log_path = Path(log_path) if log_path else None
        self.max_calls = (
            int(os.environ["EXAMDNA_MAX_CALLS"])
            if max_calls is None and os.environ.get("EXAMDNA_MAX_CALLS")
            else (max_calls or 0)
        )
        self._lock = threading.Lock()
        self.records: list[CallRecord] = []
        self._calls_made = 0

    def check_budget(self) -> None:
        if self.max_calls and self._calls_made >= self.max_calls:
            self.record(
                CallRecord(
                    ts=time.time(),
                    provider="budget",
                    model="-",
                    method="budget_check",
                    prompt_sha256="",
                    input_sha256="",
                    outcome="budget_exceeded",
                )
            )
            raise BudgetExceeded(
                f"AI call budget exhausted ({self._calls_made}/{self.max_calls})"
            )

    def record(self, rec: CallRecord) -> None:
        with self._lock:
            if rec.outcome not in ("cache", "budget_exceeded"):
                self._calls_made += rec.attempts
            self.records.append(rec)
            if self.log_path is not None:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")


_default: Optional[Telemetry] = None


def get_telemetry() -> Telemetry:
    """Process-wide telemetry; log under the data dir when configured."""
    global _default
    if _default is None:
        data_dir = os.environ.get("EXAMDNA_DATA")
        log_path = (
            Path(data_dir) / "telemetry" / "ai_calls.jsonl" if data_dir else None
        )
        _default = Telemetry(log_path=log_path)
    return _default


def reset_telemetry() -> None:
    global _default
    _default = None
