"""Deterministic, *valid* PDF fixtures for tests.

The previous hand-written byte strings omitted the xref table and
startxref, so strict parsers (newer pypdfium builds, Ghostscript) rejected
them and tests failed depending on the installed pdfium version. These
builders emit real xref/startxref so every PDF parser accepts them.
"""
from __future__ import annotations

import io


def make_pdf(page_count: int = 2) -> bytes:
    """A blank-page PDF with a correct xref table — deterministic bytes."""
    kids = " ".join(f"{3 + i} 0 R" for i in range(page_count))
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode(),
    ]
    for _ in range(page_count):
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << >> /Contents << /Length 0 >> >>"
        )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode())
        out.write(body)
        out.write(b"\nendobj\n")
    xref_pos = out.tell()
    size = len(objs) + 1
    out.write(f"xref\n0 {size}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return out.getvalue()


PDF_2PAGE = make_pdf(2)
