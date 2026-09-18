from __future__ import annotations

import hashlib
import io
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PDF_2PAGE = (
    b"%PDF-1.4\n"
    b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj\n"
    b"4 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj\n"
    b"trailer << /Root 1 0 R >>\n%%EOF"
)


def _png(w=32, h=32, color="white", exif_orientation=None) -> bytes:
    buf = io.BytesIO()
    im = Image.new("RGB", (w, h), color)
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[274] = exif_orientation
        im.save(buf, "PNG", exif=exif)
    else:
        im.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXAMDNA_DATA", str(tmp_path / "data"))
    import app.deps as deps

    deps.reset()
    import app.api.uploads as uploads_api

    monkeypatch.setattr(uploads_api, "run_once", lambda *a, **k: False)
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c, deps
    deps.reset()


def _setup(c):
    h = {"X-Dev-User": "u1"}
    c.post("/api/auth/dev-login", json={"user_id": "u1", "name": "Alice"})
    r = c.post("/api/tenants", json={"name": "Academy"}, headers=h)
    return h, r.json()["id"]


def _upload(c, h, files):
    return c.post(
        "/api/uploads",
        headers=h,
        files=[("files", (n, b, m)) for n, b, m in files],
    )


# --- ordering / manifest ----------------------------------------------------------


