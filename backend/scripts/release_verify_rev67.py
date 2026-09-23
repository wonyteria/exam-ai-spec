"""Release-blocking verification for doc_8dc95bea7fcb rev 67.

Re-runs canonical checks with the local-llm solver (local-large, plus
local-long as the configured independent alternate), logs every real
HTTP call and every file-cache hit as evidence, and replays the
RECORDED Gemini solver results from the on-disk cache only — no
external API is contacted (EXAMDNA_ENABLE_GEMINI is forced off and the
gemini client is never constructed).

Outputs under data/release_verify/:
  checks_rev67.json      — check states after re-run
  llm_calls.jsonl        — one record per real HTTP call / cache hit
  solver_answers.json    — per-question answers: recorded vs gemini
                           (cached) vs local run0/run1 vs local-long
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
os.environ["EXAMDNA_ENABLE_GEMINI"] = "0"  # belt-and-braces: no external provider

DATA = Path("data/service_e2e")
EVIDENCE = Path("data/release_verify")
EVIDENCE.mkdir(parents=True, exist_ok=True)
CALLS = EVIDENCE / "llm_calls.jsonl"
CALLS.write_text("")


def _log(record: dict) -> None:
    with CALLS.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


from canonical.store import CanonicalStore  # noqa: E402
from canonical.service import MutationService  # noqa: E402
from core.examdna import Providers  # noqa: E402
from storage.local import LocalObjectStore  # noqa: E402
from tenancy.db import TenancyDB  # noqa: E402
from providers.local.provider import LocalLLMProvider  # noqa: E402
import providers.local.provider as lp  # noqa: E402
import providers.gemini.provider as gp  # noqa: E402

# --- instrumentation -------------------------------------------------------
_orig_cache_get = lp._cache_get


def _logged_cache_get(key: str):
    hit = _orig_cache_get(key)
    _log({"kind": "local_cache", "key": key[:16], "hit": hit is not None, "ts": time.time()})
    return hit


lp._cache_get = _logged_cache_get

local = LocalLLMProvider(model="local-large")
# This server already proved (two observed attempts) that it either 501s
# or hangs on response_format requests — prime the flag so the verify run
# doesn't burn a 900s timeout relearning it.
local._json_mode_unsupported = True
alt_model = os.environ.get("LOCAL_LLM_MODEL_ALT")
alt = (
    LocalLLMProvider(model=alt_model, name=f"local-llm/{alt_model}")
    if alt_model and alt_model != local.model
    else None
)


def _instrument(p) -> None:
    orig = p._client.chat.completions.create

    def wrapped(**kwargs):
        rec = {
            "kind": "http_call",
            "ts": time.time(),
            "provider": p.name,
            "model": kwargs.get("model"),
            "prompt_sha256": hashlib.sha256(
                json.dumps(kwargs.get("messages"), ensure_ascii=False).encode()
            ).hexdigest(),
        }
        _log(rec)
        t0 = time.time()
        try:
            resp = orig(**kwargs)
            rec["duration_s"] = time.time() - t0
            rec["ok"] = True
            return resp
        except Exception as exc:
            rec["duration_s"] = time.time() - t0
            rec["ok"] = False
            rec["error"] = f"{type(exc).__name__}: {exc}"[:200]
            raise
        finally:
            rec["kind"] = "http_done"
            _log(rec)

    p._client.chat.completions.create = wrapped


_instrument(local)
if alt:
    alt._json_mode_unsupported = True
    _instrument(alt)

# --- run checks on rev 67 ---------------------------------------------------
store = CanonicalStore(DATA / "canonical.db")
svc = MutationService(store, TenancyDB(DATA / "tenancy.db"))
objects = LocalObjectStore(DATA / "objects")

rev = next(r for r in store.list_revisions("doc_8dc95bea7fcb") if r.revision_no == 67)
print(f"revision: {rev.id} (no. 67)", flush=True)

providers = Providers()
providers.solver = [local] + ([alt] if alt else [])
print("solver slots:", [f"{p.name}:{getattr(p, 'model', '?')}" for p in providers.solver], flush=True)
# NOTE: providers.ocr left empty — no local OCR auditor is installed
# (paddleocr/easyocr absent), so ORIGINAL_SOURCE_FIDELITY must honestly
# report NOT_RUN rather than silently auditing with an external API.

t0 = time.time()
checks = svc.run_checks(rev.id, providers=providers, objects=objects)
elapsed = time.time() - t0
(EVIDENCE / "checks_rev67.json").write_text(
    json.dumps(
        {
            "elapsed_s": elapsed,
            "solver_slots": [f"{p.name}:{p.model}" for p in providers.solver],
            "checks": [c.model_dump(mode="json") for c in checks],
        },
        ensure_ascii=False,
        indent=1,
    )
)
for c in checks:
    print(f"  {c.check_kind}: {c.state.value} | {c.result_summary}", flush=True)

# --- gemini cache-only replay (recorded results, no network) ----------------
from document.models import Document  # noqa: E402

doc = Document.model_validate(rev.content_json)

parents = {q.parent_id for q in doc.questions if q.parent_id}
stem_by_id = {q.id: svc._spans_text(q.body) for q in doc.questions if q.id in parents}
problems = [svc._problem_payload(q, stem_by_id) for q in doc.questions if q.id not in parents]
print(f"problems for solver: {len(problems)} (parents excluded: {len(parents)})", flush=True)

gemini_model = os.environ.get("GEMINI_MODEL_SOLVER", "gemini-3-flash-preview")
gemini_answers: dict[str, str] = {}
gemini_chunks_missing = 0
for i in range(0, len(problems), 10):
    chunk = problems[i : i + 10]
    prompt = gp._SOLVE_BATCH_PROMPT + "\n\n문제들:\n" + json.dumps(chunk, ensure_ascii=False)
    key = gp._cache_key(gemini_model, [prompt])
    cached = gp._cache_get(key)
    if cached is None:
        gemini_chunks_missing += 1
        _log({"kind": "gemini_cache", "key": key[:16], "hit": False, "chunk": i // 10})
        continue
    _log({"kind": "gemini_cache", "key": key[:16], "hit": True, "chunk": i // 10})
    try:
        data = gp._parse_json(cached)
    except Exception:
        data = None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("solved") and item.get("number") is not None:
                from canonical.service import _norm_answer

                gemini_answers[str(item["number"]).strip()] = _norm_answer(item.get("answer"))
print(f"gemini cached answers: {len(gemini_answers)} (missing chunks: {gemini_chunks_missing})", flush=True)

# --- local solver passes (captured via wrapper) -----------------------------
captured: dict[str, dict] = {}


def _capture(p, tag):
    orig = p.solve_batch

    def wrapped(probs, run=0):
        res = orig(probs, run=run)
        captured[f"{tag}:run{run}"] = svc._batch_answers(res)
        return res

    p.solve_batch = wrapped


# run_checks already ran both passes through `local`; recompute the maps
# from the record (run_checks used the same provider object — captured
# dict was not wired then, so call solve_batch again; identical prompts
# are file-cache hits, not fresh HTTP calls).
_capture(local, "local-large")
local_run0 = svc._batch_answers(local.solve_batch(problems, run=0))
local_run1 = svc._batch_answers(local.solve_batch(problems, run=1))
alt_run0 = svc._batch_answers(alt.solve_batch(problems, run=0)) if alt else {}

from canonical.service import _norm_answer, _answers_match  # noqa: E402

rows = []
for q in doc.questions:
    label = q.label or str(q.number)
    if q.id in parents:
        continue
    recorded = _norm_answer(q.answer.value) if q.answer and q.answer.value else None
    g = gemini_answers.get(label)
    l0 = local_run0.get(label)
    l1 = local_run1.get(label)
    a0 = alt_run0.get(label)
    rows.append(
        {
            "label": label,
            "recorded": recorded,
            "gemini_cached": g,
            "local_large_run0": l0,
            "local_large_run1": l1,
            "local_long_run0": a0,
            "recorded_vs_local": _answers_match(recorded, l0) if recorded and l0 else None,
            "recorded_vs_gemini": _answers_match(recorded, g) if recorded and g else None,
            "gemini_vs_local": _answers_match(g, l0) if g and l0 else None,
            "local_run0_vs_run1": _answers_match(l0, l1) if l0 and l1 else None,
            "local_vs_alt": _answers_match(l0, a0) if l0 and a0 else None,
        }
    )

(EVIDENCE / "solver_answers.json").write_text(
    json.dumps(
        {
            "gemini_model": gemini_model,
            "local_model": local.model,
            "alt_model": alt.model if alt else None,
            "rows": rows,
        },
        ensure_ascii=False,
        indent=1,
    )
)

n = len(rows)
agree = sum(1 for r in rows if r["recorded_vs_local"] is True)
print(f"\nrecorded vs local-large: {agree}/{n} agree", flush=True)
for r in rows:
    print(
        f"  q{r['label']:>4}: recorded={r['recorded']} gemini={r['gemini_cached']} "
        f"local0={r['local_large_run0']} local1={r['local_large_run1']} alt={r['local_long_run0']}",
        flush=True,
    )
print("done", flush=True)
