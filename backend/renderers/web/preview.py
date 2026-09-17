from __future__ import annotations

import html

from document.models import Document


def render_preview(document: Document) -> str:
    """Plain HTML preview of the Verified Document JSON."""
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<style>body{font-family:sans-serif;max-width:800px;margin:2rem auto}"
        ".q{margin:1.5rem 0;padding:1rem;border:1px solid #ddd;border-radius:8px}"
        ".num{font-weight:bold}.pts{color:#888;font-size:.85em}"
        ".choices{margin-left:1.5rem}</style></head><body>",
        f"<h1>시험지 미리보기 — {html.escape(document.id)}</h1>",
    ]
    if not document.questions:
        parts.append("<p>복원된 문항이 없습니다.</p>")
    for q in sorted(document.questions, key=lambda x: x.number):
        pts = f" <span class='pts'>({q.points}점)</span>" if q.points else ""
        parts.append(f"<div class='q'><span class='num'>{q.number}.</span>{pts}")
        for span in q.body:
            parts.append(f"<p>{html.escape(span.text)}</p>")
        for eq in q.equations:
            parts.append(f"<p><code>{html.escape(eq.latex or '')}</code></p>")
        if q.choices:
            parts.append("<ol class='choices'>")
            for c in q.choices:
                text = " ".join(s.text for s in c.body)
                parts.append(f"<li value='{html.escape(c.label)}'>{html.escape(text)}</li>")
            parts.append("</ol>")
        parts.append(f"<p class='pts'>상태: {q.verification.status.value}</p></div>")
    parts.append("</body></html>")
    return "".join(parts)
