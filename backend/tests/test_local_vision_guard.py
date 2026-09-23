"""Local-vision endpoint guard + independent local solver slots.

Raw exam images may only go to loopback/LAN inference endpoints —
never off-site. The provider refuses construction on a non-local URL.
"""
from __future__ import annotations

import pytest

import jobs.runner as runner
from providers.local.trace import (
    LocalVisionTraceProvider, _assert_local_base_url,
)


class TestBaseUrlGuard:
    @pytest.mark.parametrize("url", [
        "http://localhost:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://[::1]:11434/v1",
        "http://192.168.0.10:11434/v1",   # RFC-1918 LAN (Mac Studio)
        "http://10.0.0.5:11434/v1",
        "http://169.254.1.2:11434/v1",    # link-local
        "http://mac-studio.local:11434/v1",
    ])
    def test_local_endpoints_allowed(self, url):
        _assert_local_base_url(url)

    @pytest.mark.parametrize("url", [
        "http://8.8.8.8:11434/v1",            # public IP
        "https://api.openai.com/v1",          # public hostname
        "http://example.com/v1",
        "not-a-url",                          # malformed
        "",                                   # empty
    ])
    def test_nonlocal_endpoints_refused(self, url):
        with pytest.raises(ValueError):
            _assert_local_base_url(url)

    def test_provider_construction_refuses_remote(self):
        with pytest.raises(ValueError):
            LocalVisionTraceProvider(base_url="https://api.openai.com/v1")


class TestLocalSlots:
    def test_alt_model_registers_independent_slot(self, monkeypatch):
        monkeypatch.setenv("EXAMDNA_ENABLE_LOCAL_LLM", "1")
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setenv("LOCAL_LLM_MODEL", "local-large")
        monkeypatch.setenv("LOCAL_LLM_MODEL_ALT", "local-long")

        from providers.local import LocalLLMProvider

        def fake(model=None, name=None, **_):
            p = LocalLLMProvider(client=object(), model=model)
            if name:
                p.name = name
            return p

        monkeypatch.setattr(runner, "_local_provider", fake)
        providers = runner.default_providers()

        assert providers.solver[0].name == "local-llm"
        assert providers.solver[0].model == "local-large"
        assert providers.solver[1].name == "local-llm/local-long"
        # Two distinct models = two independent evidence sources.
        assert providers.solver[0].name != providers.solver[1].name

    def test_same_model_alt_is_not_independent(self, monkeypatch):
        """Pointing the ALT slot at the same model must not double-count:
        a shared-cache replay is one source, not two."""
        monkeypatch.setenv("EXAMDNA_ENABLE_LOCAL_LLM", "1")
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setenv("LOCAL_LLM_MODEL", "local-large")
        monkeypatch.setenv("LOCAL_LLM_MODEL_ALT", "local-large")

        from providers.local import LocalLLMProvider
        monkeypatch.setattr(
            runner, "_local_provider",
            lambda model=None, name=None, **_: LocalLLMProvider(
                client=object(), model=model, name=name),
        )
        providers = runner.default_providers()
        local_names = [p.name for p in providers.solver
                       if p.name.startswith("local-llm")]
        assert local_names == ["local-llm"]

    def test_local_llm_off_by_default(self, monkeypatch):
        monkeypatch.delenv("EXAMDNA_ENABLE_LOCAL_LLM", raising=False)
        providers = runner.default_providers()
        assert not any(p.name.startswith("local-llm")
                       for p in providers.solver)
