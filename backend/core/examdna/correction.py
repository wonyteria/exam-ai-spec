"""Constraint-based correction (question-centric restoration).

Deterministic fixes applied to *materialized* Question fields — never to
ATU candidates. Two classes of outcome:

  AUTO_FIX   — structural defects that cannot change meaning:
               duplicate choice labels (① ① → ① ② …), out-of-order
               choice labels, duplicate descriptive sub-numbers,
               line-join merges, obvious OCR typos in numeric context,
               unit/symbol normalization (㎝→cm, ˚→°, ⊿→△, ∟→∠, –→-).

  REVIEW     — anything that could change meaning: sign disagreements
               between candidates, numbers a fix would rewrite, figure
               lengths/angles still unresolved, handwriting-over-print
               overlap, occluded sentences, ambiguous formulas.
               These become FieldIssues → NEEDS_USER_REVIEW.

Every fix is recorded on question.restoration.corrections with
before/after so the audit trail can replay it.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

from document.models import (
    AutoCorrection,
    FieldIssue,
    Question,
    TextSpan,
)

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
_CIRCLED_SET = set(_CIRCLED)
_MINUS_CHARS = "−–—‐‑‒−ㅡ一"  # unicode dashes + ㅡ misread
_DIGIT_CTX = re.compile(r"[\d.,)]")


def run_corrections(question: Question) -> None:
    """Apply every deterministic fix; flag what must stay human-decided.

    Idempotent: a rule records a correction only when it actually changed
    something, so re-running after a user edit adds no phantom entries.
    """
    _fix_choice_labels(question)
    _fix_sub_numbers(question)
    _fix_line_join(question)
    _fix_ocr_typos(question)
    _fix_units_symbols(question)
    _fix_bogee_consonants(question)
    _flag_review_items(question)


# --- auto fixes ------------------------------------------------------------


def _fix_choice_labels(q: Question) -> None:
    """Duplicate or out-of-order circled labels are positional defects —
    the printed ①②③ order is fixed, so renumbering cannot change meaning."""
    if len(q.choices) < 2:
        return
    labels = [c.label for c in q.choices]
    if not all(l in _CIRCLED_SET for l in labels):
        # Mixed/digit labels: normalize "1)" / "1." / "1" to circled when
        # every label is a bare digit in range — that is a format fix.
        if all(re.fullmatch(r"\(?\d{1,2}[.)]?", l or "") for l in labels):
            before = list(labels)
            for i, c in enumerate(q.choices):
                if i < len(_CIRCLED):
                    c.label = _CIRCLED[i]
            _record(q, "choice_label_normalize", "choices", before,
                    [c.label for c in q.choices])
        return
    order = [_CIRCLED.index(l) for l in labels]
    if len(set(labels)) == len(labels) and order == sorted(order):
        return
    before = list(labels)
    for i, c in enumerate(q.choices):
        if i < len(_CIRCLED):
            c.label = _CIRCLED[i]
    _record(
        q,
        "choice_label_dedup" if len(set(before)) != len(before)
        else "choice_order",
        "choices",
        before,
        [c.label for c in q.choices],
    )


def _fix_sub_numbers(q: Question) -> None:
    """Descriptive sub-question label inside the question's own label —
    cross-question renumbering happens in refresh (document scope)."""
    # nothing per-question; handled by renumber_duplicates(document)
    _ = q


def _fix_line_join(q: Question) -> None:
    """Merge body spans that were split mid-sentence: a span that does not
    end with terminal punctuation followed by one that starts with a
    lowercase letter, digit, operator, or closing bracket is a wrapped
    line, not a new sentence."""
    if len(q.body) < 2:
        return
    merged: list[TextSpan] = [q.body[0]]
    changed = False
    for span in q.body[1:]:
        prev = merged[-1].text.rstrip()
        nxt = span.text.lstrip()
        if (
            prev
            and nxt
            and not prev.endswith((".", "?", "!", ":", "。"))
            and re.match(r"^[a-z0-9+\-×÷=≤≥<>()],?", nxt)
        ):
            merged[-1].text = prev + " " + nxt
            merged[-1].atu_ids = merged[-1].atu_ids + span.atu_ids
            changed = True
        else:
            merged.append(span)
    if changed:
        _record(q, "line_join", "body",
                [s.text for s in q.body], [s.text for s in merged])
        q.body = merged


def _fix_ocr_typos(q: Question) -> None:
    """Obvious OCR misreads — only inside unambiguous numeric/math context.

    - full-width digits/letters → ASCII (NFKC)
    - O/o→0 and l/I→1 only when embedded between digits ("2O3" → "203")
    - stray space inside a digit group ("3 , 5" → "3.5" is NOT safe —
      only digit-space-digit merges are skipped; never guess decimals)
    """
    for span in _all_spans(q):
        fixed = _numeric_typos(span.text)
        if fixed != span.text:
            _record(q, "ocr_typo", _span_field(q, span), span.text, fixed)
            span.text = fixed
    for eq in q.equations:
        if eq.latex:
            fixed = _numeric_typos(eq.latex)
            if fixed != eq.latex:
                _record(q, "ocr_typo", f"equation:{eq.id}", eq.latex, fixed)
                eq.latex = fixed


def _fix_units_symbols(q: Question) -> None:
    for span in _all_spans(q):
        fixed = _normalize_units(span.text)
        if fixed != span.text:
            _record(q, "unit_normalize", _span_field(q, span),
                    span.text, fixed)
            span.text = fixed
    for eq in q.equations:
        if eq.latex:
            fixed = _normalize_units(eq.latex)
            if fixed != eq.latex:
                _record(q, "unit_normalize", f"equation:{eq.id}",
                        eq.latex, fixed)
                eq.latex = fixed


# 보기 항목 자음(ㄱ ㄴ ㄷ ㄹ ㅁ)이 받침 없는 음절(가 나 다 라 마)로
# 읽히는 OCR/VLM 오류 — 심원중 gold 비교에서 발견된 체계적 오류.
_BOGEE_HEADER = re.compile(r"[<〈]\s*보\s*기\s*[>〉]")
_BOGEE_MARKER = re.compile(r"(?<![가-힣])[ㄱㄴㄷㄹㅁㅂㅅ][.)]")
_SYL_TO_CONS = {
    "가": "ㄱ", "나": "ㄴ", "다": "ㄷ", "라": "ㄹ",
    "마": "ㅁ", "바": "ㅂ", "사": "ㅅ",
}
_CHOICE_SYL = re.compile(
    r"^[가나다라마바사](?:\s*[,·]\s*[가나다라마바사])*\s*$")
_SYL_TOKEN = re.compile(r"[가나다라마바사]")
# "가. 항목" 패턴 — 앞 글자가 한글 음절이면 "이다." 같은 어미이므로 제외.
_BODY_SYL_ITEM = re.compile(r"(?<![가-힣\w])([가나다라마바사])[.)]")


def _fix_bogee_consonants(q: Question) -> None:
    """Consonant 보기 items misread as syllables (ㄱ→가, ㄴ→나, ㄷ→다).

    Evidence-gated: the body must actually use consonant 보기 items — a
    <보기> header or an existing ㄱ./ㄴ./ㄷ. marker. Without that evidence
    a bare "가" could be real text and is left for review instead. Only
    choices composed entirely of the syllable set are rewritten; a mixed
    or ambiguous choice (e.g. an extra hallucinated item) still flags.
    """
    body_text = " ".join(s.text for s in q.body)
    header = _BOGEE_HEADER.search(body_text)
    if not header and not _BOGEE_MARKER.search(body_text):
        return
    for c in q.choices:
        for span in c.body:
            t = span.text.strip()
            if _CHOICE_SYL.fullmatch(t):
                fixed = _SYL_TOKEN.sub(
                    lambda m: _SYL_TO_CONS[m.group(0)], t)
                _record(q, "bogee_consonant", f"choice:{c.label}",
                        span.text, fixed)
                span.text = fixed
    # Body item markers ("<보기> 가. … 나. …") — when a header exists,
    # only fix markers after it so a trailing "A가." sentence can never
    # be touched. When the only evidence is consonant markers elsewhere
    # in the body, syllable markers anywhere are misreads.
    seen_header = header is None  # no header -> fix from the start
    for span in q.body:
        if not seen_header:
            pos = span.text.find(header.group(0))
            if pos < 0:
                continue
            seen_header = True
            head, tail = span.text[:pos], span.text[pos:]
        else:
            head, tail = "", span.text
        fixed_tail = _BODY_SYL_ITEM.sub(
            lambda m: _SYL_TO_CONS[m.group(1)] + m.group(0)[1:], tail)
        if fixed_tail != tail:
            _record(q, "bogee_consonant", "body", span.text,
                    head + fixed_tail)
            span.text = head + fixed_tail


# --- review flags ----------------------------------------------------------


def _flag_review_items(q: Question) -> None:
    from document.restoration import atu_issues

    issues: list[FieldIssue] = []
    for atu in q.atus:
        issues.extend(atu_issues(atu))
    for i, flag in enumerate(q.verification.logic_flags):
        issues.append(FieldIssue(
            field="logic", reason=flag.kind, detail=flag.detail))
    for span in q.body:
        if re.search(r"□{2,}|…{2,}", span.text):
            issues.append(FieldIssue(
                field="body", reason="occluded",
                detail="가려진 영역이 본문에 남아 있음"))
            break
    q.restoration.issues = _dedup_issues(issues)


def _dedup_issues(issues: list[FieldIssue]) -> list[FieldIssue]:
    seen: set[tuple[str, str, str]] = set()
    out: list[FieldIssue] = []
    for i in issues:
        key = (i.field, i.reason, i.detail)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


# --- helpers ---------------------------------------------------------------


def _record(q: Question, rule: str, field: str, before: Any, after: Any) -> None:
    if before == after:
        return
    q.restoration.corrections.append(
        AutoCorrection(rule=rule, field=field, before=before, after=after)
    )


def _all_spans(q: Question) -> list[TextSpan]:
    spans = list(q.body)
    for c in q.choices:
        spans.extend(c.body)
    return spans


def _span_field(q: Question, span: TextSpan) -> str:
    for c in q.choices:
        if span in c.body:
            return f"choice:{c.label}"
    return "body"


_NORM_MAP = {
    "㎝": "cm", "㎜": "mm", "㎞": "km", "㎏": "kg", "㎡": "m²",
    "˚": "°", "º": "°", "⊿": "△", "∆": "△", "∟": "∠",
    "×": "×", "÷": "÷", "𝑥": "x", "𝑦": "y",
}
_NORM_RE = re.compile("|".join(re.escape(k) for k in _NORM_MAP))
_ANGLE_LT = re.compile(r"<([A-Z]{3})")


def _normalize_units(text: str) -> str:
    t = _NORM_RE.sub(lambda m: _NORM_MAP[m.group(0)], text)
    t = _ANGLE_LT.sub(r"∠\1", t)          # <ABC → ∠ABC
    # "85도" written as "85도" stays; "85˙"→"85°"
    t = re.sub(r"(\d)\s*˙", r"\1°", t)
    return t


# Full-width → ASCII for digits and math punctuation only. Full NFKC is
# NOT used: it would decompose ① → '1', ˚ → space+combining ring, etc.
_FW_MAP = {chr(0xFF10 + i): str(i) for i in range(10)}
_FW_MAP.update({
    "．": ".", "，": ",", "（": "(", "）": ")", "＋": "+",
    "－": "-", "＝": "=", "：": ":", "；": ";", "／": "/", "　": " ",
})


def _numeric_typos(text: str) -> str:
    t = text.translate(str.maketrans(_FW_MAP))
    # Minus-like dashes next to digits are minus signs.
    t = re.sub(
        rf"(?<=[\s(\[{_MINUS_CHARS}])([{_MINUS_CHARS}])\s*(?=\d)", "-", t)
    t = re.sub(rf"([{_MINUS_CHARS}])\s*(?=\d)", "-", t)
    # Letter-in-digit confusions: 2O3 → 203, 4l → 41 (digit-adjacent only).
    t = re.sub(r"(?<=\d)[Oo](?=\d)", "0", t)
    t = re.sub(r"(?<=\d)[lI](?=\d)", "1", t)
    t = re.sub(r"(?<=\d)[Oo]\b", "0", t)
    t = re.sub(r"(?<=\d)[lI]\b", "1", t)
    return t


# --- document-scope helpers -------------------------------------------------


def renumber_duplicate_subnumbers(doc) -> list[dict]:
    """Duplicate 'N-M' descriptive sub-labels get renumbered by position —
    the printed order is positional, so this is a format fix. Returns the
    list of corrections applied (also recorded on each question)."""
    applied = []
    by_parent: dict[str, list] = {}
    for q in doc.questions:
        m = re.fullmatch(r"(\d+)-(\d+)", q.label or "")
        if m:
            by_parent.setdefault(m.group(1), []).append(q)
    for parent, members in by_parent.items():
        labels = [q.label for q in members]
        if len(set(labels)) == len(labels):
            continue
        for i, q in enumerate(members, 1):
            new_label = f"{parent}-{i}"
            if q.label != new_label:
                _record(q, "sub_number_dedup", "number", q.label, new_label)
                q.label = new_label
                applied.append({"question": q.id, "label": new_label})
    return applied


def handwriting_overlap_issue(doc, question: Question) -> Optional[FieldIssue]:
    """A question whose bbox intersects a page 'uncertain region' (print
    overlapped by handwriting) must not auto-delete the overlap — flag it.
    Regions the reconstruction stage already resolved
    (PRESERVE_ORIGINAL / RESTORE_REFERENCE) are decided, not review items."""
    if not question.source or not question.source.bbox:
        return None
    page_idx = question.source.page
    if page_idx >= len(doc.pages):
        return None
    page = doc.pages[page_idx]
    regions = page.uncertain_regions or []
    if not regions:
        return None
    decisions = page.reconstruction or []
    # When reconstruction ran, only regions it could not decide
    # (REVIEW_REQUIRED) still need a human.
    if decisions:
        decided = {"PRESERVE_ORIGINAL", "RESTORE_REFERENCE"}
        regions = [
            r for i, r in enumerate(regions)
            if i >= len(decisions)
            or decisions[i].get("decision") not in decided
        ]
        if not regions:
            return None
    b = question.source.bbox
    for region in regions:
        rb = region.get("bbox_px") or region.get("bbox") or {}
        try:
            rx, ry, rw, rh = (
                float(rb["x"]), float(rb["y"]),
                float(rb["w"]), float(rb["h"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if (
            b.x < rx + rw and rx < b.x + b.w
            and b.y < ry + rh and ry < b.y + b.h
        ):
            return FieldIssue(
                field="source", reason="print_handwriting_overlap",
                detail="인쇄와 필기가 겹친 영역 — 자동 삭제하지 않고 보류",
            )
    return None
