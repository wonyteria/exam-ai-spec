"""Line-OCR → question segmentation bridge (RESTORE-12).

PaddleOCR produces line-level Candidates with pixel bboxes; the
recognition stage consumes structured per-question items via
`extract_page`. This adapter runs the shared PaddleOCR engine over the
full page, orders lines by position, and segments them into question
blocks using Korean-exam anchors:

    question start   "12." / "12)" — 1–2 digits followed by a delimiter
    choice markers   ①–⑩ circled digits split choice text inline
    points           "[3점]" or "[3 점]"

Output is candidate-only: every item carries per-line provenance
(line_conf, line_bboxes) and nothing here is treated as final. Lines
before the first question anchor are page furniture (headers, titles)
and are excluded from question items but counted in meta.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Optional

from document.models import Candidate
from providers.ocr.paddle import PaddleOCRProvider  # noqa: PLC0415

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"
_QNUM = re.compile(r"^\s*(\d{1,2})\s*[.)\]．]")
_POINTS = re.compile(r"\[\s*(\d{1,2})\s*점")
_CIRCLED_SPLIT = re.compile(r"([①-⑩])")


class PaddlePageExtractor:
    name = "paddle-page"

    def __init__(
        self, ocr: Optional[Any] = None, model: str = "PP-OCRv5"
    ) -> None:
        # Shares the lazy PaddleOCR engine — one model load per process.
        self._ocr = ocr or PaddleOCRProvider()
        self.model = model

    def extract_page(self, image: Path) -> list[Candidate]:
        image = Path(image)
        lines = self._ocr.recognize_text(image)
        items, dropped = segment_questions(lines)
        input_sha = hashlib.sha256(image.read_bytes()).hexdigest()
        conf = min((it["line_conf"] for it in items), default=0.0)
        return [
            Candidate(
                provider=self.name,
                value=items,
                confidence=conf,
                meta={
                    "model": self.model,
                    "input_sha256": input_sha,
                    "input_uri": str(image),
                    "kind": "page_extraction",
                    "dropped_lines": dropped,
                },
            )
        ]

    def detect_regions(self, image: Path) -> list[Candidate]:
        # Region detection is PaddleLayoutProvider's job — the page
        # extractor only segments lines it already recognized.
        return []


def segment_questions(cands) -> tuple[list[dict], int]:
    """Group line-level OCR candidates into question item dicts.

    Returns (items, dropped_line_count). Items carry label/body/choices/
    points plus provenance — the same shape `_page_extractions` feeds to
    `_ingest_fields`.
    """
    lines = []
    for c in cands:
        text = str(c.value).strip()
        if not text:
            continue
        bbox = (c.meta or {}).get("bbox_px")
        lines.append({"text": text, "conf": c.confidence, "bbox": bbox})
    lines.sort(
        key=lambda l: (
            (l["bbox"] or [0, 0, 0, 0])[1],
            (l["bbox"] or [0, 0, 0, 0])[0],
        )
    )

    blocks: list[list[dict]] = []
    current: Optional[list[dict]] = None
    dropped = 0
    last_num = 0
    for ln in lines:
        m = _QNUM.match(ln["text"])
        if m:
            num = int(m.group(1))
            # forward-moving numbering only — "2025학년도" (4 digits) and
            # repeated/out-of-order numbers are not question anchors.
            if 0 < num <= 99 and num > last_num:
                last_num = num
                current = [ln]
                blocks.append(current)
                continue
        if current is None:
            dropped += 1
            continue
        current.append(ln)

    items = []
    for block in blocks:
        item = _block_to_item(block)
        if item is not None:
            items.append(item)
    return items, dropped


def _block_to_item(block: list[dict]) -> Optional[dict]:
    first = block[0]["text"]
    m = _QNUM.match(first)
    if not m:
        return None
    label = m.group(1)
    first_body = first[m.end():].strip()
    texts = [first_body] if first_body else []
    texts += [ln["text"] for ln in block[1:]]
    joined = "\n".join(texts)

    body_parts, choice_parts = [], []
    in_choices = False
    for t in texts:
        if any(ch in t for ch in CIRCLED):
            in_choices = True
        (choice_parts if in_choices else body_parts).append(t)
    body = "\n".join(body_parts).strip()

    choices: dict[str, str] = {}
    choice_text = " ".join(choice_parts)
    parts = _CIRCLED_SPLIT.split(choice_text)
    for i in range(1, len(parts) - 1, 2):
        mark, text = parts[i], parts[i + 1]
        choices.setdefault(mark, text.strip())

    pm = _POINTS.search(joined)
    item = {
        "label": label,
        "body": body or joined.strip(),
        "line_conf": min(ln["conf"] for ln in block),
        "line_bboxes": [ln["bbox"] for ln in block],
    }
    if choices:
        item["choices"] = choices
    if pm:
        item["points"] = int(pm.group(1))
    return item
