"""Local/LAN LLM provider — OpenAI-compatible chat-completions endpoint.

Talks to a self-hosted server (Ollama, LM Studio, llama.cpp server,
vLLM, …) on another machine — e.g. a Mac Studio on the same LAN:

    OLLAMA_HOST=0.0.0.0 ollama serve          # on the Mac Studio
    EXAMDNA_ENABLE_LOCAL_LLM=1
    LOCAL_LLM_BASE_URL=http://192.168.0.10:11434/v1
    LOCAL_LLM_MODEL=qwen3:32b

Covers the solver + reasoning roles only — text in, JSON out. Image
roles (ocr/vision) stay with providers that actually accept images.
Data never leaves the LAN, which makes this the preferred solver for
real student materials when a sufficiently strong local model exists.

Reuses the Gemini prompt constants and JSON repair logic so prompt
changes apply to every backend consistently. The `openai` SDK is used
only for its chat-completions transport — the operational OpenAI
provider (Responses API) is a different, unrelated surface.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from document.models import Candidate
from providers.gemini.provider import (
    _SOLVE_BATCH_PROMPT,
    _SOLVE_PROMPT,
    _parse_json,
)

MAX_RETRIES = 3
MIN_INTERVAL = float(os.environ.get("LOCAL_LLM_MIN_INTERVAL", "0.0"))
_rate_lock = threading.Lock()
_last_call = 0.0

# Bounded concurrency for in-flight local calls — callers that
# parallelize questions share one semaphore (LOCAL_LLM_CONCURRENCY).
_concurrency_lock = threading.Lock()
_sem: threading.Semaphore | None = None


def _semaphore() -> threading.Semaphore:
    global _sem
    if _sem is None:
        with _concurrency_lock:
            if _sem is None:
                _sem = threading.Semaphore(
                    int(os.environ.get("LOCAL_LLM_CONCURRENCY", "4"))
                )
    return _sem

CACHE_DIR = Path(
    os.environ.get(
        "LOCAL_LLM_CACHE_DIR",
        Path(__file__).resolve().parents[2] / "data" / "cache" / "local_llm",
    )
)
CACHE_ENABLED = os.environ.get("LOCAL_LLM_CACHE", "1") != "0"

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think(text: str) -> str:
    """Qwen3/QwQ-style models may prepend a <think> block before the JSON."""
    return _THINK_RE.sub("", text).strip()


def _cache_key(model: str, prompt: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()


def _cache_get(key: str) -> str | None:
    if not CACHE_ENABLED:
        return None
    path = CACHE_DIR / f"{key}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else None


def _cache_put(key: str, text: str) -> None:
    if not CACHE_ENABLED or not text:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.txt").write_text(text, encoding="utf-8")


def _pace() -> None:
    if MIN_INTERVAL <= 0:
        return
    global _last_call
    with _rate_lock:
        gap = time.time() - _last_call
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        _last_call = time.time()


class LocalLLMProvider:
    """Chat-completions provider covering solver/reasoning roles."""

    name = "local-llm"

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        client: Any = None,
        name: Optional[str] = None,
    ):
        if client is not None:
            self._client = client
        else:
            from openai import OpenAI

            self._client = OpenAI(
                base_url=base_url or os.environ["LOCAL_LLM_BASE_URL"],
                # Ollama/LM Studio ignore the key but the SDK requires one.
                api_key=os.environ.get("LOCAL_LLM_API_KEY") or "local",
                timeout=float(os.environ.get("LOCAL_LLM_TIMEOUT", "600")),
                max_retries=0,
            )
        self.model = model or os.environ.get("LOCAL_LLM_MODEL", "qwen3:32b")
        # Secondary slots carry the model in the provider name so source
        # independence is keyed on model identity: two slots pointing at
        # the same model collapse to one evidence source, and a cached
        # reply can never masquerade as an independent agreement.
        if name:
            self.name = name

    # -- roles ---------------------------------------------------------------

    def solve_batch(self, problems: list[dict[str, Any]], run: int = 0) -> list[Candidate]:
        """Same contract as the Gemini solver: chunked calls (10 at a time —
        large batches overflow local output budgets too), one Candidate with
        the per-question result list."""
        # Local models generate at ~7tok/s — a 10-question batch with full
        # solutions exceeds the client timeout. LOCAL_LLM_SOLVE_CHUNK lets
        # operators trade latency for smaller calls; each call is its own
        # evidence unit either way.
        chunk_size = int(os.environ.get("LOCAL_LLM_SOLVE_CHUNK", "10"))
        out: list[Any] = []
        for i in range(0, len(problems), chunk_size):
            chunk = problems[i : i + chunk_size]
            prompt = (
                _SOLVE_BATCH_PROMPT
                + "\n\n문제들:\n"
                + json.dumps(chunk, ensure_ascii=False)
            )
            if run:
                prompt += f"\n\n(독립 검증 {run + 1}회차)"
            try:
                data = self._generate_json(prompt)
            except Exception:  # noqa: BLE001
                # A failed chunk (timeout, malformed JSON) must not sink
                # the whole batch — its questions simply stay unanswered,
                # which the downstream checks report honestly.
                data = None
            if isinstance(data, list):
                out.extend(data)
        return [Candidate(provider=self.name, value=out, confidence=0.85 if out else 0.0)]

    def solve(self, problem: dict[str, Any], run: int = 0) -> Candidate:
        prompt = _SOLVE_PROMPT + "\n\n문제:\n" + json.dumps(problem, ensure_ascii=False)
        if run:
            prompt += f"\n\n(독립 검증 {run + 1}회차)"
        try:
            data = self._generate_json(prompt)
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            return Candidate(provider=self.name, value={"solved": False, "answer": None}, confidence=0.0)
        return Candidate(provider=self.name, value=data, confidence=0.85)

    def complete(self, prompt: str, context: dict[str, Any] | None = None) -> Candidate:
        text = self._generate_text(
            json.dumps(context or {}, ensure_ascii=False) + "\n\n" + prompt
        )
        return Candidate(provider=self.name, value={"reply": text}, confidence=0.8)

    # -- transport -------------------------------------------------------------

    def _generate_json(self, prompt: str) -> Any:
        last_exc: Exception | None = None
        for attempt in range(3):
            # Nonce defeats the file cache on retry — a truncated/malformed
            # reply is cached verbatim, so the identical prompt would
            # replay the same broken JSON forever.
            p = prompt if not attempt else f"{prompt}\n\n(재시도 {attempt})"
            try:
                return _parse_json(_strip_think(self._call(p, json_mode=True)))
            except json.JSONDecodeError as exc:
                last_exc = exc
        raise last_exc

    def _generate_text(self, prompt: str) -> str:
        return _strip_think(self._call(prompt, json_mode=False))

    def _call(self, prompt: str, json_mode: bool) -> str:
        key = _cache_key(self.model, f"json={json_mode}\n{prompt}")
        if (cached := _cache_get(key)) is not None:
            return cached
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        # Some servers (llama.cpp/Ollama) reject response_format with 501
        # only AFTER generating the whole reply — learning that once and
        # skipping the flag thereafter avoids paying a full generation
        # per call just to be refused.
        if json_mode and not getattr(self, "_json_mode_unsupported", False):
            kwargs["response_format"] = {"type": "json_object"}
        if os.environ.get("LOCAL_LLM_DISABLE_THINKING") == "1":
            # Ollama qwen3/qwq accept `"think": false`; ignored elsewhere
            # only if the server tolerates unknown fields.
            kwargs["extra_body"] = {"think": False}
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            _pace()
            try:
                with _semaphore():
                    resp = self._client.chat.completions.create(**kwargs)
                text = resp.choices[0].message.content or ""
                _cache_put(key, text)
                return text
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                status = getattr(exc, "status_code", None)
                if "response_format" in kwargs and (status == 501 or status is None):
                    # Structured output unsupported or hung: some servers
                    # return 501, others (llama.cpp builds) never reply to
                    # a response_format request at all — the timeout path
                    # needs the same remedy, not another doomed retry.
                    # Plain-text fallback; _parse_json salvages the JSON.
                    self._json_mode_unsupported = True
                    kwargs.pop("response_format")
                    continue
                transient = status in (408, 409, 429, 500, 502, 503, 504) or (
                    status is None  # connection refused / reset / timeout
                )
                if not transient:
                    raise
                time.sleep(min(2**attempt * 2, 20) + random.uniform(0, 1))
        raise last_exc
