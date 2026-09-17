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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from PIL import Image  # noqa: E402

from document.models import BBox  # noqa: E402
from providers.gemini import provider as gp  # noqa: E402
from providers.gemini.provider import (  # noqa: E402
    _cache_key,
    _cache_put,
    _EXTRACT_PROMPT,
    _REGION_PROMPT,
    _SOLVE_PROMPT,
)
from core.examdna.recognition.segmenter import GAP, PAD  # noqa: E402

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


def seed(doc_id: str, overrides_path: Path | None) -> int:
    doc = json.loads((DATA / "documents" / f"{doc_id}.json").read_text(encoding="utf-8"))
    overrides = (
        json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path else {}
    )
    pages = doc["pages"]
    seeded = 0

    for page in pages:
        image = Path(page["clean_uri"] or page["original"]["uri"])
        w, h = page["width"], page["height"]

        page_qs = [
            q
            for q in doc["questions"]
            if q.get("source") and q["source"]["page"] == page["index"] and q["source"].get("bbox")
        ]
        extended = _extended_bboxes(page_qs, w, h)

        # detect_regions response for the whole page
        regions = [
            {
                "label": str(q.get("label") or q["number"]),
                **_norm_bbox(q["source"]["bbox"], w, h),
            }
            for q in page_qs
        ]
        key = _cache_key(
            "gemini-3.1-flash-lite",
            [_part(_image_bytes(image)), _REGION_PROMPT],
        )
        _cache_put(key, json.dumps(regions, ensure_ascii=False))
        seeded += 1

        for q in page_qs:
            src = q["source"]
            bbox = extended[id(q)]
            override = overrides.get(str(q["number"])) or {}
            extraction = override.get("extraction") or _question_to_extraction(q)
            if extraction:
                key = _cache_key(
                    "gemini-3.1-flash-lite",
                    [_part(_image_bytes(image, bbox)), _EXTRACT_PROMPT],
                )
                _cache_put(key, json.dumps(extraction, ensure_ascii=False))
                seeded += 1

            # solver response
            merged = _merged_question(q, override)
            problem = _problem_payload(merged)
            if problem is None:
                continue
            parent_id = q.get("parent_id") or _derive_parent_id(q, doc)
            if parent_id:
                parent = next(
                    (p for p in doc["questions"] if p["id"] == parent_id), None
                )
                if parent:
                    p_override = overrides.get(str(parent["number"])) or {}
                    p_merged = _merged_question(parent, p_override)
                    problem["shared_stem"] = {
                        "body": [t["text"] for t in p_merged["body"]],
                        "equations": [e["latex"] for e in p_merged.get("equations", [])],
                        "figures": [
                            f.get("topology", {}).get("description")
                            for f in p_merged.get("figures", [])
                        ],
                    }
            answer = override.get("answer") or (q.get("answer") or {}).get("value")
            steps = override.get("steps") or [
                s["text"] for s in (q.get("solution") or {}).get("steps", [])
            ]
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


def _extended_bboxes(page_qs: list[dict], w: float, h: float) -> dict[int, dict]:
    """Re-derive the pipeline's extended crop bbox for each stored question."""
    columns: dict[int, list[dict]] = {}
    for q in page_qs:
        b = q["source"]["bbox"]
        col = 1 if b["x"] + b["w"] / 2 > w / 2 else 0
        columns.setdefault(col, []).append(q)
    result: dict[int, dict] = {}
    for col_qs in columns.values():
        col_qs.sort(key=lambda q: q["source"]["bbox"]["y"])
        for i, q in enumerate(col_qs):
            b = dict(q["source"]["bbox"])
            if i + 1 < len(col_qs):
                bottom = col_qs[i + 1]["source"]["bbox"]["y"] - GAP
            else:
                bottom = min(h - GAP, b["y"] + b["h"] * 3)
            if bottom > b["y"] + b["h"]:
                b["h"] = bottom - b["y"]
            result[id(q)] = b
    return result


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


_SUBQ = re.compile(r"^(\d+)-(\d+)$")


def _derive_parent_id(q: dict, doc: dict) -> str | None:
    """Mirror consensus._link_subquestions for docs saved before linking."""
    m = _SUBQ.match(q.get("label") or "")
    if not m:
        return None
    group = m.group(1)
    candidates = [
        p
        for p in doc["questions"]
        if p["id"] != q["id"]
        and "-" not in (p.get("label") or "")
        and group in re.findall(r"\d+", p.get("label") or "")
    ]
    named = [p for p in candidates if not (p.get("label") or "").replace(" ", "").isdigit()]
    parent = named[0] if named else (candidates[0] if candidates else None)
    return parent["id"] if parent else None


def _merged_question(q: dict, override: dict) -> dict:
    """Apply a human-verified extraction override onto the stored question."""
    ext = override.get("extraction")
    if not ext:
        return q
    merged = dict(q)
    merged["body"] = [{"text": ext["body"]}] if ext.get("body") else []
    merged["choices"] = [
        {"label": label, "body": [{"text": text}]}
        for label, text in (ext.get("choices") or {}).items()
    ]
    merged["equations"] = [{"latex": e} for e in (ext.get("equations") or [])]
    merged["figures"] = (
        [{"topology": {"description": ext["figure"]}}] if ext.get("figure") else []
    )
    merged["type"] = ext.get("type") or q.get("type")
    return merged


def _problem_payload(q: dict) -> dict | None:
    """Reconstruct the exact problem dict solving._problem sends."""
    if not (q["body"] or q.get("equations") or q.get("figures")):
        return None
    return {
        "number": q.get("label") or q["number"],
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
    parser.add_argument(
        "--overrides",
        type=Path,
        default=None,
        help="human-verified extraction/answer overrides JSON",
    )
    args = parser.parse_args()
    seed(args.document_id, args.overrides)
