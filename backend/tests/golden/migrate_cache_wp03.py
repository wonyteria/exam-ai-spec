"""One-off fixture migration for the WP03 print-preservation guard.

The seeded golden cache was recorded while the trace mask could still
whiten print-dark pixels. WP03's S01 guard unmasks those pixels, so the
`trace_removed` bytes (and therefore every cache key bound to them)
change. This script:

1. Replays the pipeline with the guard disabled (old bytes) while logging
   every image-bearing provider call — each one hits the recorded cache.
2. Recomputes what each call's key would be under the new guard.
3. Copies the recorded response to the new key (documented fixture
   amendment — the cache is seeded regression data, not an oracle, see
   ADR-0006 and test_seeded_baseline).

Run:  python -m tests.golden.migrate_cache_wp03
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

import jobs.runner as runner
from core.examdna import Providers
from core.examdna.student_trace import separator
from document.models import Document
from jobs.models import Job
from jobs.runner import run_pipeline
from jobs.store import Store
from providers.gemini.provider import _EXTRACT_PROMPT, _PAGE_PROMPT, _REGION_PROMPT
from tests.golden.replay import CacheReplayProvider, _cache_key, _ReplayPart

SAMPLES = Path(__file__).resolve().parents[3] / "samples" / "golden_001"
CACHE = SAMPLES / "cache"
MODEL = "gemini-3.1-flash-lite"

_PROMPTS = {
    "extract_page": _PAGE_PROMPT,
    "detect_regions": _REGION_PROMPT,
    "recognize_text": _EXTRACT_PROMPT,
}


class _LoggingReplay(CacheReplayProvider):
    def __init__(self, cache_dir: Path, log: list):
        super().__init__(cache_dir, model=MODEL)
        self._call_log = log

    def extract_page(self, image):
        self._call_log.append(("extract_page", Path(image), None))
        return super().extract_page(image)

    def detect_regions(self, image):
        self._call_log.append(("detect_regions", Path(image), None))
        return super().detect_regions(image)

    def recognize_text(self, image, region=None):
        self._call_log.append(("recognize_text", Path(image), region))
        return super().recognize_text(image, region)


def _png_bytes(im: Image.Image, region=None) -> bytes:
    base = im.convert("RGB")
    if region is not None:
        base = base.crop(
            (int(region.x), int(region.y), int(region.x + region.w), int(region.y + region.h))
        )
    buf = io.BytesIO()
    base.save(buf, "PNG")
    return buf.getvalue()


def main() -> None:
    separator.PRESERVE_PRINT_OVERLAP = False  # reproduce pre-guard bytes
    call_log: list = []

    data_dir = Path(tempfile.mkdtemp())
    store = Store(data_dir)
    doc = Document()
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))
    uploads = store.job_dir(job.id) / "uploads"
    uploads.mkdir(parents=True)
    import shutil

    pages: dict[str, Path] = {}
    for img in sorted(SAMPLES.glob("page*.jpg")):
        shutil.copy(img, uploads / img.name)
        pages[img.stem] = img

    provider = _LoggingReplay(CACHE, call_log)
    runner.default_providers = lambda: Providers(
        ocr=[provider], vision=[provider], math_ocr=[],
        reasoning=[], solver=[provider],
    )
    run_pipeline(store, job.id)

    # old_clean[stem] = the trace_removed the run just produced; new_clean
    # recomputed with the guard's unmask applied.
    migrated = 0
    clean_by_path: dict[Path, tuple[np.ndarray, np.ndarray]] = {}
    work = store.job_dir(job.id) / "trace"
    for stem in pages:
        tr = work / f"{stem}_grayscale_trace_removed.png"
        old_clean = np.asarray(Image.open(tr).convert("L"), dtype=np.uint8)
        # recompute gray + masks exactly as separator.run does
        gray = np.asarray(
            Image.open(store.job_dir(job.id) / "variants" / f"{stem}_grayscale.png").convert("L"),
            dtype=np.uint8,
        )
        mask = separator._trace_mask(gray, uploads / f"{stem}.jpg")
        overlap = mask & (gray < separator.PRINT_MAX)
        new_clean = old_clean.copy()
        new_clean[overlap] = gray[overlap]
        clean_by_path[tr] = (old_clean, new_clean)

    for method, image_path, region in call_log:
        pair = clean_by_path.get(image_path)
        if pair is None:
            continue
        old_arr, new_arr = pair
        old_part = _png_bytes(Image.fromarray(old_arr), region)
        new_part = _png_bytes(Image.fromarray(new_arr), region)
        prompt = _PROMPTS[method]
        old_key = _cache_key(MODEL, [_ReplayPart(old_part), prompt])
        new_key = _cache_key(MODEL, [_ReplayPart(new_part), prompt])
        if old_key == new_key:
            continue
        src = CACHE / f"{old_key}.txt"
        dst = CACHE / f"{new_key}.txt"
        if src.exists() and not dst.exists():
            dst.write_bytes(src.read_bytes())
            migrated += 1
            print(f"alias {old_key[:12]}… -> {new_key[:12]}… ({method} {image_path.name})")

    (CACHE / "WP03_MIGRATION_NOTE.md").write_text(
        "# WP03 cache migration\n\n"
        "The S01 print-preservation guard changed `trace_removed` bytes, so\n"
        "image-bound cache keys changed. Recorded responses were aliased from\n"
        "the pre-guard key to the post-guard key for the same (page, region,\n"
        "prompt) call. Seeded regression data only — not an accuracy oracle.\n",
        encoding="utf-8",
    )
    print(f"migrated {migrated} cache aliases")


if __name__ == "__main__":
    main()
