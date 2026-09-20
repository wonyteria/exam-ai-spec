"""Local PP-Structure layout adapter — region/layout candidates only.

Lazy engine load; detection results become Candidates carrying the raw
layout label and pixel bbox. Mapping layout blocks to questions is the
segmenter's job (RESTORE-03) — this adapter never assigns semantics.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from document.models import BBox, Candidate
from providers.ocr.paddle import PaddleOCRUnavailable  # noqa: F401


class PaddleLayoutProvider:
    name = "paddle-structure"

    def __init__(self, model: str = "PP-StructureV3", engine: Optional[Any] = None):
        self.model = model
        self._engine = engine

    def _load(self):
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PPStructureV3  # noqa: PLC0415
        except ImportError as exc:
            raise PaddleOCRUnavailable(
                "paddleocr PP-StructureV3 not installed"
            ) from exc
        self._engine = PPStructureV3()
        return self._engine

    # -- VisionProvider protocol ------------------------------------------------

    def detect_regions(self, image: Path) -> list[Candidate]:
        engine = self._load()
        input_sha = hashlib.sha256(Path(image).read_bytes()).hexdigest()
        result = _run(engine, str(image))
        out = []
        for item in _normalize_layout(result):
            out.append(
                Candidate(
                    provider=self.name,
                    value={
                        "label": item["label"],
                        "bbox": item["bbox"],
                    },
                    confidence=item["score"],
                    meta={
                        "model": self.model,
                        "input_sha256": input_sha,
                        "layout_label": item["label"],
                    },
                )
            )
        return out

    def describe(self, image: Path, region: BBox | None = None) -> list[Candidate]:
        return []  # layout adapter does not caption


def _run(engine, img_path: str):
    if hasattr(engine, "predict"):
        return engine.predict(img_path)
    return engine(img_path)


def _normalize_layout(result) -> list[dict]:
    """PP-Structure predict() -> list of dicts with 'layout_detections'
    or 'parsing_res_list' depending on version; flatten to
    [{label, bbox(x0,y0,x1,y1 px), score}]."""
    items: list[dict] = []
    if result is None:
        return items
    pages = result if isinstance(result, list) else [result]
    for res in pages:
        if not isinstance(res, dict):
            continue
        blocks = res.get("layout_detections") or []
        if not blocks and isinstance(res.get("overall_ocr_res"), dict):
            blocks = res["overall_ocr_res"].get("rec_boxes") or []
        for b in blocks:
            if isinstance(b, dict):
                label = b.get("label") or b.get("type") or "unknown"
                box = b.get("bbox") or b.get("coordinate")
                score = float(b.get("score", 0.0))
            else:
                continue
            if box:
                items.append(
                    {"label": str(label), "bbox": [float(v) for v in box[:4]], "score": score}
                )
    return items
