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
_QSUB = re.compile(r"^\s*(\d{1,2})\s*-\s*(\d{1,2})\s*[.)\]．]")
_QDESC = re.compile(r"^\s*논술형\s*(\d{1,2})\s*[.)\]．]?")
# Ambiguous anchors — a question number occluded by grading marks can
# surface as a bare digit line, a backward number, or a circled number
# read as 'O'/'Q'/'0'. These open a block so the question is not lost,
# but carry `anchor_ambiguous` — the number is never trusted silently.
_QBARE = re.compile(r"^\s*(\d{1,2})\s*$")
_QCIRCLED = re.compile(r"^\s*[O0Q][^\d\s.)\]．]")
_BODYISH = re.compile(r"[가-힣]|\[\s*\d+\s*점")
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
        _normalize_bboxes(items, image)
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

    blocks: list[list[dict]] = []
    dropped = 0
    for column in _column_order(lines):
        dropped += _blocks_from_column(column, blocks)

    items = []
    seen: set[str] = set()
    for block in blocks:
        item = _block_to_item(block)
        if item is not None:
            label = item["label"]
            if label in seen:
                suffix = 2
                while f"{label}·{suffix}" in seen:
                    suffix += 1
                item["label"] = f"{label}·{suffix}"
            seen.add(item["label"])
            items.append(item)
    return items, dropped


def _column_order(lines: list[dict]) -> list[list[dict]]:
    """Reading order for multi-column exam pages.

    Korean exam sheets are 2-column: numbering ascends down the left
    column, then down the right. A page is split only when a real ink
    gutter exists — an x-range no line crosses inside the page's middle
    half, with material line count on both sides. Anything ambiguous
    (single column, one side too thin, no clean gutter) stays one column
    rather than risking a wrong split.
    """
    def by_pos(l):
        b = l["bbox"] or [0, 0, 0, 0]
        return (b[1], b[0])

    bounded = [l for l in lines if l["bbox"]]
    if len(bounded) < 10:
        return [sorted(lines, key=by_pos)]

    x_min = min(l["bbox"][0] for l in bounded)
    x_max = max(l["bbox"][2] for l in bounded)
    span = x_max - x_min
    if span <= 0:
        return [sorted(lines, key=by_pos)]

    # Column split by line-center clustering. Photographed sheets skew,
    # so text lines cross a vertical gutter — coverage-based gutter
    # detection fails. Line *centers* still cluster into two x-bands:
    # find the widest gap between consecutive centers in the middle
    # band; require both sides to carry real line volume.
    # Wide furniture lines (headers/rules spanning the gutter) sit in
    # the middle and destroy the bimodal structure — exclude them from
    # gap detection; they're still assigned to a column below.
    narrow = [l for l in bounded if l["bbox"][2] - l["bbox"][0] < span * 0.6]
    if len(narrow) < 8:
        return [sorted(lines, key=by_pos)]
    centers = sorted((l["bbox"][0] + l["bbox"][2]) / 2 for l in narrow)
    lo, hi = x_min + span * 0.3, x_min + span * 0.7
    best_gap, best_mid = 0.0, None
    for a, b in zip(centers, centers[1:]):
        mid = (a + b) / 2
        if lo <= mid <= hi and b - a > best_gap:
            best_gap, best_mid = b - a, mid
    if best_mid is None or best_gap < span * 0.05:
        return [sorted(lines, key=by_pos)]

    left = [l for l in bounded if (l["bbox"][0] + l["bbox"][2]) / 2 < best_mid]
    right = [l for l in bounded if (l["bbox"][0] + l["bbox"][2]) / 2 >= best_mid]
    if len(left) < 4 or len(right) < 4:
        return [sorted(lines, key=by_pos)]
    # Guard against splitting a single-column page on a stray indent:
    # the right cluster must genuinely start on the right half.
    if min(l["bbox"][0] for l in right) < x_min + span * 0.3:
        return [sorted(lines, key=by_pos)]
    unbounded = [l for l in lines if not l["bbox"]]
    left.extend(unbounded)
    return [sorted(left, key=by_pos), sorted(right, key=by_pos)]


