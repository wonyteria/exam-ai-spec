"""Local VLM trace detector — region-level student-trace candidates.

Uses the LAN vision model (Ollama/LM Studio, OpenAI-compatible image
input) to propose regions containing handwriting, grading marks, and
other student traces. Output is a candidate: normalized boxes that
ExamDNA's pixel policy must still adjudicate — the provider never
authorizes removal by itself.

    EXAMDNA_ENABLE_LOCAL_VISION=1
    LOCAL_LLM_BASE_URL=http://192.168.0.10:11434/v1
    LOCAL_LLM_VISION_MODEL=local-large   # falls back to LOCAL_LLM_MODEL
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from document.models import Candidate
from providers.local.provider import _parse_json, _strip_think

_TRACE_PROMPT = """이 시험지 이미지에서 학생이 손으로 쓴 필기(연필 풀이, 계산, 동그라미, 체크, 밑줄, 낙서)와 채점 마크가 있는 영역을 모두 찾아라.
인쇄된 문제 텍스트/도형/선택지는 제외하고, 각 영역을 가능한 한 타이트하게 잡아라.
페이지가 거꾸로(180°) 또는 옆으로 뒤집혀 있으면 "upside_down"을 true로 둬라.
JSON만 출력: {"traces": [{"x":0-1000, "y":0-1000, "w":0-1000, "h":0-1000, "kind":"handwriting|grading|mark"}], "upside_down": false}"""

_MAX_SIDE = 1024


def _assert_local_base_url(url: str) -> None:
    """Raw exam pages leave this machine only for a LOCAL inference
    server. Allowlist: loopback, RFC-1918/link-local LAN addresses, and
    .local/.internal hostnames (e.g. a Mac Studio on the same network).
    Anything else would push student images off-site — refused loudly."""
    from urllib.parse import urlparse
    import ipaddress

    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "localhost.localdomain") or host.endswith(
        (".local", ".internal")
    ):
        return
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback or ip.is_private or ip.is_link_local:
            return
    except ValueError:
        pass  # hostname, not an IP literal
    raise ValueError(
        f"LOCAL_LLM_BASE_URL must be loopback or LAN-local "
        f"(got {host!r}) — raw exam images never leave the network"
    )


class LocalVisionTraceProvider:
    """Region proposals from a local vision LLM."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        client: Any = None,
    ):
        if client is not None:
            self._client = client
        else:
            resolved = base_url or os.environ["LOCAL_LLM_BASE_URL"]
            _assert_local_base_url(resolved)
            from openai import OpenAI

            self._client = OpenAI(
                base_url=resolved,
                api_key=os.environ.get("LOCAL_LLM_API_KEY") or "local",
                timeout=float(os.environ.get("LOCAL_LLM_VISION_TIMEOUT", "300")),
                max_retries=0,
            )
        self.model = (
            model
            or os.environ.get("LOCAL_LLM_VISION_MODEL")
            or os.environ.get("LOCAL_LLM_MODEL")
            or "local-large"
        )
        self.name = f"local-vision:{self.model}"
        cache_dir = Path(
            os.environ.get(
                "LOCAL_LLM_CACHE_DIR",
                Path(__file__).resolve().parents[2] / "data" / "cache" / "local_llm",
            )
        )
        self._cache_dir = cache_dir
        self._cache_on = os.environ.get("LOCAL_LLM_CACHE", "1") != "0"

    def detect_traces(self, image: Path) -> Candidate:
        b64, digest = self._encode(image)
        key = hashlib.sha256(
            f"{self.model}\ntrace\n{digest}".encode()
        ).hexdigest()
        text = self._cached(key) or self._call(b64)
        if text and self._cache_on:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            (self._cache_dir / f"{key}.txt").write_text(text, encoding="utf-8")
        try:
            data = _parse_json(_strip_think(text or ""))
        except json.JSONDecodeError:
            data = None
        traces = data.get("traces") if isinstance(data, dict) else None
        if not isinstance(traces, list):
            traces = []
        upside_down = bool(
            isinstance(data, dict) and data.get("upside_down")
        )
        return Candidate(
            provider=self.name,
            value={"traces": traces, "upside_down": upside_down},
            confidence=0.7 if traces else 0.0,
            model_version=self.model,
            raw_output_sha256=hashlib.sha256((text or "").encode()).hexdigest(),
            timestamp=time.time(),
        )

    # -- transport -----------------------------------------------------------

    def _encode(self, image: Path) -> tuple[str, str]:
        from PIL import Image

        src = Path(image)
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        img = Image.open(src).convert("RGB")
        img.thumbnail((_MAX_SIDE, _MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode(), digest

    def _cached(self, key: str) -> Optional[str]:
        if not self._cache_on:
            return None
        p = self._cache_dir / f"{key}.txt"
        return p.read_text(encoding="utf-8") if p.exists() else None

    def _call(self, b64: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _TRACE_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}"
                            },
                        },
                    ],
                }
            ],
            temperature=0,
        )
        return resp.choices[0].message.content or ""
