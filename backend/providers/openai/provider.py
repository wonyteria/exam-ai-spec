"""Operational OpenAI adapter (WP04 / REQ-21, A11/A12).

Default production AI provider. Uses the Responses API with strict JSON
schema output — extraction results are schema-constrained, not
best-effort text. Every call is telemetry-logged (model, prompt/input
hashes, usage, attempts, outcome) and budget-checked before dispatch.

Prompt constants are shared with the Gemini adapter so prompt changes
apply to both providers consistently.
"""
from __future__ import annotations

import base64
import io
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Optional

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
from providers.telemetry import (
    BudgetExceeded,
    CallRecord,
    Telemetry,
    get_telemetry,
    hash_payload,
)

MAX_RETRIES = 5
_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}

# --- strict output schemas -------------------------------------------------------
# OpenAI strict mode requires every property in `required` and
# additionalProperties=false, so dynamic-key objects (choices) become
# arrays of {label, text} pairs and are normalized back afterwards.

_BBOX_SCHEMA = {
    "type": "object",
    "properties": {
        "ymin": {"type": "number"},
        "xmin": {"type": "number"},
        "ymax": {"type": "number"},
        "xmax": {"type": "number"},
    },
    "required": ["ymin", "xmin", "ymax", "xmax"],
    "additionalProperties": False,
}

_CHOICES_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "text": {"type": ["string", "null"]},
        },
        "required": ["label", "text"],
        "additionalProperties": False,
    },
}

_QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": ["string", "null"]},
        "number": {"type": ["string", "null"]},
        "type": {"type": ["string", "null"]},
        "points": {"type": ["number", "null"]},
        "body": {"type": ["string", "null"]},
        "choices": _CHOICES_SCHEMA,
        "equations": {"type": "array", "items": {"type": "string"}},
        "figure": {"type": ["string", "null"]},
        "bbox": {
            "type": ["object", "null"],
            "properties": _BBOX_SCHEMA["properties"],
            "required": _BBOX_SCHEMA["required"],
            "additionalProperties": False,
        },
    },
    "required": [
        "label", "number", "type", "points", "body",
        "choices", "equations", "figure", "bbox",
    ],
    "additionalProperties": False,
}

_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": _QUESTION_SCHEMA},
    },
    "required": ["questions"],
    "additionalProperties": False,
}

