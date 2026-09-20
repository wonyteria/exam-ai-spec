"""WP10 — tenant limits, log scrubbing, worker metrics."""
from __future__ import annotations

import pytest

from core.logscrub import scrub_payload, scrub_text
from jobs.metrics import JobMetrics
from tenancy.limits import QuotaExceeded, TenantLimiter, TenantLimits


def test_rate_limit_blocks_burst():
    lim = TenantLimiter(TenantLimits(requests_per_minute=3))
    for _ in range(3):
        lim.check_rate("t1")
    with pytest.raises(QuotaExceeded) as e:
        lim.check_rate("t1")
    assert e.value.kind == "rate"
    # a different tenant is unaffected
    lim.check_rate("t2")


def test_concurrency_gate():
    lim = TenantLimiter(TenantLimits(max_concurrent_jobs=1))
    lim.acquire_job("t1")
    with pytest.raises(QuotaExceeded) as e:
        lim.acquire_job("t1")
    assert e.value.kind == "concurrency"
    lim.release_job("t1")
    lim.acquire_job("t1")  # released slot is reusable


def test_byte_budget():
    lim = TenantLimiter(TenantLimits(monthly_byte_budget=100))
    lim.charge_bytes("t1", 60)
    with pytest.raises(QuotaExceeded) as e:
        lim.charge_bytes("t1", 50)
    assert e.value.kind == "budget"


def test_scrub_secrets_and_paths():
    assert "<REDACTED>" in scrub_text("api_key=sk-abcdef123")
    assert "<PATH>" in scrub_text(r"saved to C:\Users\student\exam.pdf")
    assert "<EMAIL>" in scrub_text("contact teacher@school.kr")
    assert "<PHONE>" in scrub_text("call 010-1234-5678")
    payload = {"msg": "token=abc123", "items": ["x@y.com"]}
    out = scrub_payload(payload)
    assert "abc123" not in out["msg"]
    assert "x@y.com" not in out["items"][0]


def test_metrics_record_and_summary(tmp_path):
    m = JobMetrics(tmp_path)
    m.stage_start("recognition")
    m.stage_end("recognition", ok=True)
    m.stage_end("rendering", ok=False)  # no start → duration None
    s = m.summary()
    assert s["stages"] == 2
    assert s["failed"] == 1
