"""Plan-driven minimal PDF renderer (WP07).

Uses a predefined CID font (HYGoThic-Medium + UniKS-UCS2-H — the
standard Adobe Korean font pack reference) so Hangul text is real
Unicode in the output stream, not `?` placeholders. Content follows the
shared LayoutPlan ordering and output mode — answers only appear in
non-STUDENT modes.
"""
from __future__ import annotations

import io

from document.models import Document

from ..plan import build_plan


def _t(s: str) -> str:
    """UTF-16BE hex string for the CID font."""
    return "<" + s.encode("utf-16-be").hex() + ">"


def render_pdf(
    document: Document,
    title: str = "시험지",
    output_mode: str = "STUDENT_WITH_ENDNOTES",
) -> bytes:
    plan = build_plan(document, output_mode=output_mode, title=title)
    q_by_id = {q.id: q for q in document.questions}

    lines: list[str] = [title]
    for slot in plan.slots:
        q = q_by_id[slot.question_id]
        head = f"{slot.label}." + (f" ({q.points}점)" if q.points else "")
        lines.append(head)
        lines.extend(span.text for span in q.body)
        for eq in q.equations:
            script = eq.hwp_formula or eq.latex or ""
            if script:
                lines.append(f"[수식] {script}")
        for c in q.choices:
            lines.append(
                f"{c.label} " + " ".join(s.text for s in c.body)
            )
        if slot.answer_lines > 0:
            lines.append("서술형 답안 작성란: " + "_" * 40)
        lines.append("")
    if plan.endnotes:
        lines.append("정답 및 해설")
        for e in plan.endnotes:
            lines.append(f"{e.label}. 정답: {e.answer}")
            lines.append(e.explanation)

    # paginate: 42 lines per page — real page breaks, not overflow
    pages = [lines[i : i + 42] for i in range(0, len(lines), 42)] or [[title]]
    streams = []
    for page_lines in pages:
        stream = io.BytesIO()
        stream.write(b"BT /F1 11 Tf 50 790 Td 15 TL\n")
        for line in page_lines:
            stream.write(f"{_t(line)} Tj T*\n".encode("latin-1"))
        stream.write(b"ET")
        streams.append(stream.getvalue())

    return _assemble(streams)


def _assemble(streams: list[bytes]) -> bytes:
    n = len(streams)
    # obj ids: 1 catalog, 2 pages, 3..3+n-1 page objs, then font, contents
    page_ids = [3 + i for i in range(n)]
    font_id = 3 + n
    content_ids = [font_id + 1 + i for i in range(n)]

    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
    ]
    for i, pid in enumerate(page_ids):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_ids[i]} 0 R >>".encode()
        )
    objects.append(
        b"<< /Type /Font /Subtype /Type0 /BaseFont /HYGoThic-Medium "
        b"/Encoding /UniKS-UCS2-H "
        b"/DescendantFonts [<< /Type /Font /Subtype /CIDFontType0 "
        b"/BaseFont /HYGoThic-Medium /CIDSystemInfo "
        b"<< /Registry (Adobe) /Ordering (Korea1) /Supplement 2 >> >>] >>"
    )
    for content in streams:
        objects.append(
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode())
        out.write(obj)
        out.write(b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF".encode()
    )
    return out.getvalue()
