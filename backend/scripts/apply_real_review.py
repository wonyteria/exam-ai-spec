"""Apply agent-reviewed resolutions to the real exam document (doc_8dc95bea7fcb).

Each question gets ONE /changes revision containing its ResolveATU ops plus
field fixes (choices/points/type/figure description) plus answer+solution.
Agent resolved each conflict by reading the source review crops directly.
"""
from __future__ import annotations

import json
import sys

import requests

BASE = "http://127.0.0.1:8871"
TENANT = "tn_19e257c96c4b"
DOC = "doc_8dc95bea7fcb"
HDR = {"X-Dev-User": "e2e@local"}

Q = {  # label -> question id (stable targets; labels may change on renumber)
    "1": "q_f6a04711e205", "2": "q_92639756b640", "3": "q_e6b3b1884bf2",
    "4": "q_b7550f31899b", "5": "q_6ddb972f8216", "6": "q_f43405779844",
    "7": "q_b95c112a4946", "8": "q_164036950ba4", "9": "q_ea31f9f0ef00",
    "?mark1": "q_82393f7950d8", "11": "q_bbeda252b335", "12": "q_5c31dcb57cf3",
    "13": "q_085b2807b6e0", "14": "q_27e7c0567900", "15": "q_d1fd83171882",
    "?6": "q_48e0d7a169ea", "17": "q_030097c6bf89", "18": "q_282aa7d45e0f",
    "19": "q_0866a70040ba", "20": "q_90df0302f66b",
    "논술1": "q_e3390f7e5175", "1-1": "q_0c8bbf9a80f4", "1-2": "q_2494ba616c37",
    "논술2": "q_2a5cab198ce2", "2-1": "q_435b333ca92e", "2-2": "q_820d22d054f2",
    "2-3": "q_9b7ed1744f31", "논술3": "q_95562e6f6d7f", "3-1": "q_290bd94bce10",
    "3-2": "q_cb45220b3052", "3-3": "q_d01d8b77f8e8",
}

MC = "multiple_choice"
SJ = "subjective"

# label -> list of ChangeOps for that question
PLAN: dict[str, list[dict]] = {}

def resolve(atu_id: str, value) -> dict:
    return {"op": "ResolveATU", "target_id": atu_id, "value": value}

def body(qid, text):
    return {"op": "SetBody", "target_id": qid, "value": text}

def choice(qid, label, text):
    return {"op": "SetChoice", "target_id": qid, "field": label, "value": text}

def pts(qid, n):
    return {"op": "SetPoints", "target_id": qid, "value": n}

def ans(qid, v):
    return {"op": "SetAnswer", "target_id": qid, "value": v}

def sol(qid, steps, concepts=None):
    return {"op": "SetSolution", "target_id": qid,
            "value": {"steps": steps, "concepts": concepts or []}}

def fld(qid, field, value):
    return {"op": "SetField", "target_id": qid, "field": field, "value": value}

def fig(qid, desc):
    return fld(qid, "figures", [{"topology": {"description": desc}}])


# ---------- page 2 : 1~5 ----------

PLAN["1"] = [
    resolve("atu_c8264cb3115f",
            "△ABC에서 AB=AC, ∠A=40°일 때, ∠ACB의 크기는? [3점]"),
    choice(Q["1"], "①", "55°"), choice(Q["1"], "②", "60°"),
    choice(Q["1"], "③", "65°"), choice(Q["1"], "④", "70°"),
    ans(Q["1"], "④"),
    sol(Q["1"], [
        "AB=AC인 이등변삼각형이므로 ∠B=∠ACB이다.",
        "∠A+∠B+∠ACB=180°이고 ∠A=40°이므로 ∠ACB=(180°−40°)/2=70°.",
    ], ["이등변삼각형", "삼각형 내각의 합"]),
]

