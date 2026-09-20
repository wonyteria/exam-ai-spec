"""One-off fixture migration for the RESTORE-04 six-class layer engine.

The seeded golden cache was recorded against `trace_removed` bytes from
the pre-RESTORE-04 mask (dilated pencil|color minus print cores). The
layer engine writes `restored_candidate` with the policy-filtered removal
mask, so image-bound cache keys change. This script:

1. Replays the pipeline under ``separator.LEGACY_REMOVAL`` — the restored
   file contains the exact bytes the cache was recorded against, so every
   image-bearing provider call hits the recorded cache and is logged.
2. Recomputes the post-RESTORE-04 restored image per page.
3. Aliases each recorded response to the new key (documented fixture
   amendment — the cache is seeded regression data, not an oracle, see
   ADR-0006 / WP03_MIGRATION_NOTE.md).

Run:  python -m tests.golden.migrate_cache_restore04
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

import jobs.runner as runner
from core.examdna import Providers
from core.examdna.student_trace import separator
from core.examdna.student_trace.layers import classify_layers, load_rgb
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
    separator.LEGACY_REMOVAL = True   # restored file = pre-RESTORE-04 bytes
    call_log: list = []

    data_dir = Path(tempfile.mkdtemp())
    store = Store(data_dir)
    doc = Document()
    store.save_document(doc)
    job = store.create_job(Job(document_id=doc.id))
    uploads = store.job_dir(job.id) / "uploads"
    uploads.mkdir(parents=True)

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

    # old_clean = the bytes the cache knows (the file the legacy run just
    # wrote); new_clean = recomputed under the six-class removal policy.
    migrated = 0
    clean_by_path: dict[Path, tuple[np.ndarray, np.ndarray]] = {}
    work = store.job_dir(job.id) / "trace"
    variants = store.job_dir(job.id) / "variants"
    for stem in pages:
        tr = work / f"{stem}_grayscale_restored_candidate.png"
        if not tr.exists():
            continue
        old_clean = np.asarray(Image.open(tr).convert("L"), dtype=np.uint8)
        gray = np.asarray(
            Image.open(variants / f"{stem}_grayscale.png").convert("L"),
            dtype=np.uint8,
        )
        rgb = load_rgb(uploads / f"{stem}.jpg", gray.shape)
        evidence = classify_layers(gray, rgb)
        new_clean = gray.copy()
        new_clean[evidence.removal_mask] = 255
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

    (CACHE / "RESTORE04_MIGRATION_NOTE.md").write_text(
        "# RESTORE-04 cache migration\n\n"
        "The six-class layer engine changed restored-page bytes (policy-\n"
        "filtered removal mask instead of the dilated trace mask), so\n"
        "image-bound cache keys changed. Recorded responses were aliased\n"
        "from the legacy key to the RESTORE-04 key for the same (page,\n"
        "region, prompt) call. Seeded regression data only — not an\n"
        "accuracy oracle.\n",
        encoding="utf-8",
    )
    print(f"migrated {migrated} cache aliases")


if __name__ == "__main__":
    main()
