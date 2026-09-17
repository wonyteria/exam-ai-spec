from __future__ import annotations

import io

from document.models import Document


def render_pdf(document: Document, title: str = "exam") -> bytes:
    """Minimal single-page PDF listing question headers (draft renderer)."""
    lines = [title]
    for q in sorted(document.questions, key=lambda x: x.number):
        head = f"{q.number}." + (f" ({q.points} pts)" if q.points else "")
        lines.append(head)
        lines.extend(span.text for span in q.body)

    stream = io.BytesIO()
    stream.write(b"BT /F1 12 Tf 50 780 Td 16 TL\n")
    for line in lines:
        safe = line.encode("latin-1", "replace").decode("latin-1")
        safe = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.write(f"({safe}) Tj T*\n".encode("latin-1"))
    stream.write(b"ET")
    content = stream.getvalue()

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode())
        out.write(obj)
        out.write(b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF".encode()
    )
    return out.getvalue()