PLAN["2"] = [
    resolve("atu_0587e2ad0d5e",
            "△ABC에서 BD=CD, AB=12cm, ∠CAD=50°일 때, x, y의 값으로 각각 "
            "옳은 것은? (단, x, y는 상수) [3점]"),
    fig(Q["2"], "AD⊥BC (그림의 직각 표시), x=∠ABC(도), y=AC(cm)"),
    choice(Q["2"], "①", "35, 12"), choice(Q["2"], "②", "40, 10"),
    choice(Q["2"], "③", "40, 12"), choice(Q["2"], "④", "50, 10"),
    choice(Q["2"], "⑤", "50, 12"),
    ans(Q["2"], "③"),
    sol(Q["2"], [
        "AD⊥BC이고 BD=CD이므로 AD는 BC의 수직이등분선 → AB=AC.",
        "y=AC=AB=12(cm).",
        "이등변삼각형에서 AD는 ∠A의 이등분선 → ∠BAC=2×50°=100°.",
        "∠ABC=(180°−100°)/2=40° → x=40. 따라서 x=40, y=12.",
    ], ["수직이등분선", "이등변삼각형"]),
]

PLAN["3"] = [
    body(Q["3"], "□ABCD에서 AE=BE이고, AD=12cm, BC=10cm일 때, "
                 "DC의 길이(cm)는? [3점]"),
    pts(Q["3"], 3),
    fig(Q["3"], "직각사다리꼴 (∠ADC=∠BCD=90°), E는 DC 위의 점, "
                "∠AEB=90°(그림의 직각 표시), AE=BE"),
    choice(Q["3"], "①", "20"), choice(Q["3"], "②", "21"),
    choice(Q["3"], "③", "22"), choice(Q["3"], "④", "23"),
    choice(Q["3"], "⑤", "24"),
    ans(Q["3"], "③"),
    sol(Q["3"], [
        "∠AEB=90°이므로 ∠AED+∠BEC=90°이고, △ADE에서 ∠AED+∠DAE=90° "
        "→ ∠DAE=∠BEC.",
        "∠ADE=∠ECB=90°, AE=BE, ∠DAE=∠BEC이므로 △ADE≅△ECB (RHA 합동).",
        "DE=BC=10cm, EC=AD=12cm → DC=DE+EC=10+12=22(cm).",
    ], ["직각삼각형 합동", "RHA"]),
]

PLAN["4"] = [
    resolve("atu_180d5e02d18b", "4"),  # number ATU — label stays '4'
    resolve("atu_9d759e16d5b3",
            "직각삼각형의 합동 조건에 대한 설명으로 옳은 것만을 <보기>에서 "
            "있는 대로 고른 것은? [4점]\n<보기>\nㄱ. 두 변의 길이가 각각 같은 "
            "두 직각삼각형은 서로 합동이다.\nㄴ. 두 내각의 크기가 각각 같은 두 "
            "직각삼각형은 서로 합동이다.\nㄷ. 빗변의 길이가 같고 한 예각의 "
            "크기가 같은 두 직각삼각형은 합동이다."),
    resolve("atu_6208e5c56b63", "ㄱ, ㄷ"),
    resolve("atu_4e3ae5865f7b", "ㄴ, ㄷ"),
    pts(Q["4"], 4),
    choice(Q["4"], "①", "ㄱ"), choice(Q["4"], "②", "ㄴ"),
    choice(Q["4"], "③", "ㄷ"),
    ans(Q["4"], "④"),
    sol(Q["4"], [
        "ㄱ. 두 변의 길이가 각각 같으면 나머지 한 변도 피타고라스 정리로 "
        "같아 SSS 합동(또는 직각을 끼인 SAS 합동) → 참.",
        "ㄴ. 각만 같으면 닮음일 뿐 합동이 아님 → 거짓.",
        "ㄷ. 빗변과 한 예각이 같으면 RHA 합동 → 참.",
        "옳은 것은 ㄱ, ㄷ.",
    ], ["직각삼각형 합동 조건", "RHA", "RHS"]),
]

PLAN["5"] = [
    resolve("atu_b383b3ad34d2",
            "삼각형의 세 변의 길이를 나타낸 것 중, 직각삼각형이 될 수 "
            "없는 것은? [4점]"),
    choice(Q["5"], "①", "3cm, 4cm, 5cm"), choice(Q["5"], "②", "6cm, 8cm, 10cm"),
    choice(Q["5"], "③", "5cm, 12cm, 13cm"), choice(Q["5"], "④", "8cm, 15cm, 17cm"),
    choice(Q["5"], "⑤", "9cm, 10cm, 15cm"),
    ans(Q["5"], "⑤"),
    sol(Q["5"], [
        "직각삼각형 조건: (가장 긴 변)² = (나머지 두 변)²의 합.",
        "① 9+16=25 ✓  ② 36+64=100 ✓  ③ 25+144=169 ✓  ④ 64+225=289 ✓",
        "⑤ 9²+10²=181 ≠ 15²=225 → 직각삼각형이 될 수 없다.",
    ], ["피타고라스 정리"]),
]

