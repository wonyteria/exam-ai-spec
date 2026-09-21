"""Local EasyOCR adapter — second independent observer (RESTORE-10C).

EasyOCR (Apache-2.0) is a genuinely independent OCR stack: CRAFT text
detection + its own CRNN recognizer on torch — a different engine family
from PaddleOCR, so agreement between the two is real cross-verification
evidence, not the same model twice.

Candidate-only, opt-in via EXAMDNA_EASYOCR=1, no network calls after the
one-time model download. Lazy engine load keeps tests fast.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from document.models import BBox, Candidate

DEFAULT_LANGS = ["ko", "en"]


class EasyOCRUnavailable(RuntimeError):
    """Engine or dependency missing — an explicit capability gap."""


class EasyOCRProvider:
    name = "easyocr"

    def __init__(
        self,
        langs: Optional[list[str]] = None,
        engine: Optional[Any] = None,
    ) -> None:
        self.langs = langs or DEFAULT_LANGS
        self._engine = engine
        self.model = "easyocr-" + "+".join(self.langs)

    def _load(self):
        if self._engine is not None:
            return self._engine
        try:
            import easyocr  # noqa: PLC0415
        except ImportError as exc:
            raise EasyOCRUnavailable(
                "easyocr not installed — install easyocr or run without "
                "EXAMDNA_EASYOCR"
            ) from exc
        self._engine = easyocr.Reader(self.langs, gpu=False, verbose=False)
        return self._engine

    def recognize_text(
        self, image: Path, region: BBox | None = None
    ) -> list[Candidate]:
        engine = self._load()
        import time

        import numpy as np
        from PIL import Image

        input_sha = hashlib.sha256(Path(image).read_bytes()).hexdigest()
        crop_offset = (0.0, 0.0)
        with Image.open(image) as im:
            if region is not None:
                box = (
                    int(region.x),
                    int(region.y),
                    int(region.x + region.w),
                    int(region.y + region.h),
                )
                im = im.crop(box)
                crop_offset = (region.x, region.y)
            # Pass an ndarray, not a path — cv2.imread inside easyocr
            # cannot read non-ASCII (e.g. Korean) absolute paths.
            arr = np.asarray(im.convert("RGB"))
        img_path = str(image)
        results = engine.readtext(arr)
        out = []
        for poly, text, score in results or []:
            bbox = _poly_bbox(poly)
            if bbox is not None:
                dx, dy = crop_offset
                bbox = [bbox[0] + dx, bbox[1] + dy, bbox[2] + dx, bbox[3] + dy]
            out.append(
                Candidate(
                    provider=self.name,
                    value=text,
                    confidence=float(score),
                    model_version=self.model,
                    bbox_original=(
                        BBox(x=bbox[0], y=bbox[1], w=bbox[2] - bbox[0], h=bbox[3] - bbox[1])
                        if bbox is not None
                        else None
                    ),
                    raw_output_sha256=input_sha,
                    timestamp=time.time(),
                    meta={
                        "model": self.model,
                        "input_sha256": input_sha,
                        "input_uri": img_path,
                        "bbox_px": bbox,
                        "kind": "ocr_line",
                    },
                )
            )
        return out


def _poly_bbox(poly) -> Optional[list[float]]:
    if not poly:
        return None
    try:
        pts = [[float(p[0]), float(p[1])] for p in poly]
    except (TypeError, IndexError, KeyError):
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]