def test_natural_page_order_and_manifest(env):
    c, deps = env
    h, tid = _setup(c)
    r = _upload(
        c,
        h,
        [
            ("page10.png", _png(), "image/png"),
            ("page1.png", _png(), "image/png"),
            ("page2.png", _png(), "image/png"),
        ],
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()["document_id"]

    pages = c.get(f"/api/v1/tenants/{tid}/documents/{doc_id}/pages", headers=h)
    assert pages.status_code == 200
    data = pages.json()["data"]
    names = [p["original_name"] for p in data["pages"]]
    assert names == ["page1.png", "page2.png", "page10.png"]
    assert data["manifest"]["confirmed_by"] is None
    assert len(data["manifest"]["page_ids_ordered"]) == 3
    # revision binds the manifest
    revs = c.get(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/revisions", headers=h
    ).json()["data"]["revisions"]
    assert revs[-1]["manifest_id"] == data["manifest"]["id"]


def test_duplicate_filename_and_dedup(env):
    c, deps = env
    h, tid = _setup(c)
    same = _png(40, 40, "gray")
    r = _upload(
        c,
        h,
        [
            ("page1.png", same, "image/png"),
            ("page1.png", same, "image/png"),  # duplicate name + bytes
        ],
    )
    assert r.status_code == 200, r.text
    cstore = deps.get_canonical()
    doc_id = r.json()["document_id"]
    pages = cstore.list_source_pages(doc_id)
    assert len(pages) == 2  # two pages, one asset
    assert pages[0].asset_id == pages[1].asset_id
    assert pages[0].original_sha256 == hashlib.sha256(same).hexdigest()


def test_path_attack_filename_sanitized(env):
    c, deps = env
    h, tid = _setup(c)
    r = _upload(
        c,
        h,
        [("../../etc/evil.png", _png(), "image/png")],
    )
    assert r.status_code == 200, r.text
    cstore = deps.get_canonical()
    doc_id = r.json()["document_id"]
    pages = cstore.list_source_pages(doc_id)
    assert len(pages) == 1
    asset = cstore.get_source_asset(pages[0].asset_id)
    assert ".." not in asset.blob_key
    assert asset.blob_key.endswith("evil.png")


# --- validation -----------------------------------------------------------------


def test_reject_corrupt_image(env):
    c, deps = env
    h, tid = _setup(c)
    r = _upload(c, h, [("bad.png", b"\x89PNG\r\n\x1a\n" + b"garbage", "image/png")])
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["code"] == "CORRUPT_FILE"


def test_reject_unsupported_type(env):
    c, deps = env
    h, tid = _setup(c)
    r = _upload(c, h, [("notes.txt", b"hello world", "text/plain")])
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["code"] == "UNSUPPORTED_TYPE"


def test_multi_pdf_pages(env):
    c, deps = env
    h, tid = _setup(c)
    r = _upload(
        c,
        h,
        [
            ("exam_a.pdf", PDF_2PAGE, "application/pdf"),
            ("exam_b.pdf", PDF_2PAGE, "application/pdf"),
        ],
    )
    assert r.status_code == 200, r.text
    cstore = deps.get_canonical()
    pages = cstore.list_source_pages(r.json()["document_id"])
    assert len(pages) == 4
    assert sorted(p.pdf_page_index for p in pages) == [0, 0, 1, 1]


def test_corrupt_pdf_rejected(env):
    c, deps = env
    h, tid = _setup(c)
    r = _upload(c, h, [("bad.pdf", b"%PDF-1.4 garbage", "application/pdf")])
    assert r.status_code == 422


# --- page order confirmation -------------------------------------------------------


def test_page_order_confirm_creates_new_manifest_and_revision(env):
    c, deps = env
    h, tid = _setup(c)
    r = _upload(
        c,
        h,
        [("p1.png", _png(), "image/png"), ("p2.png", _png(48, 48), "image/png")],
    )
    doc_id = r.json()["document_id"]
    cstore = deps.get_canonical()

    pages_data = c.get(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/pages", headers=h
    ).json()["data"]
    order = pages_data["manifest"]["page_ids_ordered"]
    head = cstore.get_head_revision(doc_id)

    # missing If-Match -> 428
    r2 = c.put(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/pages/order",
        headers=h,
        json={"page_ids_ordered": order},
    )
    assert r2.status_code == 428

    # reversed order -> new manifest + new revision
    rev_order = list(reversed(order))
    r3 = c.put(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/pages/order",
        headers={**h, "If-Match": head.id},
        json={"page_ids_ordered": rev_order},
    )
    assert r3.status_code == 200, r3.text
    data = r3.json()["data"]
    assert data["manifest"]["page_ids_ordered"] == rev_order
    assert data["manifest"]["digest"] != pages_data["manifest"]["digest"]
    assert data["manifest"]["confirmed_by"] == "u1"
    assert data["revision"]["manifest_id"] == data["manifest"]["id"]
    assert data["revision"]["revision_no"] == head.revision_no + 1

    # stale If-Match now -> 409
    r4 = c.put(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/pages/order",
        headers={**h, "If-Match": head.id},
        json={"page_ids_ordered": order},
    )
    assert r4.status_code == 409


def test_page_order_rejects_non_permutation(env):
    c, deps = env
    h, tid = _setup(c)
    r = _upload(c, h, [("p1.png", _png(), "image/png")])
    doc_id = r.json()["document_id"]
    head = deps.get_canonical().get_head_revision(doc_id)
    r2 = c.put(
        f"/api/v1/tenants/{tid}/documents/{doc_id}/pages/order",
        headers={**h, "If-Match": head.id},
        json={"page_ids_ordered": ["spage_nope"]},
    )
    assert r2.status_code == 422


# --- preprocessing / trace guard ---------------------------------------------------


def _ctx(doc, workdir: Path, store=None):
    from core.examdna.context import PipelineContext, Providers
    from jobs.models import Job

    return PipelineContext(
        document=doc,
        job=Job(id="job_t", document_id=doc.id),
        store=store,
        workdir=workdir,
        providers=Providers(),
        event_sink=lambda *a: None,
    )


def test_exif_orientation_transform(tmp_path):
    from core.examdna import preprocessing
    from document.models import Document, Page, PageImage

    src = tmp_path / "rot.png"
    src.write_bytes(_png(100, 50, exif_orientation=6))  # rotate 90 -> 50x100
    doc = Document(tenant_id="t")
    doc.pages.append(Page(index=0, original=PageImage(uri=str(src))))
    ctx = _ctx(doc, tmp_path / "work")

    preprocessing.run(ctx)
    page = doc.pages[0]
    assert (page.width, page.height) == (50, 100)
    assert page.transform["kind"] == "exif_orientation"
    assert page.transform["axes_swapped"] is True
    # original bytes untouched
    assert src.read_bytes() == _png(100, 50, exif_orientation=6)


def test_pdf_rasterization_in_preprocessing(tmp_path):
    pytest.importorskip("pypdfium2")
    from core.examdna import preprocessing
    from document.models import Document, Page, PageImage

    src = tmp_path / "exam.pdf"
    src.write_bytes(PDF_2PAGE)
    doc = Document(tenant_id="t")
    doc.pages.append(
        Page(index=0, original=PageImage(uri=str(src)), pdf_page_index=0)
    )
    doc.pages.append(
        Page(index=1, original=PageImage(uri=str(src)), pdf_page_index=1)
    )
    ctx = _ctx(doc, tmp_path / "work")

    preprocessing.run(ctx)
    for p in doc.pages:
        assert p.transform["kind"] == "pdf_raster"
        assert "grayscale" in p.original.variants
        assert Path(p.original.variants["raster"]).exists()
        assert (p.width, p.height) == (1700.0, 2200.0)
    assert src.read_bytes() == PDF_2PAGE  # original untouched


def test_print_line_not_destroyed(tmp_path):
    import numpy as np
    from core.examdna.student_trace import separator
    from document.models import Document, Page, PageImage

    # Synthetic page: dark print line + a pencil-gray circle overlapping it.
    gray = np.full((200, 400), 200, dtype=np.uint8)
    gray[95:105, 20:380] = 20  # printed rule
    yy, xx = np.mgrid[0:200, 0:400]
    circle = ((yy - 100) ** 2 + (xx - 200) ** 2) < 60**2
    ring = circle & (((yy - 100) ** 2 + (xx - 200) ** 2) > 55**2)
    gray[ring] = 80  # dark pencil stroke crossing the print line

    src = tmp_path / "page.png"
    Image.fromarray(gray).save(src)
    variants = tmp_path / "variants"
    variants.mkdir()
    gray_path = variants / "page_grayscale.png"
    Image.fromarray(gray).save(gray_path)

    doc = Document(tenant_id="t")
    page = Page(
        index=0,
        original=PageImage(
            uri=str(src), variants={"grayscale": str(gray_path)}
        ),
    )
    doc.pages.append(page)
    ctx = _ctx(doc, tmp_path / "work")
    separator.run(ctx)

    removed = np.asarray(
        Image.open(page.original.variants["trace_removed"]), dtype=np.uint8
    )
    # print-line pixels away from the ring crossings must NOT be whitened
    assert (removed[100, 40:120] == 20).all()
    assert (removed[100, 280:360] == 20).all()
    # the mask itself must never cover print-dark pixels (S01)
    mask_img = np.asarray(Image.open(page.trace_mask_uri), dtype=np.uint8) > 0
    assert not mask_img[gray < 55].any()
    assert page.uncertain_regions  # overlap recorded for original comparison
