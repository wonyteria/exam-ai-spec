"""Deterministic offline replay provider for golden regression tests.

Implements the provider surface used by the pipeline by replaying the
recorded response cache byte-for-byte. A cache miss raises ``CacheMiss``
immediately — this provider never imports an SDK and never touches the
network (INV-12: a cached response is fixture data, not a live proof).
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image

from document.models import BBox, Candidate
from providers.gemini.provider import (
    _EDIT_PROMPT,
    _EXTRACT_PROMPT,
    _PAGE_PROMPT,
    _REGION_PROMPT,
    _SOLVE_BATCH_PROMPT,
    _SOLVE_PROMPT,
    _parse_json,
)


class CacheMiss(RuntimeError):
    """Raised when replay hits a key that is not in the fixture cache."""


class _ReplayPart:
    """Duck-typed stand-in for google genai ``types.Part`` used only so the
    cache-key hash matches the recorded live calls (``inline_data.data``)."""

    def __init__(self, data: bytes, mime_type: str = "image/png"):
        self.inline_data = SimpleNamespace(data=data, mime_type=mime_type)


def _image_part(image: Path, region: BBox | None = None) -> _ReplayPart:
    with Image.open(image) as im:
        base = im.convert("RGB")
        if region is not None:
            base = base.crop(
                (
                    int(region.x),
                    int(region.y),
                    int(region.x + region.w),
                    int(region.y + region.h),
                )
            )
        buf = io.BytesIO()
        base.save(buf, "PNG")
    return _ReplayPart(buf.getvalue())


def _cache_key(model: str, contents: list[Any]) -> str:
    h = hashlib.sha256(model.encode())
    for c in contents:
        if isinstance(c, str):
            h.update(c.encode())
            continue
        data = getattr(getattr(c, "inline_data", None), "data", None)
        h.update(data if isinstance(data, bytes) else repr(c).encode())
    return h.hexdigest()


class CacheReplayProvider:
    """Replays recorded model responses from a fixture cache directory."""

    name = "replay_cache"

    def __init__(self, cache_dir: Path, model: str = "gemini-3.1-flash-lite"):
        self.cache_dir = Path(cache_dir)
        self.model = model

    # -- internal ---------------------------------------------------------
    def _lookup(self, contents: list[Any]) -> str:
        key = _cache_key(self.model, contents)
        path = self.cache_dir / f"{key}.txt"
        if not path.exists():
            raise CacheMiss(f"{key} ({self.model})")
        return path.read_text(encoding="utf-8")

    def _generate_json(self, parts: list[Any], prompt: str | None = None) -> Any:
        contents = [*parts, prompt] if prompt else parts
        return _parse_json(self._lookup(contents))

    # -- pipeline surface ---------------------------------------------------
    def extract_page(self, image: Path) -> list[Candidate]:
        data = self._generate_json([_image_part(image)], _PAGE_PROMPT)
        if not isinstance(data, list):
            return []
        return [
            Candidate(provider=self.name, value=data, confidence=0.9, meta={"page_extract": True})
        ]

    def detect_regions(self, image: Path) -> list[Candidate]:
        data = self._generate_json([_image_part(image)], _REGION_PROMPT)
        if not isinstance(data, list):
            return []
        return [
            Candidate(
                provider=self.name,
                confidence=0.9,
                value={
                    "label": str(item.get("label", i + 1)),
                    "bbox": {
                        "ymin": float(item["ymin"]),
                        "xmin": float(item["xmin"]),
                        "ymax": float(item["ymax"]),
                        "xmax": float(item["xmax"]),
                    },
                },
            )
            for i, item in enumerate(data)
            if isinstance(item, dict)
        ]

    def recognize_text(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        data = self._generate_json([_image_part(image, region)], _EXTRACT_PROMPT)
        if not isinstance(data, dict):
            return []
        return [Candidate(provider=self.name, value=data, confidence=0.9, meta={"structured": True})]

    def recognize_math(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        return []

    def describe(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        return []

    def solve_batch(self, problems: list[dict[str, Any]], run: int = 0) -> list[Candidate]:
        prompt = _SOLVE_BATCH_PROMPT + "\n\n문제들:\n" + json.dumps(problems, ensure_ascii=False)
        if run:
            prompt += f"\n\n(독립 검증 {run + 1}회차)"
        data = self._generate_json([prompt])
        if not isinstance(data, list):
            return [Candidate(provider=self.name, value=[], confidence=0.0)]
        return [Candidate(provider=self.name, value=data, confidence=0.85)]

    def solve(self, problem: dict[str, Any], run: int = 0) -> Candidate:
        prompt = _SOLVE_PROMPT + "\n\n문제:\n" + json.dumps(problem, ensure_ascii=False)
        if run:
            prompt += f"\n\n(독립 검증 {run + 1}회차)"
        data = self._generate_json([prompt])
        if not isinstance(data, dict):
            return Candidate(provider=self.name, value={"solved": False, "answer": None}, confidence=0.0)
        return Candidate(provider=self.name, value=data, confidence=0.85)

    def edit_ops(self, summary: list[dict], instruction: str) -> list[dict]:
        prompt = (
            _EDIT_PROMPT
            + "\n\n문서:\n"
            + json.dumps(summary, ensure_ascii=False)
            + "\n\n지시:\n"
            + instruction
        )
        data = self._generate_json([prompt])
        return data if isinstance(data, list) else []

    def complete(self, prompt: str, context: dict[str, Any] | None = None) -> Candidate:
        text = self._lookup([json.dumps(context or {}, ensure_ascii=False), prompt])
        return Candidate(provider=self.name, value={"reply": text}, confidence=0.8)
