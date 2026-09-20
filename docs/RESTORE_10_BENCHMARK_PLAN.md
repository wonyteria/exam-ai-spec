# RESTORE-10_BENCHMARK_PLAN

Master Spec v3.1 §62 / RESTORE-10B·10C의 구현 계획(승인 전 계획안).

## 1. 목적

동일 damaged fixture에서 provider/알고리즘을 공정하게 비교하는 benchmark
harness. 결과로만 adapter 채택을 결정한다 (발견≠채택).

## 2. Fixture (실제 damaged 입력)

| 세트 | 내용 | 용도 |
|---|---|---|
| `golden_001` | 5p 실물 스캔 + expected.json + reference_draft | dev 회귀/벤치 |
| `gyenam-2025-imagepdf` | 7p image-only 실제 PDF | dev 벤치(텍스트 0자 확인됨) |
| synthetic corpus | Clean Renderer → 합성 필기/채점/열화 → GT 마스크 | layer/overlap 정량 평가 (§29) |
| sealed holdout | **미확보 — 큐레이터가 별도 확보·잠금** | release 판정 전용 |

Gold isolation 규약(코드 강제):
- `samples/gold/` 등 참조 디렉터리는 reconstruction path가 읽지 못한다.
  benchmark runner만 gold를 로드하고, 파이프라인 입력에는 damaged 자산만
  전달한다. 순서: DAMAGED INPUT → RESTORATION → RESULT FREEZE →
  GOLD 접근 → COMPARISON.
- `eval/splits.py`의 family/asset 해시 격리 검증을 CI에서 실행 —
  holdout family 자산이 dev/regression에 섞이면 빌드 실패.
- gold에 접근한 eval은 해당 세트를 regression으로 강등 기록한다 (§4 규칙).

## 3. 비교 대상 (1차)

| 축 | 후보 |
|---|---|
| OCR | PaddleOCR(기본 adapter) / Surya / olmOCR / KolmOCR / DeepSeek-OCR / 현재 stub |
| Math OCR | UniMERNet / TexTeller / Pix2Text / PaddleOCR formula |
| Layer separation | 현재 6-class 분류기 / WGM / printed-hw-segmentation / DocWaveDiff |
| Figure parsing | PGDP / OpenCV rule baseline(현행) |
| Preprocessing | 현행 3-variant / +deskew / +dewarp(DocTr++) / +shadow / +channel split |
| Layout/parsing | Docling / MinerU / ExamSplitter 방식 참고 |

## 4. Metrics (§34/§46 반영)

- **Text**: Character/Word/Question Exact, Critical Token Exact
  (문항번호·배점·부정어·부호·소수·단위·각도·선지 순서).
- **Math**: MathATU Exact, Digit/Operator Exact, AST Exact, Semantic
  (SymPy equivalence), latency, VRAM.
- **Layer**: PRINT RECALL, HANDWRITING PRECISION, OVERLAP RECALL,
  **PRINT_DESTRUCTION RATE**(인쇄를 필기로 오판해 지운 비율 — 최고 패널티).
- **Figure**: vertex/line/circle/label/intersection/parallel/perpendicular
  + relation exactness. Edge IoU 단독 불인정.
- **Preprocessing**: 미관이 아니라 OCR 정확도 개선·기하 보존·수식 보존.
- **Hallucination**: SOURCE_HALLUCINATION — 원본에 없는 텍스트/숫자/부호/
  수식/도형/조건/선지 생성률.
- **자원**: latency/page, peak memory, VRAM, API cost(외부 호출 시).

## 5. 실행/기록 형식

- run record: `commit + benchmark_version + split_hash +
  provider_config + renderer/worker_version` (기존 `eval/report.py` 재사용).
- 결과 항목: item_id, split(family), provider, variant, metric 값,
  status(PASS/FAIL/REVIEW/REJECT/NOT_RUN), latency/memory.
- 결과 저장: `docs/handoff/evidence/bench/<run_id>.jsonl` +
  요약 markdown. 원본·자동결과·사람수정후 결과를 구분.
- 부분 자료군(해외 보조·손글씨 조각·합성·negative)의 분모는 섞지 않는다.

## 6. 합격/탈락 기준 (adapter 승격 게이트)

- USE_THROUGH_ADAPTER 승격 조건:
  - dev fixture에서 Critical Token Exact ≥ 기존 baseline, AND
  - PRINT_DESTRUCTION == 0 on overlap fixtures, AND
  - SOURCE_HALLUCINATION == 0 on gold-checked items, AND
  - 라이선스 감사 통과 (registry Status ≥ USE_THROUGH_ADAPTER), AND
  - 로컬/승인된 경로로 재현 가능한 추론.
- 탈락: critical token 회귀, print destruction 발생, 라이선스 불명,
  holdout 대상 fixture에 대한 dev 누출.
- 벤치 성능이 synthetic만으로 도출된 경우 "합성 성능"으로 표기 —
  실제 시험지 성능 주장 금지.

## 7. RESTORE-10B 구현 범위 (승인 후)

1. `backend/eval/bench/` — fixture 로더, provider registry,
   metric 계산기(text/math/layer/figure), run recorder.
2. gold 접근 경계: benchmark 모듈만 `samples/gold`-류 경로를 import하도록
   패키지 분리 + 회귀 테스트(파이프라인 모듈이 gold 경로를 참조하면 실패).
3. synthetic damage generator v0 (합성 필기 스트로크·채점 마크·열화) —
   RESTORE-11 LayerDNA 벤치의 GT 공급.
4. 첫 실행: 현행 stub/PaddleOCR(설치 시) 대비 baseline 표 생성.
5. 결과는 dev split만. holdout은 확보·잠금 후 독립 QA가 실행.

## 8. 이번 세션의 한계

- 외부 모델 가중치 다운로드·실측 벤치는 미실행(네트워크/GPU 정책).
  본 문서는 계획이며 수치 주장을 포함하지 않는다.
- 라이선스는 repo의 LICENSE 파일 기준 1차 확인. 법적 확정은
  채택 시점에 별도 검토 필요.