# ---------- page 0 : 6~10 ----------

PLAN["6"] = [
    body(Q["6"], "∠C=90°인 직각삼각형 ABC에서 AB⊥DE이고, ED=CD, "
                 "AE=8cm, CD=6cm일 때, x+y의 값은? [4점]"),
    fig(Q["6"], "D는 BC 위의 점, E는 AB 위의 점이고 DE⊥AB, "
                "x=AC(cm), y=AD(cm)"),
    choice(Q["6"], "①", "18"), choice(Q["6"], "⑤", "22"),
    ans(Q["6"], "①"),
    sol(Q["6"], [
        "DE⊥AB, DC⊥AC이고 ED=CD이므로 △AED≅△ACD (빗변 AD 공통, "
        "한 변 ED=CD인 RHA 합동).",
        "AE=AC이므로 x=8.",
        "△ACD에서 AD=√(AC²+CD²)=√(64+36)=√100=10 → y=10.",
        "x+y=8+10=18.",
    ], ["RHA 합동", "피타고라스 정리"]),
]

PLAN["7"] = [
    resolve("atu_c3a13f1d8253",
            "삼각형의 내심과 외심에 대한 설명 중 옳지 않은 것은? [4점]"),
    choice(Q["7"], "①", "직각삼각형의 외심은 삼각형 외부에 있다"),
    choice(Q["7"], "③", "내심은 세 내각의 이등분선이 만나는 점이다."),
    ans(Q["7"], "①"),
    sol(Q["7"], [
        "내심은 세 내각의 이등분선의 교점이고 세 변에 이르는 거리가 같다 "
        "(②, ③ 참).",
        "외심은 세 변의 수직이등분선의 교점이고 세 꼭짓점에 이르는 거리가 "
        "같다 (④, ⑤ 참).",
        "직각삼각형의 외심은 빗변의 중점이므로 삼각형 외부가 아니다 "
        "→ ①이 옳지 않다.",
    ], ["내심", "외심"]),
]

PLAN["8"] = [
    resolve("atu_23f6d21f5b37",
            "점 I는 △ABC의 내심이고, DE는 점 I를 지나며 BC에 평행한 "
            "선이다. AD=13cm, AE=11cm, DE=15cm일 때, AB+AC의 값은? [3점]"),
    fig(Q["8"], "D는 AB 위, E는 AC 위의 점. I는 DE 위에 있다."),
    choice(Q["8"], "③", "37"), choice(Q["8"], "④", "39"),
    ans(Q["8"], "④"),
    sol(Q["8"], [
        "DE∥BC이므로 ∠DIB=∠IBC(엇각). I는 내심이라 ∠DBI=∠IBC "
        "→ ∠DBI=∠DIB → △DBI 이등변 → DB=DI.",
        "같은 방법으로 EC=EI.",
        "AB+AC=AD+DB+AE+EC=AD+AE+DI+EI=AD+AE+DE=13+11+15=39.",
    ], ["내심", "이등변삼각형", "평행선 엇각"]),
]

PLAN["9"] = [
    resolve("atu_ed4ddbfedbc8",
            "점 O가 △ABC의 외심일 때, x의 값은? [3점]"),
    fig(Q["9"], "∠BAC=50°, O는 △ABC 내부의 외심, x=∠BOC(도)"),
    choice(Q["9"], "①", "100"),
    ans(Q["9"], "①"),
    sol(Q["9"], [
        "외심 O는 외접원의 중심이므로 ∠BOC는 중심각, ∠BAC는 같은 호 BC에 "
        "대한 원주각.",
        "∠BOC=2∠BAC=2×50°=100° → x=100.",
    ], ["외심", "원주각과 중심각"]),
]

