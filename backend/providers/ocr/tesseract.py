"""Tesseract OCR provider — engine-independent observer (no package needed).

Tesseract's LSTM engine is a different family from both the local VLM and
PaddleOCR, so its readings are genuinely independent evidence: agreement
with another engine can lift an ATU to AUTO_VERIFIED, disagreement is an
honest CONFLICT rather than a silent single-source guess.

Runs the system `tesseract` binary in TSV mode over a region crop and
groups word rows into line-level Candidates with `bbox_px` mapped back to
page coordinates — the same shape PaddleOCRProvider emits. Requires the
`kor` traineddata (``tesseract --list-langs``); local-only, nothing
leaves the machine.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import shutil
import subprocess
import warnings
from pathlib import Path
from typing import Optional

from document.models import BBox, Candidate

_TIMEOUT = float(os.environ.get("TESSERACT_TIMEOUT", "120"))


class TesseractOCRProvider:
    name = "tesseract-ocr"

    def __init__(
        self, binary: Optional[str] = None, langs: Optional[str] = None
    ) -> None:
        self.binary = binary or shutil.which("tesseract") or "tesseract"
        self.langs = langs or os.environ.get("TESSERACT_LANGS", "kor+eng")
        self.model = f"tesseract:{self.langs}"

    def recognize_text(
        self, image: Path, region: BBox | None = None
    ) -> list[Candidate]:
        image = Path(image)
        offset = (0.0, 0.0)
        if region is not None:
            image, offset = _crop(image, region)
        words = _tsv_words(self._run(image))
        input_sha = hashlib.sha256(image.read_bytes()).hexdigest()
        return [
            Candidate(
                provider=self.name,
                value=line["text"],
                confidence=line["conf"],
                model_version=self.model,
                meta={
                    "input_sha256": input_sha,
                    "input_uri": str(image),
                    "bbox_px": (
                        [
                            line["bbox"][0] + offset[0],
                            line["bbox"][1] + offset[1],
                            line["bbox"][2] + offset[0],
                            line["bbox"][3] + offset[1],
                        ]
                        if line["bbox"] else None
                    ),
                    "kind": "line",
                },
            )
            for line in _group_lines(words)
        ]

    def _run(self, image: Path) -> str:
        try:
            proc = subprocess.run(
                [self.binary, str(image), "stdout", "-l", self.langs, "tsv"],
                capture_output=True, timeout=_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            warnings.warn(f"tesseract OCR failed: {exc}")
            return ""
        if proc.returncode != 0:
            warnings.warn(
                "tesseract exited "
                f"{proc.returncode}: {proc.stderr.decode('utf-8', 'replace')[:200]}"
            )
            return ""
        return proc.stdout.decode("utf-8", "replace")


def _crop(image: Path, region: BBox) -> tuple[Path, tuple[float, float]]:
    """Crop to a temp file — never writes next to the source image."""
    import tempfile

    from PIL import Image

    with Image.open(image) as im:
        box = (
            int(region.x), int(region.y),
            int(region.x + region.w), int(region.y + region.h),
        )
        crop = im.crop(box)
        crop.load()  # crop() is lazy — materialize before the file closes
    fd, name = tempfile.mkstemp(suffix=".png", prefix="tess_crop_")
    os.close(fd)
    out = Path(name)
    crop.save(out)
    return out, (region.x, region.y)


def _tsv_words(tsv: str) -> list[dict]:
    words = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t"):
        if row.get("level") != "5":
            continue
        try:
            words.append({
                "text": (row.get("text") or "").strip(),
                "conf": float(row.get("conf") or 0) / 100.0,
                "key": (
                    row.get("page_num"), row.get("block_num"),
                    row.get("par_num"), row.get("line_num"),
                ),
                "box": (
                    int(row["left"]), int(row["top"]),
                    int(row["left"]) + int(row["width"]),
                    int(row["top"]) + int(row["height"]),
                ),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return words


def _group_lines(words: list[dict]) -> list[dict]:
    lines: dict[tuple, dict] = {}
    for w in words:
        line = lines.setdefault(w["key"], {"words": [], "confs": [], "bbox": None})
        if w["text"]:
            line["words"].append(w["text"])
            line["confs"].append(w["conf"])
        box = w["box"]
        line["bbox"] = (
            list(box) if line["bbox"] is None else [
                min(line["bbox"][0], box[0]), min(line["bbox"][1], box[1]),
                max(line["bbox"][2], box[2]), max(line["bbox"][3], box[3]),
            ]
        )
    return [
        {
            "text": " ".join(l["words"]),
            "conf": sum(l["confs"]) / len(l["confs"]) if l["confs"] else 0.0,
            "bbox": l["bbox"],
        }
        for l in lines.values()
    ]
