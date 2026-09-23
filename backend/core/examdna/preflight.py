"""Capability preflight (Phase 1).

One bounded probe pass before any stage runs: which providers exist,
which are actually reachable, and which features the reachable ones
support (e.g. response_format/json mode). Results are recorded once per
job and carried on the context — stages consult the report instead of
discovering capability mid-flight via a 900s timeout.

Only LOCAL endpoints are ever probed (localhost/LAN, same guard as the
vision path). External providers are recorded as configured-or-absent —
this pipeline never sends even a ping to an external API.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class CapabilityReport:
    """Recorded once per job; consumed by stage contracts (`requires`)
    and written to <job_dir>/preflight.json as evidence."""

    generated_at: float = field(default_factory=time.time)
    capabilities: dict[str, Any] = field(default_factory=dict)

    def has(self, key: str) -> bool:
        return bool(self.capabilities.get(key, {}).get("available"))

    def as_dict(self) -> dict:
        return {"generated_at": self.generated_at, "capabilities": self.capabilities}


def _probe_local_endpoint(base_url: str, timeout: float = 3.0) -> dict:
    """Bounded reachability probe for an OpenAI-compatible LOCAL server.
    The base URL is re-validated against the local-only allowlist — a
    misconfigured provider must fail closed here, not later."""
    from providers.local.trace import _assert_local_base_url

    try:
        _assert_local_base_url(base_url)
    except ValueError as exc:
        return {"available": False, "reason": f"non-local base_url rejected: {exc}"}
    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return {
            "available": True,
            "models": [m.get("id") for m in data.get("data", [])],
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}


def _probe_json_mode(provider, timeout: float = 15.0) -> Optional[bool]:
    """Learn response_format support once — a max_tokens=1 probe, so a
    server that hangs on structured output costs seconds, not a full
    generation. The learned flag is stored back on the provider so the
    real calls never repeat the probe."""
    client = getattr(provider, "_client", None)
    if client is None:
        return None
    try:
        client.chat.completions.create(
            model=provider.model,
            messages=[{"role": "user", "content": "1"}],
            max_tokens=1,
            temperature=0,
            response_format={"type": "json_object"},
            timeout=timeout,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        status = getattr(exc, "status_code", None)
        if status == 501 or status is None:
            provider._json_mode_unsupported = True
            return False
        # Other errors (auth, model missing) say nothing about json_mode.
        return None


def run_preflight(providers) -> CapabilityReport:
    report = CapabilityReport()
    caps = report.capabilities

    # --- solver / reasoning (text roles) ----------------------------------
    solvers = []
    for p in getattr(providers, "solver", []) or []:
        entry: dict[str, Any] = {
            "name": getattr(p, "name", type(p).__name__),
            "model": getattr(p, "model", None),
        }
        base_url = str(getattr(getattr(p, "_client", None), "base_url", "") or "")
        is_local = False
        if base_url:
            from providers.local.trace import _assert_local_base_url

            try:
                _assert_local_base_url(base_url)
                is_local = True
            except ValueError:
                is_local = False
        if is_local:
            probe = _probe_local_endpoint(base_url)
            entry["endpoint"] = probe
            if probe.get("available"):
                entry["json_mode"] = _probe_json_mode(p)
        else:
            # External solver: record presence only — never probed.
            entry["endpoint"] = {"available": None, "reason": "external provider — not probed"}
        solvers.append(entry)
    caps["solver"] = {
        # A slot counts when its local endpoint answered the probe, or
        # it is a configured external provider (runtime failure will
        # surface as FAILED with evidence — not a silent pass).
        "available": any(
            s["endpoint"].get("available") in (True, None) for s in solvers
        ),
        "slots": solvers,
    }

    # --- OCR audit providers (non-stub, local engines) --------------------
    # Engines lazy-load, so "in the list" is not "usable" — probe the
    # backing module so a missing install is BLOCKED, not a surprise.
    _ENGINE_MODULES = {"paddleocr": "paddleocr", "easyocr": "easyocr"}
    ocr = []
    for p in getattr(providers, "ocr", []) or []:
        name = str(getattr(p, "name", ""))
        if name.startswith("stub"):
            continue
        module = _ENGINE_MODULES.get(name)
        usable = module is None or importlib.util.find_spec(module) is not None
        ocr.append(
            {
                "name": name,
                "usable": usable,
                "reason": None if usable else f"module '{module}' not installed",
            }
        )
    # A structured local VLM page extractor is also an OCR observer. It is
    # candidate-only and may still yield UNVERIFIED values, but it is enough
    # to run the consensus stage and materialize an inspectable draft. The
    # consensus rules, not this capability bit, decide whether it is final.
    for p in getattr(providers, "vision", []) or []:
        name = str(getattr(p, "name", ""))
        if hasattr(p, "extract_page") and not name.startswith("stub"):
            ocr.append({"name": name, "usable": True, "reason": "structured page extractor"})
    caps["ocr_audit"] = {
        "available": any(o["usable"] for o in ocr),
        "providers": ocr,
    }

    # --- vision trace detectors (local-only by construction) --------------
    trace = []
    for p in getattr(providers, "trace", []) or []:
        entry = {"name": getattr(p, "name", type(p).__name__)}
        base_url = str(getattr(getattr(p, "_client", None), "base_url", "") or "")
        if base_url:
            entry["endpoint"] = _probe_local_endpoint(base_url)
        trace.append(entry)
    caps["trace_detect"] = {
        "available": any(
            t.get("endpoint", {}).get("available") for t in trace
        ),
        "providers": trace,
    }

    # --- renderers / platform tools ---------------------------------------
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    caps["docx_render"] = {
        "available": bool(soffice),
        "path": soffice,
    }
    caps["hwp_worker"] = {
        "available": sys.platform == "win32",
        "reason": None if sys.platform == "win32" else "Windows + Hancom HWP required",
    }
    return report


def write_report(report: CapabilityReport, workdir: Path) -> Path:
    path = Path(workdir) / "preflight.json"
    path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=1))
    return path
