# WP11 — 독립 평가·파일럿·출시 상태 (2026-02)

## 코드/인프라로 완료된 것

| 항목 | 상태 | 증거 |
|---|---|---|
| Family 단위 분할 레지스트리 | DONE | `CORPUS_SPLITS.json`, `backend/eval/splits.py` — 스플릿 간 family 중복·holdout↔open 해시 누출·`sealed_at` 누락을 검증 에러로 처리 |
| 골드 접근 격리 | DONE | `backend/eval/bench/gold.py` 단일 게이트 + `test_restore10b.py` 회귀 스캔(프로덕션 경로의 gold 참조 시 빌드 실패) |
| 벤치마크 하니스 | DONE | `backend/eval/bench/` — char/critical-token exactness, source hallucination, layer metrics, runtime/memory, NOT_RUN/REVIEW 정직 기록 |
| Blind evaluation sealing | DONE | `backend/eval/blind.py` — 예측을 먼저 SHA-256 봉인하고 gold를 나중에 읽음; 봉인 후 수정 시 scoring 거부 |
| 릴리스 게이트 | DONE | `backend/eval/report.py` `evaluate_release_gate` — 미측정 항목은 PASS 불가, BLOCKED 사유 명시 |
| 합성 손상 코퍼스 생성기 | DONE | `backend/eval/bench/synth.py` — 필기/채점/블러/회전 + GT 마스크 쌍 |
| 실제 OCR observer 측정 | DONE(1회) | `docs/handoff/evidence/bench/bench_1789917623` — PaddleOCR char_exact 0.19, critical 142/172 (golden-001) |

## 코드로 완결 불가 — 외부 작업 필요 (BLOCKED)

| 항목 | 필요한 것 | 현재 상태 |
|---|---|---|
| 독립 holdout 코퍼스 | 개발에 사용하지 않은 실제 시험지 ≥30부/≥1,000 평가 단위 + 정답/해설 gold | `CORPUS_SPLITS.json` holdout 비어 있음 → 릴리스 게이트 **BLOCKED** (fail-closed, 정상) |
| 정확도 목표 확정 | §216: 99.5%/99%는 목표 제안값 — gold 규모·대표성 확인 후 책임자가 수치 고정 | 미측정(NOT_RUN). 목표를 낮춰 합격시키지 않음 |
| 실제 손상 시험지 성능 | synthetic 수치를 실제 성능으로 주장 금지 — 실제 필기/채점 시험지 측정 필요 | synthetic 생성기만 존재 |
| 운영 AI 공급자 승인 | 비용·데이터 전송 정책 승인 전 mock/로컬만 | PaddleOCR(로컬)만 승인된 상태로 간주 가능 |

## AT 게이트 매트릭스 (WP11 관련)

| AT | 내용 | 상태 |
|---|---|---|
| AT-058 | 성능·모델 평가 | PARTIAL — dev split만 측정, holdout 없음 |
| AT-059 | CI 회귀 | PASS(로컬) — backend 395 tests; PR CI 연결은 환경 작업 |
| AT-060 | 출시 인수 | NOT_RUN — 위 BLOCKED 항목 선결 필요 |

## 다음 단계

1. holdout 코퍼스 확보(외부) → `CORPUS_SPLITS.json`에 sealed 등록 → 게이트 재실행
2. RESTORE-10C 다중 observer 벤치: UniMERNet(Apache-2.0) 어댑터 추가 시 math OCR 비교 가능
3. 파일럿: 승인된 학원 1곳 + 동의된 데이터 정책 하에 실제 시험지 측정