def _anchor(text: str, last_num: int) -> Optional[tuple[str, int]]:
    """Question-start anchor → (label, main number) or None.

    Three forms: numbered "12.", sub-question "2-1.", descriptive group
    header "논술형 2.". Sub-questions and group headers are always valid
    anchors (their numbering is scoped); main numbers must move forward.
    """
    m = _QSUB.match(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}", int(m.group(1))
    m = _QDESC.match(text)
    if m:
        return f"논술{m.group(1)}", int(m.group(1))
    m = _QNUM.match(text)
    if m:
        num = int(m.group(1))
        # forward-moving numbering only — "2025학년도" (4 digits) and
        # repeated/out-of-order numbers are not question anchors.
        if 0 < num <= 99 and num > last_num:
            return m.group(1), num
    return None


def _blocks_from_column(lines: list[dict], blocks: list[list[dict]]) -> int:
    current: Optional[list[dict]] = None
    dropped = 0
    last_num = 0
    left_edge = min((l["bbox"][0] for l in lines if l["bbox"]), default=0.0)
    ambiguous = 0
    for i, ln in enumerate(lines):
        anchor = _anchor(ln["text"], last_num)
        if anchor is not None:
            label, num = anchor
            if not _QSUB.match(ln["text"]) and not _QDESC.match(ln["text"]):
                last_num = num
            current = [ln]
            blocks.append(current)
            ln["label"] = label
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if _ambiguous_anchor(ln, nxt, left_edge):
            ambiguous += 1
            observed = (
                _QNUM.match(ln["text"]) or _QBARE.match(ln["text"])
            )
            label = (
                f"?{observed.group(1)}" if observed else f"?mark{ambiguous}"
            )
            current = [ln]
            blocks.append(current)
            ln["label"] = label
            ln["anchor_ambiguous"] = True
            continue
        if current is None:
            dropped += 1
            continue
        current.append(ln)
    return dropped


def _ambiguous_anchor(ln: dict, nxt: Optional[dict], left_edge: float) -> bool:
    """Occluded-number heuristics — a question whose printed number was
    fused with a grading circle. Only fires at the column's left edge
    (question anchors are never indented deep), and never silently
    assigns a real number.

    Guards against look-alikes: a detached bare digit or an 'O'-fused
    number is only an anchor when the *next* line is body-like (hangul
    or a points tag) — choice values and lone grading marks are not.
    """
    text = ln["text"]
    b = ln["bbox"]
    if b is None or b[0] > left_edge + 40:
        return False
    if _QNUM.match(text):  # backward/duplicate number, e.g. 16 read as 6
        return True
    if _QBARE.match(text):
        return bool(nxt) and bool(_BODYISH.search(nxt["text"]))
    if _QCIRCLED.match(text):
        # 'O' fused to text with no delimiter; require real body content
        # on the line itself — a lone 'O' grading mark is not an anchor.
        return len(text) >= 8 and bool(_BODYISH.search(text))
    return False


def _normalize_bboxes(items: list[dict], image: Path) -> None:
    """Attach each item's union bbox in the 1000-grid form the segmenter
    consumes ({xmin,ymin,xmax,ymax}/1000 of the page)."""
    try:
        from PIL import Image

        with Image.open(image) as im:
            w, h = im.size
    except Exception:  # noqa: BLE001
        return
    if not w or not h:
        return
    for item in items:
        boxes = [b for b in item.get("line_bboxes", []) if b]
        if not boxes:
            continue
        item["bbox"] = {
            "xmin": min(b[0] for b in boxes) / w * 1000,
            "ymin": min(b[1] for b in boxes) / h * 1000,
            "xmax": max(b[2] for b in boxes) / w * 1000,
            "ymax": max(b[3] for b in boxes) / h * 1000,
        }


def _block_to_item(block: list[dict]) -> Optional[dict]:
    first = block[0]["text"]
    label = block[0].get("label")
    m = _QSUB.match(first) or _QDESC.match(first) or _QNUM.match(first)
    if label is None:
        if not m:
            return None
        if _QSUB.match(first):
            label = f"{m.group(1)}-{m.group(2)}"
        elif _QDESC.match(first):
            label = f"논술{m.group(1)}"
        else:
            label = m.group(1)
    if m is None:
        # Ambiguous anchor (occluded number): only a bare-digit line is
        # stripped; a circled-number line keeps its text verbatim so the
        # body retains exactly what OCR saw.
        if _QBARE.match(first):
            first_body = first[_QBARE.match(first).end():].strip()
        else:
            first_body = first.strip()
    else:
        first_body = first[m.end():].strip()
    if not first_body and len(block) == 1:
        return None  # bare stray digit, no content — not a question
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
