from __future__ import annotations

import html

from document.models import Document

from ..brand import get_brand
from ..plan import build_plan


def render_preview(
    document: Document,
    output_mode: str = "STUDENT_WITH_ENDNOTES",
    brand_id: str | None = None,
) -> str:
    """HTML preview driven by the same LayoutPlan as the print renderers —
    what the reviewer sees is what the artifact will contain."""
    plan = build_plan(document, output_mode=output_mode)
    brand = get_brand(brand_id or document.brand_id)
    q_by_id = {q.id: q for q in document.questions}

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<style>"
        "body{font-family:sans-serif;max-width:900px;margin:2rem auto}"
        ".grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}"
        ".q{padding:.8rem;border:1px solid #ddd;border-radius:8px}"
        ".wide{grid-column:1/-1}"
        ".num{font-weight:bold}.pts{color:#888;font-size:.85em}"
        ".choices{margin-left:1.5rem}"
        ".ans{border:1px dashed #aaa;min-height:4rem;margin:.5rem 0;"
        "color:#bbb;padding:.4rem;font-size:.8em}"
        f"h1{{color:{brand.accent_color}}}"
        ".notes{margin-top:2rem;border-top:2px solid #333;padding-top:1rem}"
        "</style></head><body>",
        f"<h1>{html.escape(brand.header_text or '시험지 미리보기')}</h1>",
    ]
    if not plan.slots:
        parts.append("<p>복원된 문항이 없습니다.</p>")
    parts.append("<div class='grid'>")
    for slot in plan.slots:
        q = q_by_id[slot.question_id]
        wide = "" if slot.kind == "objective" else " wide"
        pts = f" <span class='pts'>({q.points}점)</span>" if q.points else ""
        parts.append(
            f"<div class='q{wide}'><span class='num'>"
            f"{html.escape(slot.label)}.</span>{pts}"
        )
        for span in q.body:
            parts.append(f"<p>{html.escape(span.text)}</p>")
        for eq in q.equations:
            script = eq.hwp_formula or eq.latex or ""
            parts.append(f"<p><code>{html.escape(script)}</code></p>")
        if q.choices:
            parts.append("<div class='choices'>")
            for c in q.choices:
                text = " ".join(s.text for s in c.body)
                parts.append(
                    f"<div>{html.escape(c.label)} {html.escape(text)}</div>"
                )
            parts.append("</div>")
        if slot.answer_lines > 0:
            parts.append(
                f"<div class='ans' style='min-height:"
                f"{slot.answer_lines * 0.9:.0f}em'>서술형 답안 작성란</div>"
            )
        if output_mode == "TEACHER":
            parts.append(
                f"<p class='pts'>상태: {q.verification.status.value}</p>"
            )
        parts.append("</div>")
    parts.append("</div>")

    if plan.endnotes:
        parts.append("<div class='notes'><h2>정답 및 해설</h2>")
        for e in plan.endnotes:
            parts.append(
                f"<p><b>{html.escape(e.label)}.</b> 정답: "
                f"{html.escape(e.answer)} — {html.escape(e.explanation)}</p>"
            )
        parts.append("</div>")
    parts.append("</body></html>")
    return "".join(parts)
