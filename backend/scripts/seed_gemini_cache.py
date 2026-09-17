"""Seed the Gemini response cache from a saved document.

Reconstructs provider responses (detect_regions / recognize_text / solve)
from a completed document so subsequent pipeline runs replay without API
calls. Useful for offline dev and deterministic regression runs.

Usage:
    python scripts/seed_gemini_cache.py <document_id> [--job <job_id>]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from PIL import Image  # noqa: E402

from providers.gemini import provider as gp  # noqa: E402
from providers.gemini.provider import (  # noqa: E402
    _cache_key,
    _cache_put,
    _EXTRACT_PROMPT,
    _REGION_PROMPT,
    _SOLVE_PROMPT,
)
from core.examdna.recognition.segmenter import PAD  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"


def _image_bytes(image: Path, bbox: dict | None = None) -> bytes:
    with Image.open(image) as im:
        base = im.convert("RGB")
        if bbox is not None:
            base = base.crop(
                (int(bbox["x"]), int(bbox["y"]), int(bbox["x"] + bbox["w"]), int(bbox["y"] + bbox["h"]))
            )
        buf = io.BytesIO()
        base.save(buf, "PNG")
    return buf.getvalue()


def _part(data: bytes):
    from google.genai import types

    return types.Part.from_bytes(data=data, mime_type="image/png")


def _norm_bbox(bbox: dict, w: float, h: float) -> dict:
    """Invert segmenter._to_pixels padding to recover ~normalized coords."""

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    return {
        "xmin": clamp((bbox["x"] + PAD * w) / w * 1000, 0, 1000),
        "ymin": clamp((bbox["y"] + PAD * h) / h * 1000, 0, 1000),
        "xmax": clamp((bbox["x"] + bbox["w"] - PAD * w) / w * 1000, 0, 1000),
        "ymax": clamp((bbox["y"] + bbox["h"] - PAD * h) / h * 1000, 0, 1000),
    }


def seed(doc_id: str, job_id: str | None) -> int:
    doc = json.loads((DATA / "documents" / f"{doc_id}.json").read_text(encoding="utf-8"))
    pages = doc["pages"]
    seeded = 0

    for page in pages:
        image = Path(page["clean_uri"] or page["original"]["uri"])
        w, h = page["width"], page["height"]

        # detect_regions response for the whole page
        regions = [
            {
                "label": str(q.get("label") or q["number"]),
                **_norm_bbox(q["source"]["bbox"], w, h),
            }
            for q in doc["questions"]
            if q.get("source") and q["source"]["page"] == page["index"] and q["source"].get("bbox")
        ]
        key = _cache_key(
            "gemini-3.1-flash-lite",
            [_part(_image_bytes(image)), _REGION_PROMPT],
        )
        _cache_put(key, json.dumps(regions, ensure_ascii=False))
        seeded += 1

        # per-question extraction
        for q in doc["questions"]:
            src = q.get("source") or {}
            if src.get("page") != page["index"] or not src.get("bbox"):
                continue
            extraction = _question_to_extraction(q)
            if not extraction:
                continue
            key = _cache_key(
                "gemini-3.1-flash-lite",
                [_part(_image_bytes(image, src["bbox"])), _EXTRACT_PROMPT],
            )
            _cache_put(key, json.dumps(extraction, ensure_ascii=False))
            seeded += 1

        # solver responses
        for q in doc["questions"]:
            src = q.get("source") or {}
            if src.get("page") != page["index"]:
                continue
            problem = _problem_payload(q)
            if problem is None:
                continue
            answer = (q.get("answer") or {}).get("value")
            steps = [s["text"] for s in (q.get("solution") or {}).get("steps", [])]
            solved = {
                "solved": bool(answer),
                "answer": answer,
                "steps": steps,
                "reason": None if answer else "seed: no verified answer",
            }
            prompt = _SOLVE_PROMPT + "\n\n문제:\n" + json.dumps(problem, ensure_ascii=False)
            key = _cache_key("gemini-3.1-flash-lite", [prompt])
            _cache_put(key, json.dumps(solved, ensure_ascii=False))
            seeded += 1

    print(f"seeded {seeded} cache entries from {doc_id}")
    return seeded


def _question_to_extraction(q: dict) -> dict | None:
    if not q["body"] and not q["choices"]:
        return None
    return {
        "number": q.get("label") or q["number"],
        "type": q.get("type", "multiple_choice" if q["choices"] else "subjective"),
        "points": q.get("points"),
        "body": " ".join(t["text"] for t in q["body"]),
        "choices": {c["label"]: " ".join(t["text"] for t in c["body"]) for c in q["choices"]},
        "equations": [e["latex"] for e in q.get("equations", [])],
        "figure": (q.get("figures") or [{}])[0].get("topology", {}).get("description"),
    }


def _problem_payload(q: dict) -> dict | None:
    """Reconstruct the exact problem dict solving._problem sends."""
    if not (q["body"] or q.get("equations") or q.get("figures")):
        return None
    return {
        "number": q["number"],
        "type": q.get("type"),
        "body": [t["text"] for t in q["body"]],
        "equations": [e["latex"] for e in q.get("equations", [])],
        "choices": {
            c["label"]: " ".join(t["text"] for t in c["body"]) for c in q["choices"]
        },
        "figures": [f.get("topology", {}).get("description") for f in q.get("figures", [])],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("document_id")
    parser.add_argument("--job", default=None)
    args = parser.parse_args()
    seed(args.document_id, args.job)