_REGION_SCHEMA = {
    "type": "object",
    "properties": {
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": ["string", "null"]}, **_BBOX_SCHEMA["properties"]},
                "required": ["label", "ymin", "xmin", "ymax", "xmax"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["regions"],
    "additionalProperties": False,
}

_EXTRACT_SCHEMA = _QUESTION_SCHEMA

_SOLVE_SCHEMA = {
    "type": "object",
    "properties": {
        "solved": {"type": "boolean"},
        "answer": {"type": ["string", "number", "null"]},
        "steps": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": ["string", "null"]},
    },
    "required": ["solved", "answer", "steps", "reason"],
    "additionalProperties": False,
}

_SOLVE_BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": ["string", "number", "null"]},
                    **_SOLVE_SCHEMA["properties"],
                },
                "required": ["number", "solved", "answer", "steps", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["results"],
    "additionalProperties": False,
}

_EDIT_OPS_SCHEMA = {
    "type": "object",
    "properties": {
        "ops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "field": {"type": "string"},
                    "choice": {"type": ["string", "null"]},
                    "index": {"type": ["number", "null"]},
                    "value": {},
                },
                "required": ["question", "field", "choice", "index", "value"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["ops"],
    "additionalProperties": False,
}


def _choices_to_dict(item: dict) -> dict:
    """Normalize schema-constrained choices (array of {label,text}) back to
    the {label: text} mapping the pipeline consumes."""
    ch = item.get("choices")
    if isinstance(ch, list):
        item["choices"] = {
            str(c.get("label")): c.get("text")
            for c in ch
            if isinstance(c, dict) and c.get("label") is not None
        }
    elif not isinstance(ch, dict):
        item["choices"] = {}
    return item


class OpenAIProvider:
    """OpenAI-backed provider covering vision/ocr/math-ocr/llm/solver roles."""

    name = "openai"

    def __init__(
        self,
        model: Optional[str] = None,
        client: Any = None,
        telemetry: Optional[Telemetry] = None,
    ):
        if client is not None:
            self._client = client
        else:
            from openai import OpenAI

            self._client = OpenAI(timeout=180.0, max_retries=0)
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-5-mini")
        self.telemetry = telemetry or get_telemetry()

    # -- pipeline surface ----------------------------------------------------

    def extract_page(self, image: Path) -> list[Candidate]:
        try:
            data = self._generate_json(
                [self._image_content(image), {"type": "input_text", "text": _PAGE_PROMPT}],
                schema=_PAGE_SCHEMA,
                schema_name="page_extraction",
                method="extract_page",
            )
        except (json.JSONDecodeError, BudgetExceeded, RuntimeError):
            return []
        questions = data.get("questions") if isinstance(data, dict) else None
        if not isinstance(questions, list):
            return []
        return [
            Candidate(
                provider=self.name,
                value=[_choices_to_dict(dict(q)) for q in questions if isinstance(q, dict)],
                confidence=0.9,
                meta={"page_extract": True},
            )
        ]

    def detect_regions(self, image: Path) -> list[Candidate]:
        try:
            data = self._generate_json(
                [self._image_content(image), {"type": "input_text", "text": _REGION_PROMPT}],
                schema=_REGION_SCHEMA,
                schema_name="region_detection",
                method="detect_regions",
            )
        except (json.JSONDecodeError, BudgetExceeded, RuntimeError):
            return []
        regions = data.get("regions") if isinstance(data, dict) else None
        if not isinstance(regions, list):
            return []
        return [
            Candidate(
                provider=self.name,
                confidence=0.9,
                value={
                    "label": str(item.get("label") or i + 1),
                    "bbox": {
                        "ymin": float(item["ymin"]),
                        "xmin": float(item["xmin"]),
                        "ymax": float(item["ymax"]),
                        "xmax": float(item["xmax"]),
                    },
                },
            )
            for i, item in enumerate(regions)
            if isinstance(item, dict)
        ]

    def recognize_text(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        try:
            data = self._generate_json(
                [
                    self._image_content(image, region),
                    {"type": "input_text", "text": _EXTRACT_PROMPT},
                ],
                schema=_EXTRACT_SCHEMA,
                schema_name="question_extraction",
                method="recognize_text",
            )
        except (json.JSONDecodeError, BudgetExceeded, RuntimeError):
            return []
        if not isinstance(data, dict):
            return []
        return [
            Candidate(
                provider=self.name,
                value=_choices_to_dict(data),
                confidence=0.9,
                meta={"structured": True},
            )
        ]

    def recognize_math(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        return []

    def describe(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        return []

    def solve(self, problem: dict[str, Any], run: int = 0) -> Candidate:
        prompt = _SOLVE_PROMPT + "\n\n문제:\n" + json.dumps(problem, ensure_ascii=False)
        if run:
            prompt += f"\n\n(독립 검증 {run + 1}회차)"
        try:
            data = self._generate_json(
                [{"type": "input_text", "text": prompt}],
                schema=_SOLVE_SCHEMA,
                schema_name="solve",
                method="solve",
            )
        except (json.JSONDecodeError, BudgetExceeded, RuntimeError):
            data = None
        if not isinstance(data, dict):
            return Candidate(provider=self.name, value={"solved": False, "answer": None}, confidence=0.0)
        return Candidate(provider=self.name, value=data, confidence=0.85)

    def solve_batch(self, problems: list[dict[str, Any]], run: int = 0) -> list[Candidate]:
        prompt = _SOLVE_BATCH_PROMPT + "\n\n문제들:\n" + json.dumps(problems, ensure_ascii=False)
        if run:
            prompt += f"\n\n(독립 검증 {run + 1}회차)"
        try:
            data = self._generate_json(
                [{"type": "input_text", "text": prompt}],
                schema=_SOLVE_BATCH_SCHEMA,
                schema_name="solve_batch",
                method="solve_batch",
            )
        except (json.JSONDecodeError, BudgetExceeded, RuntimeError):
            data = None
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return [Candidate(provider=self.name, value=[], confidence=0.0)]
        return [Candidate(provider=self.name, value=results, confidence=0.85)]

    def edit_ops(self, summary: list[dict], instruction: str) -> list[dict]:
        prompt = (
            _EDIT_PROMPT
            + "\n\n문서:\n"
            + json.dumps(summary, ensure_ascii=False)
            + "\n\n지시:\n"
            + instruction
        )
        try:
            data = self._generate_json(
                [{"type": "input_text", "text": prompt}],
                schema=_EDIT_OPS_SCHEMA,
                schema_name="edit_ops",
                method="edit_ops",
            )
        except (json.JSONDecodeError, BudgetExceeded, RuntimeError):
            return []
        ops = data.get("ops") if isinstance(data, dict) else None
        return ops if isinstance(ops, list) else []

    def complete(self, prompt: str, context: dict[str, Any] | None = None) -> Candidate:
        text = self._generate_text(
            [{"type": "input_text", "text": json.dumps(context or {}, ensure_ascii=False)},
             {"type": "input_text", "text": prompt}],
            method="complete",
        )
        return Candidate(provider=self.name, value={"reply": text}, confidence=0.8)

    # -- transport -------------------------------------------------------------

    def _generate_json(
        self,
        content: list[dict],
        schema: dict,
        schema_name: str,
        method: str,
    ) -> Any:
        resp = self._call(content, method=method, schema=schema, schema_name=schema_name)
        return _parse_json(resp["text"])

    def _generate_text(self, content: list[dict], method: str) -> str:
        return self._call(content, method=method, schema=None, schema_name=None)["text"]

    def _call(
        self,
        content: list[dict],
        method: str,
        schema: Optional[dict],
        schema_name: Optional[str],
    ) -> dict:
        """One logical call: budget check, retry on 429/5xx, telemetry."""
        self.telemetry.check_budget()
        input_hash = hash_payload([json.dumps(content, ensure_ascii=False)])
        started = time.time()
        last_exc: Optional[Exception] = None
        attempts = 0
        for attempt in range(MAX_RETRIES):
            attempts += 1
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "input": [{"role": "user", "content": content}],
                }
                if schema is not None:
                    kwargs["text"] = {
                        "format": {
                            "type": "json_schema",
                            "name": schema_name,
                            "schema": schema,
                            "strict": True,
                        }
                    }
                resp = self._client.responses.create(**kwargs)
                usage = getattr(resp, "usage", None)
                self.telemetry.record(
                    CallRecord(
                        ts=time.time(),
                        provider=self.name,
                        model=self.model,
                        method=method,
                        prompt_sha256=input_hash,
                        input_sha256=input_hash,
                        outcome="ok" if attempt == 0 else "retry",
                        attempts=attempts,
                        latency_ms=(time.time() - started) * 1000,
                        input_tokens=getattr(usage, "input_tokens", None),
                        output_tokens=getattr(usage, "output_tokens", None),
                    )
                )
                return {"text": resp.output_text}
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                status = getattr(exc, "status_code", None)
                if status not in _RETRYABLE_STATUS:
                    self._record_error(method, input_hash, started, attempts, exc)
                    raise
                wait = min(2**attempt * 2, 60) + random.uniform(0, 2)
                time.sleep(wait)
        self._record_error(method, input_hash, started, attempts, last_exc)
        raise last_exc  # type: ignore[misc]

    def _record_error(self, method, input_hash, started, attempts, exc) -> None:
        self.telemetry.record(
            CallRecord(
                ts=time.time(),
                provider=self.name,
                model=self.model,
                method=method,
                prompt_sha256=input_hash,
                input_sha256=input_hash,
                outcome="error",
                attempts=attempts,
                latency_ms=(time.time() - started) * 1000,
                error_class=type(exc).__name__ if exc else "unknown",
            )
        )

    # -- helpers ----------------------------------------------------------------

    @staticmethod
    def _image_content(image: Path, region: BBox | None = None) -> dict:
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
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {
            "type": "input_image",
            "image_url": f"data:image/png;base64,{b64}",
        }
