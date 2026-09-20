"""WP10 — worker metrics.

Stage-level duration and outcome are appended as JSONL records next to
the job artifacts so throughput/latency regressions are measurable
without external infrastructure.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


class JobMetrics:
    def __init__(self, workdir: Path):
        self.path = workdir / "worker_metrics.jsonl"
        self._stage_start: dict[str, float] = {}

    def stage_start(self, stage: str) -> None:
        self._stage_start[stage] = time.time()

    def stage_end(self, stage: str, ok: bool = True,
                  extra: Optional[dict[str, Any]] = None) -> None:
        started = self._stage_start.pop(stage, None)
        rec = {
            "stage": stage,
            "ok": ok,
            "duration_s": (
                round(time.time() - started, 3) if started else None
            ),
            "ts": time.time(),
        }
        if extra:
            rec.update(extra)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def summary(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"stages": 0, "total_s": 0.0, "failed": 0}
        stages = 0
        total = 0.0
        failed = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            stages += 1
            total += rec.get("duration_s") or 0
            if not rec.get("ok", True):
                failed += 1
        return {"stages": stages, "total_s": round(total, 3),
                "failed": failed}