PLAN["?mark1"] = [  # → printed number 10
    fld(Q["?mark1"], "number", 10),
    body(Q["?mark1"],
         "AB=AC인 이등변삼각형 ABC의 꼭짓점 A에서 BC에 내린 수선 위의 "
         "두 점 I와 O는 각각 △ABC의 내심과 외심이다. AB=40cm, BC=48cm이고, "
         "△ABC의 외접원의 반지름이 25cm일 때, IO의 길이(cm)는? [5점]"),
    pts(Q["?mark1"], 5),
    choice(Q["?mark1"], "①", "1"), choice(Q["?mark1"], "②", "2"),
    choice(Q["?mark1"], "③", "3"), choice(Q["?mark1"], "④", "4"),
    choice(Q["?mark1"], "⑤", "5"),
    ans(Q["?mark1"], "⑤"),
    sol(Q["?mark1"], [
        "BC의 중점을 M이라 하면 BM=24cm이고, AM=√(40²−24²)=√1024=32cm.",
        "내심 I는 BC에서 내접원 반지름만큼 위에 있다. 넓이=48×32/2=768, "
        "둘레 절반 s=(40+40+48)/2=64 → r=768/64=12 → I의 높이=12.",
        "외심 O는 M 위에서 OM=√(OB²−BM²)=√(25²−24²)=√49=7 → O의 높이=7.",
        "I와 O는 같은 수선 위에 있으므로 IO=12−7=5(cm).",
    ], ["내심", "외심", "외접원", "피타고라스 정리"]),
]

# ---------- page 1 : 논술2, 논술3 ----------

PLAN["논술2"] = [
    body(Q["논술2"], "원 I는 직각삼각형 ABC의 내접원이고 점 P, Q, R은 "
                     "원 I의 접점일 때, ∠RCQ의 크기를 구하려고 한다. "
                     "다음 물음에 답하시오. [7점]"),
    fig(Q["논술2"], "∠B=90°인 직각삼각형. P는 AB 위, Q는 BC 위, R은 AC 위의 "
                    "접점"),
    fld(Q["논술2"], "type", SJ),
    ans(Q["논술2"], "18"),
    sol(Q["논술2"], [
        "(2-1) ∠PIQ=90° → ∠PRQ=45°",
        "(2-2) ∠CRQ=(180°−45°)×3/5=81°",
        "(2-3) ∠RCQ=180°−2×81°=18°",
    ], ["내접원", "접선의 길이", "원주각"]),
]

PLAN["2-1"] = [
    resolve("atu_b0ee8d484374",
            "원 I 위의 접점을 연결한 △PQR의 한 내각인 ∠PRQ의 크기를 "
            "구하고, 그 과정을 서술하시오. [3점]"),
    resolve("atu_488629f2ab9b", 3),  # points
    fld(Q["2-1"], "type", SJ),
    ans(Q["2-1"], "45"),
    sol(Q["2-1"], [
        "접점에서의 반지름은 접선과 수직이므로 IP⊥AB, IQ⊥BC.",
        "사각형 BPIQ에서 ∠PBI=∠BPI=∠BQI=90°이므로 ∠PIQ=90°.",
        "∠PRQ는 호 PQ에 대한 원주각 → ∠PRQ=½∠PIQ=45°.",
    ], ["내접원", "원주각"]),
]

PLAN["2-2"] = [
    pts(Q["2-2"], 2),
    fld(Q["2-2"], "type", SJ),
    ans(Q["2-2"], "81"),
    sol(Q["2-2"], [
        "직선 AC 위에서 ∠ARP+∠PRQ+∠QRC=180°이고 ∠PRQ=45°이므로 "
        "∠ARP+∠CRQ=135°.",
        "∠CRQ:∠ARP=3:2 → ∠CRQ=135°×3/5=81°.",
    ], ["직선상의 각", "비례배분"]),
]

PLAN["2-3"] = [
    fld(Q["2-3"], "type", SJ),
    ans(Q["2-3"], "18"),
    sol(Q["2-3"], [
        "점 C에서 원 I에 그은 두 접선 CQ, CR은 길이가 같으므로 △CQR은 "
        "이등변삼각형.",
        "∠CRQ=∠RQC=81°이므로 ∠RCQ=180°−2×81°=18°.",
    ], ["접선의 길이", "이등변삼각형"]),
]

