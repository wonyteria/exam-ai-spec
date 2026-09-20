"""Local PaddleOCR adapter — candidate-only, opt-in, no network calls.

The engine is lazy-loaded on first use so importing this module never
pulls model weights or native deps into the test/unit path. Output is
always `Candidate`s carrying provenance (model, input hash, detected
bbox) — never final values (RESTORE-02).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from document.models import BBox, Candidate

DEFAULT_MODEL = "PP-OCRv5"
DEFAULT_LANG = "korean"


class PaddleOCRUnavailable(RuntimeError):
    """Engine or dependency missing — callers must treat this as an
    explicit capability gap, never degrade silently."""


class PaddleOCRProvider:
    name = "paddleocr"

    def __init__(
        self,
        lang: str = DEFAULT_LANG,
        model: str = DEFAULT_MODEL,
        engine: Optional[Any] = None,
    ) -> None:
        self.lang = lang
        self.model = model
        self._engine = engine

    # -- engine ---------------------------------------------------------------

    def _load(self):
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR  # noqa: PLC0415
        except ImportError as exc:
            raise PaddleOCRUnavailable(
                "paddleocr not installed — install paddlepaddle+paddleocr "
                "or run without EXAMDNA_PADDLEOCR"
            ) from exc
        self._engine = PaddleOCR(lang=self.lang)
        return self._engine

    # -- OCRProvider protocol ---------------------------------------------------

    def recognize_text(
        self, image: Path, region: BBox | None = None
    ) -> list[Candidate]:
        engine = self._load()
        img_path = str(image)
        crop_offset = (0.0, 0.0)
        if region is not None:
            img_path, crop_offset = _crop(image, region)
        result = _run_engine(engine, img_path)
        input_sha = hashlib.sha256(Path(img_path).read_bytes()).hexdigest()
        return [
            _to_candidate(
                item,
                provider=self.name,
                model=self.model,
                input_sha256=input_sha,
                input_uri=img_path,
                crop_offset=crop_offset,
                region=region,
            )
            for item in _normalize(result)
        ]


# -- internals ---------------------------------------------------------------


def _crop(image: Path, region: BBox) -> tuple[str, tuple[float, float]]:
    """Crop the region into a temp file next to the image; returns
    (path, (dx, dy)) so detected boxes can be mapped back."""
    from PIL import Image

    with Image.open(image) as im:
        box = (
            int(region.x),
            int(region.y),
            int(region.x + region.w),
            int(region.y + region.h),
        )
        cropped = im.crop(box)
        out = image.with_name(f"{image.stem}__r{int(region.x)}_{int(region.y)}.png")
        cropped.save(out)
    return str(out), (region.x, region.y)


def _run_engine(engine, img_path: str):
    """Support both PaddleOCR APIs: predict() (3.x) and ocr() (2.x)."""
    if hasattr(engine, "predict"):
        return engine.predict(img_path)
    return engine.ocr(img_path)


def _normalize(result) -> list[dict]:
    """Flatten engine output to [{text, score, poly}] dicts.

    3.x predict() -> list[{'rec_texts': [...], 'rec_scores': [...],
    'rec_polys'/'dt_polys': [...]}]
    2.x ocr() -> [[ [box], (text, score) ], ...]
    """
    items: list[dict] = []
    if result is None:
        return items
    pages = result if isinstance(result, list) else [result]
    for res in pages:
        if isinstance(res, dict):
            texts = res.get("rec_texts") or []
            scores = res.get("rec_scores") or []
            polys = res.get("rec_polys", res.get("dt_polys")) or []
            for i, text in enumerate(texts):
                items.append(
                    {
                        "text": text,
                        "score": float(scores[i]) if i < len(scores) else 0.0,
                        "poly": list(polys[i]) if i < len(polys) else None,
                    }
                )
        elif isinstance(res, (list, tuple)):
            # 2.x: res is a list of [box, (text, score)]
            for entry in res:
                if (
                    isinstance(entry, (list, tuple))
                    and len(entry) == 2
                    and isinstance(entry[1], (list, tuple))
                    and len(entry[1]) == 2
                ):
                    items.append(
                        {
                            "text": entry[1][0],
                            "score": float(entry[1][1]),
                            "poly": entry[0],
                        }
                    )
    return items


def _poly_bbox(poly) -> Optional[list[float]]:
    """polygon points -> [x0, y0, x1, y1]."""
    if not poly:
        return None
    try:
        pts = [[float(p[0]), float(p[1])] for p in poly]
    except (TypeError, IndexError, KeyError):
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def _to_candidate(
    item: dict,
    provider: str,
    model: str,
    input_sha256: str,
    input_uri: str,
    crop_offset: tuple[float, float],
    region: BBox | None,
) -> Candidate:
    bbox = _poly_bbox(item.get("poly"))
    if bbox is not None:
        dx, dy = crop_offset
        bbox = [bbox[0] + dx, bbox[1] + dy, bbox[2] + dx, bbox[3] + dy]
    return Candidate(
        provider=provider,
        value=item["text"],
        confidence=item["score"],
        meta={
            "model": model,
            "input_sha256": input_sha256,
            "input_uri": input_uri,
            "bbox_px": bbox,
            "region": (
                {"x": region.x, "y": region.y, "w": region.w, "h": region.h}
                if region is not None
                else None
            ),
            "kind": "ocr_line",
        },
    )
