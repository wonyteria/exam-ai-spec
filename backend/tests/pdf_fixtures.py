"""Deterministic, *valid* PDF fixtures for tests.

The previous hand-written byte strings omitted the xref table and
startxref, so strict parsers (newer pypdfium builds, Ghostscript) rejected
them and tests failed depending on the installed pdfium version. These
builders emit real xref/startxref so every PDF parser accepts them.
"""
from __future__ import annotations

import io


def _text_stream(text: str) -> bytes:
    content = f"BT /F1 12 Tf 100 700 Td ({text}) Tj ET".encode()
    return (
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"\nendstream"
    )


def make_pdf(
    page_count: int = 2,
    text: str | None = None,
    rotate: int = 0,
) -> bytes:
    """A PDF with a correct xref table — deterministic bytes.

    `text` puts a real text object on page 1 (Helvetica). `rotate` sets
    /Rotate on page 1. Other pages stay blank.
    """
    kids = " ".join(f"{3 + i} 0 R" for i in range(page_count))
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode(),
    ]
    for i in range(page_count):
        resources = b"/Resources << >>"
        contents = b"/Contents << /Length 0 >>"
        if text and i == 0:
            contents = f"/Contents {3 + page_count} 0 R".encode()
            resources = (
                b"/Resources << /Font << /F1 << /Type /Font "
                b"/Subtype /Type1 /BaseFont /Helvetica >> >> >>"
            )
        rot = f"/Rotate {rotate} ".encode() if rotate and i == 0 else b""
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            + rot + resources + b" " + contents + b" >>"
        )
    if text:
        objs.append(_text_stream(text))
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
