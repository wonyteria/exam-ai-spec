# WP03 Report — 원본 업로드·페이지 순서·비파괴 전처리

Date: 2026-09-21
Commit base: WP02 `d57ee54`

## Scope delivered

### Source registration + manifest (`backend/canonical/`)

- `SourceAsset` — immutable uploaded blob: `sha256`, `mime`, `byte_size`,
  `original_name`, `blob_key`. Per-tenant content dedup
  (`UNIQUE(tenant_id, sha256)` + `find_source_asset` lookup skips
  re-storing identical bytes on retry/double-select).
- `SourcePage` — one logical exam page: `asset_id`, `pdf_page_index?`,
  `width_px`, `height_px`, `original_sha256`, `upload_index`.
  Upload order and exam order are modeled separately.
- `SourceManifest` — `page_ids_ordered`, `missing_page_expectation`,
  `confirmed_by`, `digest`. The digest covers order + expectation, so any
  reorder produces a different digest.
- `Revision.manifest_id` — every revision binds to a manifest;
  `content_hash` now covers the manifest digest (02 contract: source
  manifest is part of content_hash). `create_revision` inherits the
  parent's manifest when none is given; `apply`/`undo` carry it forward.
  Schema migration is additive (`ALTER TABLE` guarded by PRAGMA check).

### Upload validation (`backend/app/api/uploads.py`)

- Magic-byte sniffing (PNG/JPEG/BMP/WEBP/PDF) — declared Content-Type and
  extension are untrusted. Unknown types → 422 `UNSUPPORTED_TYPE`.
- Image validation via PIL `verify()` + reopen; corrupt files → 422
  `CORRUPT_FILE`. Pixel cap (80MP) → 422 `IMAGE_TOO_LARGE`; PIL's own
  decompression warning is superseded by the explicit cap.
- PDF validation via pypdfium2: unreadable → 422 `CORRUPT_FILE`;
  0 or >100 pages → 422 `PDF_PAGE_LIMIT`.
- All files validated **before** anything is stored — a bad file fails
  the whole request atomically.
- Initial page order = natural sort of original names
  (`page1, page2, page10`), stable by upload index.
- Creates the canonical document row, source assets/pages, initial
  (unconfirmed) manifest, `Document.pages` with full source linkage
  (`source_asset_id`, `source_page_id`, `pdf_page_index`, `sha256`,
  `original_name`), a manifest-bound RESTORE revision, and the durable
  job — unchanged response shape plus `manifest_id`.

### Non-destructive preprocessing (`backend/core/examdna/preprocessing.py`)

- EXIF orientation honored via `ImageOps.exif_transpose`; the applied
  correction is recorded on `page.transform` (`kind=exif_orientation`,
  axes_swapped, original dims) so source anchors in original pixels stay
  invertible (02 SourceAnchor/transform_id).
- PDF pages rasterized via pypdfium2 at 200dpi into the job workdir
  (original PDF bytes untouched); `kind=pdf_raster` transform recorded.
- Variants derived from the oriented/rasterized working image.

### Print-destruction guard (`backend/core/examdna/student_trace/separator.py`)

- S01: trace-mask pixels that overlap print-dark cores are **unmasked** —
  the eraser can no longer whiten printed strokes even when the
  classifier catches them (e.g. pencil fused to a printed rule).
- Overlapping components are recorded as `page.uncertain_regions`
  (bbox + pixel count + reason) for original comparison / human review
  instead of silent deletion.
- `PRESERVE_PRINT_OVERLAP` module flag reproduces pre-guard bytes — used
  only by the cache-migration script.

### API (`backend/app/api/v1.py`)

- `GET /tenants/{t}/documents/{d}/pages` — pages + active manifest
  (confirmed status, digest, expectation).
- `PUT /tenants/{t}/documents/{d}/pages/order` — confirm/reorder.
  If-Match CAS required (428/409); validates the id list is a permutation
  of the document's source pages (422 otherwise); creates a new manifest
  + new EDIT revision bound to it; audited.

### Frontend (`frontend/`)

- `lib/api.ts` — `getDocPages`, `confirmPageOrder` (If-Match fetched from
  the document head automatically).
- Review page — "페이지 순서" panel: ordered list with ↑/↓ reorder,
  PDF page labels, uncertain-region badges, confirm button, and
  확정됨/미확정 manifest status chip. Hidden when no manifest exists.

## Contract evidence (tests)

`backend/tests/test_wp03.py` — 12 tests, all green:

- Natural ordering: `page10, page1, page2` upload → manifest order
  `page1, page2, page10`; revision binds manifest_id.
- Duplicate filename + identical bytes → 2 source pages sharing 1 asset.
- Path-attack filename `../../etc/evil.png` → sanitized blob key.
- Corrupt image → 422 CORRUPT_FILE; text file → 422 UNSUPPORTED_TYPE.
- Two 2-page PDFs → 4 source pages with `pdf_page_index` 0,0,1,1;
  corrupt PDF → 422.
- Page-order confirm: missing If-Match → 428; reorder → new manifest
  (digest changed) + revision+1 bound to it, `confirmed_by` recorded;
  stale If-Match → 409; non-permutation → 422.
- EXIF orientation=6 image → dims swapped, `exif_orientation` transform
  recorded, original bytes untouched.
- PDF rasterization → per-page PNG + variants + `pdf_raster` transform;
  original PDF bytes untouched.
- S01: pencil ring fused to a printed rule — mask never covers
  print-dark pixels, line preserved in `trace_removed`,
  `uncertain_regions` populated.

## Golden cache migration (documented fixture amendment)

The guard changed `trace_removed` bytes, so image-bound cache keys in the
seeded `samples/golden_001/cache` missed. `tests/golden/migrate_cache_wp03.py`
replays the pipeline with the guard off (logging every image call), then
aliases each recorded response to the post-guard key for the same
(page, region, prompt). 5 aliases written + `WP03_MIGRATION_NOTE.md` in
the cache dir. The pre-guard mask was in fact erasing print pixels on the
sample — the fixture had silently encoded the defect.

## Dependency change

- `pypdfium2` (5.13.0) added for PDF page counting + rasterization —
  recorded here per ADR-0005's dependency-decision requirement.

## Verification

- `python -m pytest tests` — **64 passed** (52 prior + 12 new).
- `npx eslint` clean; `npm run build` clean.

## Known boundaries

- Perspective correction / crop transforms beyond EXIF are not yet
  implemented — the `page.transform` slot is in place and recorded
  transforms must keep anchor invertibility.
- The review page shows order confirmation but not yet page thumbnails;
  the full upload-queue UX is WP09.