PLAN["논술3"] = [
    body(Q["논술3"], "평행사변형 ABCD에서 점 E는 CD의 중점이고, "
                     "AE의 연장선과 BC의 연장선이 만나는 점을 F라 하자. "
                     "다음 물음에 답하시오. [7점]"),
    fld(Q["논술3"], "type", SJ),
    ans(Q["논술3"], "평행사변형"),
    sol(Q["논술3"], [
        "(3-1) △AED≅△FEC (ASA 합동)",
        "(3-2) □ACFD는 평행사변형",
        "(3-3) AD∥CF이고 AD=CF이므로 한 쌍의 대변이 평행하고 길이가 같다.",
    ], ["삼각형 합동", "평행사변형 판정"]),
]

PLAN["3-1"] = [
    resolve("atu_bf513c9d9deb",
            "△AED와 △FEC가 합동임을 설명하시오. (단, 만족하는 합동 조건을 "
            "반드시 포함하여 설명하시오.) [3점]"),
    fld(Q["3-1"], "type", SJ),
    ans(Q["3-1"], "ASA 합동"),
    sol(Q["3-1"], [
        "∠AED=∠FEC (맞꼭지각).",
        "E는 CD의 중점이므로 DE=CE.",
        "AD∥BF이므로 ∠ADE=∠FCE (엇각).",
        "따라서 △AED≅△FEC (ASA 합동).",
    ], ["ASA 합동", "맞꼭지각", "엇각"]),
]

PLAN["3-2"] = [
    fld(Q["3-2"], "type", SJ),
    ans(Q["3-2"], "평행사변형"),
    sol(Q["3-2"], [
        "3-1의 합동에서 대응변 AD=CF.",
        "F는 BC의 연장선 위에 있고 AD∥BC이므로 AD∥CF.",
        "한 쌍의 대변 AD, CF가 평행하고 길이가 같으므로 □ACFD는 "
        "평행사변형.",
    ], ["평행사변형 판정"]),
]

PLAN["3-3"] = [
    resolve("atu_7557b8df97b7",
            "3-2에서 답한 사각형인 이유를 서술하시오. [2점]"),
    fld(Q["3-3"], "type", SJ),
    ans(Q["3-3"], "AD∥CF이고 AD=CF이므로"),
    sol(Q["3-3"], [
        "AD∥BC이고 F는 BC의 연장선 위의 점이므로 AD∥CF.",
        "△AED≅△FEC이므로 대응변 AD=CF.",
        "한 쌍의 대변이 평행하고 그 길이가 같으면 평행사변형이다.",
    ], ["평행사변형 판정"]),
]

# ---------- page 3 : 17~20, 논술1 ----------

PLAN["17"] = [
    resolve("atu_adeef76b69a1",
            "마름모 ABCD의 꼭짓점 A에서 BD와 CD에 내린 수선의 발을 각각 "
            "O, E라 하고, AE와 BD의 교점을 F라고 하자. ∠FAO=24°일 때, "
            "∠BCD의 크기는? [5점]"),
    fig(Q["17"], "마름모의 대각선 교점 O, E는 CD 위의 수선의 발, "
                 "F=AE∩BD"),
    choice(Q["17"], "①", "130°"), choice(Q["17"], "②", "132°"),
    choice(Q["17"], "③", "134°"), choice(Q["17"], "④", "136°"),
    choice(Q["17"], "⑤", "138°"),
    ans(Q["17"], "②"),
    sol(Q["17"], [
        "∠BCD=θ라 하면 마름모의 대각이 같으므로 ∠BAD=θ이고, 대각선 AC는 "
        "∠BAD를 이등분하므로 ∠OAD=θ/2.",
        "AE⊥CD이고 ∠ADC=180°−θ이므로 △ADE에서 ∠DAE=θ−90°.",
        "∠FAO=∠OAD−∠EAD=θ/2−(θ−90°)=90°−θ/2=24°.",
        "θ/2=66° → ∠BCD=132°.",
    ], ["마름모", "수선", "각 계산"]),
]

PLAN["18"] = [
    resolve("atu_e7a2420d697b",
            "□ABCD는 정사각형이고, 두 대각선의 교점을 O라 하자. "
            "AO=7cm일 때, 사각형의 넓이(cm²)는? [3점]"),
    choice(Q["18"], "④", "98"), choice(Q["18"], "⑤", "104"),
    ans(Q["18"], "④"),
    sol(Q["18"], [
        "정사각형의 대각선은 서로를 이등분하므로 AC=2AO=14cm.",
        "정사각형 넓이=(대각선²)/2=14²/2=98(cm²).",
    ], ["정사각형", "대각선"]),
]

