"""JEV adapter boundary — feature-flagged, sanitized, gating-only."""
from __future__ import annotations

import base64

import pytest

from providers.jev.adapter import (
    JevAdapter, JevGateRequest, JevReviewRequest, JevRouteRequest,
)


def test_disabled_by_default_returns_needs_review(monkeypatch):
    monkeypatch.delenv("EXAMDNA_ENABLE_JEV", raising=False)
    jev = JevAdapter(base_url="http://jev.internal")
    v = jev.route(JevRouteRequest(item_kind="page", item_id="p1"))
    assert v.verdict == "NEEDS_REVIEW"
    assert v.rationale == "jev_disabled"


def test_no_generate_entrypoint():
    # Reconstruction content generation through JEV is structurally
    # impossible — there is no generate verb on the adapter.
    assert not hasattr(JevAdapter, "generate")
    assert not hasattr(JevAdapter, "reconstruct")


def test_binary_payload_refused(monkeypatch):
    """Even if a caller stuffs base64 into a metadata field, the payload
    is scanned and refused before any network call."""
    monkeypatch.setenv("EXAMDNA_ENABLE_JEV", "1")
    monkeypatch.setenv("JEV_BASE_URL", "http://jev.internal")

    class Spy:
        def post(self, *a, **kw):  # pragma: no cover - must not run
            raise AssertionError("network call reached")

    jev = JevAdapter(client=Spy())
    blob = base64.b64encode(b"\x89PNG" * 200).decode()
    req = JevReviewRequest(
        subject="trace_region", candidates=[{"crop": blob}]
    )
    with pytest.raises(ValueError, match="refused"):
        jev.review(req)


def test_data_uri_refused(monkeypatch):
    monkeypatch.setenv("EXAMDNA_ENABLE_JEV", "1")
    monkeypatch.setenv("JEV_BASE_URL", "http://jev.internal")
    jev = JevAdapter(client=object())
    req = JevGateRequest(
        operation="bulk_delete", target_id="q1", reason="test",
        risk_signals={"evidence": "data:image/png;base64,AAA"},
    )
    with pytest.raises(ValueError):
        jev.gate(req)


def test_clean_structured_payload_passes(monkeypatch):
    monkeypatch.setenv("EXAMDNA_ENABLE_JEV", "1")
    monkeypatch.setenv("JEV_BASE_URL", "http://jev.internal")

    class FakeClient:
        def post(self, url, json=None, timeout=None):
            class R:
                def json(self):
                    return {"verdict": "ALLOW", "route": "local-llm",
                            "rationale": "structured only"}
            return R()

    jev = JevAdapter(client=FakeClient())
    v = jev.route(JevRouteRequest(
        item_kind="question", item_id="q_1",
        signals={"needs_review": True, "field": "body"},
        candidates=["local-llm", "openai"],
    ))
    assert v.verdict == "ALLOW" and v.route == "local-llm"
