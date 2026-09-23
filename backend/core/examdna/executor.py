"""Fail-closed stage executor (Phase 1).

Runs the typed STAGE contracts: preflight-gated, hash-bound, and every
transition recorded. Rules:

- required capability missing -> BLOCKED, the function never runs
- exception -> FAILED and the pipeline stops (evidence kept)
- cancel requested -> CANCELLED for this and every remaining stage
- a BLOCKED stage marks ctx.stage_blocked — the job can only finish as
  NEEDS_REVIEW, never COMPLETED

Records are appended to <workdir>/stage_records.jsonl.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

from core.examdna.context import PipelineContext
from core.examdna.pipeline import STAGES
from core.examdna.stage_contract import StageRecord, StageStatus


def run_stages(
    ctx: PipelineContext,
    on_stage_start: Optional[Callable] = None,
    on_stage_end: Optional[Callable] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[StageRecord]:
    records_path = Path(ctx.workdir) / "stage_records.jsonl"
    records: list[StageRecord] = []

    def _flush(rec: StageRecord) -> None:
        with records_path.open("a") as fh:
            fh.write(json.dumps(rec.as_dict(), ensure_ascii=False) + "\n")

    cancelled = False
    for contract in STAGES:
        rec = StageRecord(name=contract.name)
        records.append(rec)

        if cancelled or (should_cancel is not None and should_cancel()):
            rec.transition(StageStatus.CANCELLED)
            _flush(rec)
            cancelled = True
            continue

        if on_stage_start is not None:
            on_stage_start(contract)

        missing = [
            req
            for req in contract.requires
            if ctx.capabilities is not None
            and not ctx.capabilities.has(req)
        ]
        if missing:
            rec.transition(StageStatus.BLOCKED, missing_capabilities=missing)
            ctx.stage_blocked = True
            ctx.emit(
                contract.name,
                f"BLOCKED — missing capability: {', '.join(missing)}",
                "warn",
            )
            _flush(rec)
            if on_stage_end is not None:
                on_stage_end(contract, rec)
            continue

        ctx.emit(contract.name, f"단계 시작: {contract.name}")
        rec.transition(StageStatus.RUNNING)
        try:
            contract.fn(ctx)
        except Exception as exc:
            rec.transition(
                StageStatus.FAILED, error_type=type(exc).__name__
            )
            rec.error = str(exc)[:500]
            _flush(rec)
            if on_stage_end is not None:
                on_stage_end(contract, rec)
            raise

        metrics = ctx.stage_metrics.get(contract.name) or {}
        rec.transition(StageStatus.SUCCEEDED, **metrics)
        _flush(rec)
        if on_stage_end is not None:
            on_stage_end(contract, rec)

    return records