PLAN["19"] = [
    resolve("atu_8a93290e34b9" if False else "atu_0866a70040ba", ""),
]
PLAN["19"] = [
    resolve("__ATU_q19__", ""),
]
PLAN["19"] = [
    # filled by script: resolve body ATU + clean choices
    choice(Q["19"], "①", "마름모 — 이웃한 두 각의 크기가 같다"),
    choice(Q["19"], "②", "직사각형 — 두 대각선이 서로 수직이다"),
    choice(Q["19"], "③", "평행사변형 — 두 대각선의 길이가 같다"),
    choice(Q["19"], "④", "사다리꼴 — 두 쌍의 대변이 각각 평행하다"),
    choice(Q["19"], "⑤", "정사각형 — 두 쌍의 대각의 크기가 각각 같다"),
    ans(Q["19"], "⑤"),
    sol(Q["19"], [
        "① 마름모의 이웃한 두 각은 보각(합 180°)이지 일반적으로 같지 않다.",
        "② 직사각형의 대각선은 길이가 같고, 수직은 정사각형(마름모)의 성질.",
        "③ 평행사변형의 대각선 길이가 같은 것은 직사각형의 성질.",
        "④ 두 쌍의 대변이 평행한 것은 평행사변형.",
        "⑤ 정사각형은 평행사변형이므로 두 쌍의 대각이 각각 같다 → 참.",
    ], ["사각형의 성질"]),
]

PLAN["20"] = [
    body(Q["20"], "평행사변형 ABCD의 AB의 중점 E에서 AC와 평행한 직선을 "
                  "그어 BC와 만나는 점을 F라 하자. △AEC의 넓이와 같은 "
                  "삼각형은? [5점]"),
    fig(Q["20"], "E는 AB의 중점, EF∥AC, F는 BC 위의 점"),
    choice(Q["20"], "①", "△AED"), choice(Q["20"], "②", "△AFC"),
    choice(Q["20"], "③", "△BCE"), choice(Q["20"], "④", "△CDF"),
    choice(Q["20"], "⑤", "△EFD"),
    ans(Q["20"], "②"),
    sol(Q["20"], [
        "EF∥AC이므로 △AEC와 △AFC는 밑변 AC를 공유하고 꼭짓점 E, F가 "
        "AC와 평행한 직선 위에 있다.",
        "평행선 사이의 거리가 일정하므로 두 삼각형의 높이가 같다 "
        "→ 넓이가 같다.",
    ], ["평행선과 넓이", "등적 변형"]),
]

PLAN["논술1"] = [
    fld(Q["논술1"], "type", SJ),
    ans(Q["논술1"], "76"),
    sol(Q["논술1"], [
        "(1-1) △MBD≅△MCE (RHS 합동) → ∠DMB=∠EMC=38°",
        "(1-2) ∠B=∠C=90°−38°=52° → ∠BAC=180°−104°=76°",
    ], ["RHS 합동", "삼각형 내각의 합"]),
]

PLAN["1-1"] = [
    fld(Q["1-1"], "parent_id", "q_e3390f7e5175"),  # fix wrong stem link
    fld(Q["1-1"], "type", SJ),
    ans(Q["1-1"], "RHS 합동"),
    sol(Q["1-1"], [
        "∠MDB=∠MEC=90° (수선의 발).",
        "M은 BC의 중점이므로 BM=CM.",
        "DM=EM (주어짐).",
        "빗변과 한 예각이 아닌 빗변·한 변이 같으므로 RHS 합동 → "
        "∠DMB=∠EMC.",
    ], ["RHS 합동"]),
]

PLAN["1-2"] = [
    fld(Q["1-2"], "parent_id", "q_e3390f7e5175"),  # fix wrong stem link
    fld(Q["1-2"], "type", SJ),
    ans(Q["1-2"], "76"),
    sol(Q["1-2"], [
        "∠DMB=∠EMC=38°.",
        "직각삼각형 MBD에서 ∠B=90°−38°=52°, 같은 방법으로 ∠C=52°.",
        "∠BAC=180°−52°−52°=76°.",
    ], ["삼각형 내각의 합"]),
]

# ---------- page 4 : 11~16 ----------

