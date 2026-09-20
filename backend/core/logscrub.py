"""WP10 — log scrubbing.

Student material and secrets must not leak into logs/events. Every
string emitted to logs or stored event payloads passes through
`scrub_text`, which redacts:
  - secrets: key/token/password assignments, bearer headers
  - absolute file paths (client machine layout)
  - email addresses and phone numbers
"""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(
        r"(?i)(api[_-]?key|token|secret|password|passwd|authorization)"
        r"(\s*[:=]\s*)['\"]?[^\s'\"]+"),
     r"\1\2<REDACTED>"),
    (re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"), "Bearer <REDACTED>"),
    (re.compile(r"[A-Za-z]:\\[^\s'\"]+"), "<PATH>"),
    (re.compile(r"/(?:home|Users|tmp|var)/[^\s'\"]+"), "<PATH>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
     "<EMAIL>"),
    (re.compile(r"\b0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}\b"), "<PHONE>"),
]


def scrub_text(text: str) -> str:
    out = str(text)
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out


def scrub_payload(value):
    """Recursively scrub strings inside dict/list payloads."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: scrub_payload(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub_payload(v) for v in value]
    return value
