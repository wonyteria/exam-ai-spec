# Auxiliary layers — JEV / Codex boundary contract

Scope: these are **auxiliary** layers only. They are never part of the
reconstruction or content-generation path.

## JEV (`backend/providers/jev/adapter.py`)

- Disabled by default: `EXAMDNA_ENABLE_JEV=1` + `JEV_BASE_URL` required.
- Three verbs only: `route`, `review`, `gate`. There is no generate or
  reconstruct entrypoint — reconstruction content generation through JEV
  is structurally impossible.
- Payloads are typed pydantic models (`JevRouteRequest`,
  `JevReviewRequest`, `JevGateRequest`) with no image/binary fields.
  `_assert_sanitized` additionally scans every serialized payload for
  base64 blobs and `data:image/` URIs and refuses before any network
  call — a caller bug cannot become an exfiltration path.
- Permitted payloads: sanitized structured metadata and derived
  candidates only (ids, counts, field names, verdicts, short text).
- Disabled/unconfigured JEV always returns `NEEDS_REVIEW` — never an
  implicit allow.

## Codex (account / CLI / App Server)

- Development worker only: eval runs, fixture generation, code review.
  Never a runtime provider for real student materials.
- Account tokens/auth.json must never appear in backend code, logs,
  frontend, `.env`, or any public request path.
- Codex image generation may only produce **synthetic damaged-exam
  fixtures** and **UI visual tests**. Generated imagery is never
  restoration evidence.

## Local LLM (Ollama / LM Studio)

- `EXAMDNA_ENABLE_LOCAL_LLM=1` — text solver/reasoning roles.
  `LOCAL_LLM_MODEL` is the primary slot; `LOCAL_LLM_MODEL_ALT` registers
  a second model as an independent evidence source
  (`local-llm/<model>`). Pointing ALT at the same model registers
  nothing — a shared-cache replay is never independent agreement.
- `EXAMDNA_ENABLE_LOCAL_VISION=1` — trace-region proposals only.
  `_assert_local_base_url` allows loopback, RFC-1918, link-local, and
  `.local`/`.internal` hosts; anything else is refused at construction.
  Raw exam pages never leave the LAN.
- Vision latency on this Mac Studio (local-large 27.8B): ~110 s/page
  cold, cached on repeat. Solver ~7 tok/s.