PLAN["11"] = [
    resolve("atu_c26b5dbded19",
            "평행사변형 ABCD에서 ∠C와 ∠D의 비율이 5:7이다. ∠A=x°, "
            "∠B=y°일 때, x−y의 값은? [4점]"),
    choice(Q["11"], "①", "-35"), choice(Q["11"], "②", "-30"),
    ans(Q["11"], "②"),
    sol(Q["11"], [
        "평행사변형에서 ∠C+∠D=180°이고 비율 5:7 → ∠C=75°, ∠D=105°.",
        "대각이 같으므로 ∠A=∠C=75°, ∠B=∠D=105°.",
        "x−y=75−105=−30.",
    ], ["평행사변형의 각"]),
]

PLAN["12"] = [
    resolve("atu_0044a37b233f",
            "평행사변형 ABCD에서 ∠D=60°이고, AD=14cm, CD=6cm, AB=AE일 때, "
            "x의 값은? [3점]"),
    fig(Q["12"], "E는 BC 위의 점, x=CE(cm)"),
    ans(Q["12"], "②"),
    sol(Q["12"], [
        "평행사변형의 대각이 같으므로 ∠B=∠D=60°.",
        "AB=AE이고 ∠B=60°인 이등변삼각형 ABE는 정삼각형 → BE=AB=CD=6cm.",
        "BC=AD=14cm이므로 CE=BC−BE=14−6=8 → x=8.",
    ], ["평행사변형", "정삼각형"]),
]

PLAN["13"] = [
    resolve("atu_29cf2e7f7d0e",
            "□ABCD가 평행사변형이 되는 조건으로 옳은 것은? (단, 점 O는 "
            "두 대각선의 교점) [5점]"),
    choice(Q["13"], "④", "∠A=108°, ∠B=72°"),
    choice(Q["13"], "⑤", "AB∥DC, ∠DAC=∠BCA"),
    ans(Q["13"], "⑤"),
    sol(Q["13"], [
        "⑤ AB∥DC이고 ∠DAC=∠BCA는 직선 AC에 대한 엇각이 같으므로 "
        "AD∥BC를 뜻한다.",
        "두 쌍의 대변이 각각 평행하므로 □ABCD는 평행사변형.",
        "나머지 보기는 평행사변형임을 보장하지 않는다.",
    ], ["평행사변형 판정", "엇각"]),
]

PLAN["14"] = [
    resolve("atu_b01c199b2c0b",
            "평행사변형 ABCD에서 CD의 중점을 E, 꼭짓점 A에서 BE에 내린 "
            "수선의 발을 F, BE의 연장선과 AD의 연장선이 만나는 점을 G라 "
            "하자. ∠ABF=53°, ∠EBC=25°일 때, ∠FDE의 크기는? [5점]"),
    choice(Q["14"], "①", "20°"), choice(Q["14"], "②", "22°"),
    choice(Q["14"], "③", "24°"), choice(Q["14"], "④", "26°"),
    choice(Q["14"], "⑤", "28°"),
    ans(Q["14"], "⑤"),
    sol(Q["14"], [
        "∠ABC=53°+25°=78°이므로 ∠BAD=102°, ∠ADC=78°.",
        "DE∥AB이고 DE=CD/2=AB/2이므로 △GDE∽△GAB의 닮음비는 1:2 → "
        "D는 AG의 중점.",
        "직각삼각형 AFG(∠AFG=90°)에서 D는 빗변 AG의 중점 → DF=DG=DA.",
        "△ABG에서 ∠AGB=180°−102°−53°=25°이고 △DFG는 이등변삼각형 → "
        "∠DFG=∠DGF=25°, ∠FDG=130°.",
        "∠GDC=180°−∠ADC=102°이므로 ∠FDE=∠FDG−∠GDC=130°−102°=28°.",
    ], ["평행사변형", "닮음", "직각삼각형 외심"]),
]

PLAN["15"] = [
    resolve("atu_d1fd83171882" if False else "atu_xx", ""),
]
PLAN["15"] = [
    choice(Q["15"], "②", "AC⊥BD"),
    choice(Q["15"], "⑤", "∠D=90°"),
    ans(Q["15"], "②"),
    sol(Q["15"], [
        "① AC=BD: 대각선 길이가 같으면 직사각형 ✓",
        "③ OA=OB이면 OA=OB=OC=OD → 대각선이 같고 서로 이등분 → 직사각형 ✓",
        "④ MB=MC이면 △ABM≅△DCM → ∠A=∠D=90° → 직사각형 ✓",
        "⑤ ∠D=90° → 직사각형 ✓",
        "② AC⊥BD는 마름모가 되는 조건이지 직사각형 조건이 아니다 → "
        "옳지 않은 것은 ②.",
    ], ["직사각형 판정", "마름모 판정"]),
]

