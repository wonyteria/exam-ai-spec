"""LocalLLMProvider — chat-completions adapter contract tests."""
from __future__ import annotations

import json

from providers.local import LocalLLMProvider


class _Msg:
    def __init__(self, content: str):
        self.content = content


class _Choice:
    def __init__(self, content: str):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content: str):
        self.choices = [_Choice(content)]


class FakeChat:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return _Resp(r)


class FakeClient:
    def __init__(self, responses):
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeChat(responses)


def _provider(responses, monkeypatch, tmp_path):
    # CACHE_ENABLED is read at import time — patch the module constant, and
    # point the cache at tmp_path so identical prompts across tests can't
    # share cached files.
    import providers.local.provider as local_mod

    monkeypatch.setattr(local_mod, "CACHE_ENABLED", False)
    monkeypatch.setattr(local_mod, "CACHE_DIR", tmp_path / "cache")
    return LocalLLMProvider(
        base_url="http://localhost:11434/v1",
        model="test-model",
        client=FakeClient(responses),
    )


def test_solve_batch_parses_json_array(monkeypatch, tmp_path):
    p = _provider(
        [
            json.dumps(
                [
                    {"number": "6", "solved": True, "answer": "①"},
                    {"number": "7", "solved": True, "answer": "③"},
                ],
                ensure_ascii=False,
            )
        ],
        monkeypatch,
        tmp_path,
    )
    out = p.solve_batch([{"number": 6}, {"number": 7}])
    assert len(out) == 1
    assert out[0].provider == "local-llm"
    assert out[0].value[0]["answer"] == "①"


def test_solve_batch_strips_think_block(monkeypatch, tmp_path):
    p = _provider(
        ["<think>reasoning…</think>\n[{\"number\": \"1\", \"solved\": true, \"answer\": \"42\"}]"],
        monkeypatch,
        tmp_path,
    )
    out = p.solve_batch([{"number": 1}])
    assert out[0].value[0]["answer"] == "42"


def test_solve_batch_strips_code_fence(monkeypatch, tmp_path):
    p = _provider(
        ["```json\n[{\"number\": \"2\", \"solved\": true, \"answer\": \"④\"}]\n```"],
        monkeypatch,
        tmp_path,
    )
    out = p.solve_batch([{"number": 2}])
    assert out[0].value[0]["answer"] == "④"


def test_solve_batch_chunks_by_ten(monkeypatch, tmp_path):
    p = _provider(["[]", "[]"], monkeypatch, tmp_path)
    p.solve_batch([{"number": i} for i in range(11)])
    client = p._client
    assert len(client.chat.completions.calls) == 2


def test_solve_batch_run_nonce_varies_prompt(monkeypatch, tmp_path):
    p = _provider(["[]", "[]"], monkeypatch, tmp_path)
    p.solve_batch([{"number": 1}], run=0)
    p.solve_batch([{"number": 1}], run=1)
    calls = p._client.chat.completions.calls
    assert calls[0]["messages"][0]["content"] != calls[1]["messages"][0]["content"]
    assert "독립 검증 2회차" in calls[1]["messages"][0]["content"]


def test_malformed_json_retries_and_eventually_returns_empty(monkeypatch, tmp_path):
    p = _provider(["not json", "still not json", "also bad"], monkeypatch, tmp_path)
    out = p.solve_batch([{"number": 1}])
    assert out[0].value == []
    assert out[0].confidence == 0.0
    assert len(p._client.chat.completions.calls) == 3


def test_solve_single_problem(monkeypatch, tmp_path):
    p = _provider(
        ['{"solved": true, "answer": "②", "steps": ["a", "b"]}'],
        monkeypatch,
        tmp_path,
    )
    cand = p.solve({"number": 9, "body": "…"})
    assert cand.value["answer"] == "②"


def test_response_format_json_object_requested(monkeypatch, tmp_path):
    p = _provider(["[]"], monkeypatch, tmp_path)
    p.solve_batch([{"number": 1}])
    assert p._client.chat.completions.calls[0]["response_format"] == {
        "type": "json_object"
    }


def test_runner_registers_local_when_enabled(monkeypatch):
    import jobs.runner as runner

    monkeypatch.setenv("EXAMDNA_ENABLE_LOCAL_LLM", "1")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "qwen3:32b")
    providers = runner.default_providers()
    assert any(p.name == "local-llm" for p in providers.solver)
    assert providers.solver[0].name == "local-llm"


def test_runner_skips_local_when_disabled(monkeypatch):
    import jobs.runner as runner

    monkeypatch.delenv("EXAMDNA_ENABLE_LOCAL_LLM", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    providers = runner.default_providers()
    assert all(p.name != "local-llm" for p in providers.solver)
