"""Dev-only gold extraction for the 심원중 benchmark.

Reads the reference HWP's binary record stream (pyhwp — NOT a project
dependency; run with a venv that has `pip install pyhwp six`) and emits
`expected.json` next to the sample images. The HWP is evaluation ground
truth only — it is never a runtime input to the restoration pipeline.

HWP internals used:
  - HWPTAG_PARA_TEXT (67): UTF-16LE runs. Inline objects appear as
    \\x0b + 6-char ctrlid + \\x0b; equation controls have ctrlid 'deqe'
    (UTF-16 'eqed' byte-swapped).
  - HWPTAG_CTRL_EQEDIT (88): payload offset 4 = uint16 char count, then
    the HWP equation script (UTF-16LE), then an "Equation Version" tail.

Figure text labels (rmA, 40DEG, 12 rm cm) live in standalone EQ
paragraphs between a question body and its choices — they are collected
as `figure_labels`, the closest thing to a 도형 라벨 ground truth.

    pyhwp-venv/bin/python extract_simwon_gold.py [--hwp PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import unicodedata
from pathlib import Path

SAMPLES = Path(__file__).resolve().parents[3] / "samples" / "심원중 샘플"
DEFAULT_HWP = next(iter(SAMPLES.glob("*.hwp")), None)

# The exam's fixed structure — labels must match what the pipeline
# produces (segmenter.normalize_label canonical form).
LABELS = (
    [str(i) for i in range(1, 21)]
    + ["논술형 1", "1-1", "1-2", "논술형 2", "2-1", "2-2", "2-3",
       "논술형 3", "3-1", "3-2", "3-3"]
)

# Every inline object is <ctrl><6 UTF-16 chars of ctrlid><ctrl> where the
# bracketing char marks the object kind; '敤敱\x00\x00\x00\x00' is the
# byte-swapped 'eqed' ctrlid of an equation.
_EQ_CTRLID = "敤敱\x00\x00\x00\x00"
CTRL_PAIR = re.compile(r"([\x01-\x1f])([\s\S]{6})\1")
SUB_Q = re.compile(r"^\s*(\d{1,2})-(\d{1,2})\s*[.)\]．]")
POINTS = re.compile(r"\[\s*(\d{1,2})\s*점")
ANSWER_MARK = re.compile(r"^\s*([①-⑩])\s*$")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


def eq_script(payload: bytes) -> str | None:
    try:
        n = struct.unpack_from("<H", payload, 4)[0]
        return payload[6 : 6 + n * 2].decode("utf-16-le")
    except Exception:
        return None


def script_to_text(script: str) -> str:
    """HWP equation script -> readable surface text (for gold comparison).

    Covers the operators this exam uses; unknown constructs degrade to a
    compacted script, never a guessed rendering."""
    s = script.strip()
    s = re.sub(r"\beqalign\s*\{", "", s)
    s = re.sub(r"\brm\s*", "", s)
    s = re.sub(r"\bBAR\s*", "", s)
    s = re.sub(r"\bbar\s*\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\bTRIANGLE\s*", "△", s)
    s = re.sub(r"\bANGLE\s*", "∠", s)
    s = re.sub(r"\bTHEREFORE\s*", "∴", s)
    s = re.sub(r"\bBOT\b", "⊥", s)
    s = re.sub(r"\bBECAUSE\b", "∵", s)
    s = re.sub(r"\bDEG\b", "°", s)
    s = re.sub(r"(\d+)\s*OVER\s*(\d+)", r"\1/\2", s)
    s = re.sub(r"\bTIMES\s*", "×", s)
    s = re.sub(r"//", "∥", s)
    s = s.replace("==", "≡")
    s = re.sub(r"``+", " ", s)
    s = re.sub(r"`+", " ", s)
    s = s.replace("#", ", ")
    s = re.sub(r"[{}]", "", s)
    s = re.sub(r"□\s*", "□", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def clean_text(text: str) -> str:
    """Drop HWP control/picture glyph noise from decoded para text."""
    out = []
    for ch in text:
        cp = ord(ch)
        if cp < 0x20 or 0xE000 <= cp <= 0xF8FF:
            continue
        if unicodedata.category(ch) in ("Co", "Cf", "Cs"):
            continue
        out.append(ch)
    s = "".join(out)
    # Symbol-font marks (teacher's checks) survive as rare glyphs —
    # keep only chars that appear in normal Korean exam text.
    s = re.sub(r"[ᦅ-᧿ᚵᚹᲾ᪱᝸Ᏼ፞Ā-žࠀ-࿿ఐ-ఴྠ-ᆿ\ua000-\ua4ff⚬-⚿\U0001f000-\U0001ffff]+", "", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def extract_paras(hwp_path: Path) -> list[dict]:
    from hwp5.binmodel import Hwp5File

    hwp = Hwp5File(str(hwp_path))
    sec = hwp.bodytext.sections[0]
    paras: list[dict] = []
    cur = None
    for r in sec.records():
        tid = r["tagid"]
        if tid == 66:  # PARA_HEADER
            cur = {"text_parts": [], "eqs": []}
            paras.append(cur)
        elif cur is None:
            continue
        elif tid == 67:  # PARA_TEXT
            cur["text_parts"].append(r["payload"])
        elif tid == 88:  # CTRL_EQEDIT
            cur["eqs"].append(eq_script(r["payload"]))

    out = []
    for p in paras:
        raw = b"".join(p["text_parts"])
        text = raw.decode("utf-16-le", "replace")
        eqs = iter(p["eqs"])
        parts = []
        pos = 0
        for m in CTRL_PAIR.finditer(text):
            parts.append(text[pos:m.start()])
            if m.group(2) == _EQ_CTRLID:
                try:
                    s = next(eqs)
                    if s:
                        parts.append(f"〈{script_to_text(s)}〉")
                except StopIteration:
                    pass
            pos = m.end()
        parts.append(text[pos:])
        joined = "".join(parts)
        # Floating equation objects (figure labels like △ABC, ∠A, 40°)
        # anchor at paragraph level with NO para-text placeholder — emit
        # them as the paragraph's content so they reach figure_labels.
        remaining = [s for s in eqs if s]
        if remaining:
            joined += "".join(f"〈{script_to_text(s)}〉" for s in remaining)
        out.append({"text": clean_text(joined), "eqs": p["eqs"]})
    return out


def classify(text: str) -> str:
    if not text:
        return "empty"
    if SUB_Q.match(text):
        return "sub"
    if ANSWER_MARK.match(text):
        return "answer_mark"
    if text[0] in CIRCLED:
        return "choices"
    if text.startswith("〈") and text.endswith("〉"):
        return "figure"
    if re.fullmatch(r"(〈[^〉]*〉\s*)+", text):
        return "figure"
    if re.fullmatch(r"[가-힣\s]*\d-\d( \(.*\))?", text):
        return "answer_note"  # teacher's worked-answer headers "1-1" etc
    return "body"


_FURNITURE = re.compile(
    r"학원|학년도|학기|이름|심원중|심 원 중|중간고사|중간|정답"
    r"|\d{3}-\d{3,4}-\d{4}|답 여러가지"
)


def is_body_start(text: str) -> bool:
    """A para that opens a question: ends with [N점] or a question
    mark/imperative (Q12 lost its [점] tag in source). Paragraphs
    starting with an equation fragment (〈…〉) are worked answers printed
    inside the sheet, and header/footer furniture is excluded."""
    if text.startswith("〈") or _FURNITURE.search(text):
        return False
    if POINTS.search(text):
        return True
    t = text.rstrip()
    return t.endswith(("?", "？", "시오.", "시오"))


def build_gold(paras: list[dict]) -> list[dict]:
    questions: list[dict] = []
    cur: dict | None = None
    expected = iter(LABELS)
    pending_subs: list[str] = []
    for p in paras:
        text = p["text"]
        if not text or _FURNITURE.search(text):
            continue
        kind = classify(text)
        if kind == "sub":
            # literal "N-M." sub-question bodies — their own question
            label = f"{SUB_Q.match(text).group(1)}-{SUB_Q.match(text).group(2)}"
            cur = {"number": label, "body": SUB_Q.sub("", text).strip(),
                   "figure_labels": [], "choices": {}}
            questions.append(cur)
            continue
        if kind == "body" and is_body_start(text):
            # teacher answer notes ("1-1" "2-2") are not bodies
            if ANSWER_MARK.match(text) or re.fullmatch(r"\d-\d", text.strip()):
                continue
            cur = {"number": None, "body": text,
                   "figure_labels": [], "choices": {}}
            questions.append(cur)
            continue
        if cur is None:
            continue
        if kind == "answer_mark":
            cur.setdefault("answer", ANSWER_MARK.match(text).group(1))
        elif kind == "choices":
            for m in re.finditer(r"([①-⑩])([^①-⑩]*)", text):
                label, body = m.group(1), clean_text(m.group(2))
                if body or label not in cur["choices"]:
                    cur["choices"].setdefault(label, body.strip())
        elif kind == "figure":
            for s in p["eqs"]:
                if s:
                    v = script_to_text(s)
                    if v not in cur["figure_labels"]:
                        cur["figure_labels"].append(v)
        elif kind in ("body", "answer_note"):
            # continuation text inside a question block (e.g. <보기>)
            cur["body"] = (cur["body"] + "\n" + text).strip()

    # Assign labels: subs already named; bodies consume the LABELS order
    # skipping any label a sub already claimed.
    claimed = {q["number"] for q in questions if q["number"]}
    remaining = [l for l in LABELS if l not in claimed]
    ri = 0
    for q in questions:
        if q["number"] is None:
            q["number"] = remaining[ri]
            ri += 1
        pm = POINTS.search(q["body"])
        if pm:
            q["points"] = int(pm.group(1))
        if not q["choices"]:
            q.pop("choices")
        if not q["figure_labels"]:
            q.pop("figure_labels")
    return questions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwp", type=Path, default=DEFAULT_HWP)
    ap.add_argument("--out", type=Path, default=SAMPLES / "expected.json")
    args = ap.parse_args()
    paras = extract_paras(args.hwp)
    questions = build_gold(paras)
    gold = {
        "_note": (
            "Dev-only gold extracted from the reference HWP via pyhwp "
            "(EQEDIT scripts converted to surface text). Never a runtime "
            "input. See eval/bench/extract_simwon_gold.py."
        ),
        "questions": questions,
    }
    args.out.write_text(
        json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for q in questions:
        print(
            q["number"], "|", q["body"][:60].replace("\n", " "),
            "| pts:", q.get("points"), "| ans:", q.get("answer"),
            "| ch:", len(q.get("choices", {})), "| fig:", q.get("figure_labels", [])[:6],
        )
    print(f"\n{len(questions)} questions -> {args.out}")


if __name__ == "__main__":
    main()