PLAN["?6"] = [  # → printed number 16
    fld(Q["?6"], "number", 16),
    body(Q["?6"], "평행사변형 ABCD에서 EF는 AC의 수직이등분선이다. "
                  "AB∥EF, BC=14cm, CD=8cm일 때, CE의 길이(cm)는? [5점]"),
    fig(Q["?6"], "E는 AD 위, F는 BC 위의 점"),
    choice(Q["?6"], "②", "6"),
    ans(Q["?6"], "③"),
    sol(Q["?6"], [
        "EF는 AC의 수직이등분선이고 AB∥EF이므로 AB⊥AC → ∠BAC=90°.",
        "AB∥CD이므로 ∠ACD=∠BAC=90° (엇각).",
        "E는 AC의 수직이등분선 위의 점 → EA=EC. 직각삼각형 ACD에서 "
        "빗변 AD 위의 점 E가 A, C에서 같은 거리 → E는 외심이며 AD의 중점.",
        "CE=AD/2=BC/2=14/2=7(cm).",
    ], ["수직이등분선", "직각삼각형 외심", "평행사변형"]),
]


def main() -> int:
    # fetch head + content for ATU ids
    r = requests.get(
        f"{BASE}/api/v1/tenants/{TENANT}/documents/{DOC}/revisions",
        headers=HDR, timeout=15,
    )
    r.raise_for_status()
    head = r.json()["data"]["revisions"][-1]["id"]

    r = requests.get(
        f"{BASE}/api/v1/tenants/{TENANT}/documents/{DOC}/revisions/{head}",
        headers=HDR, timeout=15,
    )
    r.raise_for_status()
    cj = r.json()["data"]["content_json"]
    doc = json.loads(cj) if isinstance(cj, str) else cj

    # map question id -> {field -> atu_id} for unresolved ATUs
    atu_map: dict[str, dict[str, str]] = {}
    for q in doc["questions"]:
        m = {}
        for a in q.get("atus", []):
            if a["status"] in ("UNVERIFIED", "CONFLICT"):
                m[a["field"]] = a["id"]
        atu_map[q["id"]] = m

    # patch PLAN entries that need runtime ATU ids
    def res(qid_label: str, field: str, value) -> dict:
        aid = atu_map[Q[qid_label]].get(field)
        if not aid:
            raise RuntimeError(f"no unresolved {field} ATU on {qid_label}")
        return resolve(aid, value)

    PLAN["19"] = [
        res("19", "body", "여러 가지 사각형 중 그 성질에 옳게 연결된 것은? [4점]"),
    ] + PLAN["19"]
    PLAN["15"] = [
        res("15", "body",
            "평행사변형 ABCD에서 점 M은 AD의 중점이고 점 O가 AC와 BD의 "
            "교점이라 할 때, 직사각형이 되기 위한 조건으로 옳지 않은 것은? "
            "[5점]"),
    ] + PLAN["15"]

    order = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "?mark1",
             "논술2", "2-1", "2-2", "2-3", "논술3", "3-1", "3-2", "3-3",
             "17", "18", "19", "20", "논술1", "1-1", "1-2",
             "11", "12", "13", "14", "15", "?6"]

    for label in order:
        ops = PLAN[label]
        resp = requests.post(
            f"{BASE}/api/v1/tenants/{TENANT}/documents/{DOC}/changes",
            headers={**HDR, "If-Match": head},
            json={"ops": ops}, timeout=30,
        )
        if resp.status_code != 200:
            print(f"FAIL {label}: {resp.status_code} {resp.text[:400]}")
            return 1
        head = resp.json()["data"]["revision"]["id"]
        print(f"OK  {label}: {len(ops)} ops -> {head} "
              f"(rev {resp.json()['data']['revision']['revision_no']})")
    print("done, head =", head)
    return 0


if __name__ == "__main__":
    sys.exit(main())
