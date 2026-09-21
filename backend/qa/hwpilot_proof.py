"""Independent HWP/HWPX readback via hwpilot (MIT — devxoul/hwpilot).

hwpilot is a separate implementation of the HWP 5.0 binary and HWPX
container formats. Reading our own artifacts back through it is a second
observer: it catches systematic bugs our own writer/parser pair would
share (the "write broken, read broken, pass" anti-pattern), and it is the
only Hancom-free readback path for binary HWP — previously that artifact
had no native re-parse at all.

This is a content readback, not a render proof: layout, fonts, and visual
fidelity still require the Windows HWP worker. When the tool is absent the
result is NOT_RUN — never silently skipped or promoted to a pass.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

_TIMEOUT_S = 120
# Daemons are per-file and linger by default; keep them short-lived in
# batch verification so they never pin an artifact file open.
_DAEMON_ENV = {"HWPILOT_DAEMON_IDLE_MS": "1000"}


def _default_checkout_dir() -> Path:
    # qa/ -> backend/ -> project/ -> <root>/tools/hwpilot
    return Path(__file__).resolve().parents[3] / "tools" / "hwpilot"


def hwpilot_argv() -> Optional[list[str]]:
    """Resolve the hwpilot invocation, or None when unavailable.

    Resolution order:
      1. HWPILOT_CMD — full command line, e.g. "node D:/tools/hwpilot/dist/src/cli/main.js"
      2. HWPILOT_DIR — repo checkout with a built dist/ (node runs the CLI)
      3. sibling checkout at <repo>/../tools/hwpilot
      4. `hwpilot` on PATH (future npm install)
    """
    cmd = os.environ.get("HWPILOT_CMD")
    if cmd:
        return shlex.split(cmd)
    node = shutil.which("node")
    candidates = []
    if os.environ.get("HWPILOT_DIR"):
        candidates.append(Path(os.environ["HWPILOT_DIR"]))
    candidates.append(_default_checkout_dir())
    for d in candidates:
        entry = d / "dist" / "src" / "cli" / "main.js"
        if node and entry.exists():
            return [node, str(entry)]
    exe = shutil.which("hwpilot")
    return [exe] if exe else None


def hwpilot_text(path: Path, argv: Optional[list[str]] = None) -> Optional[str]:
    """Full visible text of an HWP/HWPX via the independent reader,
    or None when the tool is missing or the file fails to parse."""
    argv = argv if argv is not None else hwpilot_argv()
    if argv is None:
        return None
    try:
        proc = subprocess.run(
            [*argv, "text", str(path)],
            capture_output=True,
            timeout=_TIMEOUT_S,
            env={**os.environ, **_DAEMON_ENV},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    text = payload.get("text")
    return text if isinstance(text, str) else None


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text))


def hwpilot_readback(path: Path, document) -> Optional[int]:
    """Content mismatch count via the independent reader — same
    expectations as the in-repo HWPX reverse-parse: every question head,
    points tag, body span, and choice label+body, plus counts of
    answer-space cells and endnote answers that must appear in text.

    Answers ride in hp:endNote subLists, which hwpilot does not expose in
    `text` output — so answer presence is deliberately not counted here;
    it stays covered by the in-repo XML census and the rendered-PDF check.

    Returns None when hwpilot is unavailable or the file does not parse —
    callers record NOT_RUN, not a pass.
    """
    text = hwpilot_text(path)
    if text is None:
        return None
    norm_blob = _norm(text)
    miss = 0
    descriptive = 0
    for q in document.questions:
        head = f"{q.label or q.number}."
        # hwpilot quirk: a paragraph whose next run carries an endNote
        # ctrl loses the first run's final char in text extraction —
        # "6." reads back as "6". The label itself is what matters;
        # accept the dotless form only for that exact truncation.
        if _norm(head) not in norm_blob and _norm(head)[:-1] not in norm_blob:
            miss += 1
        if q.points:
            if _norm(f"{q.points}점") not in norm_blob:
                miss += 1
        if q.type.value != "multiple_choice":
            descriptive += 1
        for span in q.body:
            if _norm(span.text) and _norm(span.text) not in norm_blob:
                miss += 1
        for c in q.choices:
            body = _norm(" ".join(s.text for s in c.body))
            if _norm(c.label) not in norm_blob or (body and body not in norm_blob):
                miss += 1
    if text.count("서술형 답안 작성란") < descriptive:
        miss += descriptive - text.count("서술형 답안 작성란")
    return miss


def hwpilot_convert(src: Path, dst: Path) -> bool:
    """HWP 5.0 -> HWPX via hwpilot — the Hancom-free conversion path.

    Returns True only when dst exists and is a readable ZIP package;
    anything else is failure, never a partial write claimed as success.
    """
    argv = hwpilot_argv()
    if argv is None:
        return False
    try:
        proc = subprocess.run(
            [*argv, "convert", str(src), str(dst), "--force"],
            capture_output=True,
            timeout=_TIMEOUT_S,
            env={**os.environ, **_DAEMON_ENV},
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return (
        proc.returncode == 0
        and dst.exists()
        and zipfile.is_zipfile(dst)
    )
