# RESTORE-00 — 복원 기술 베이스라인 & 실패 재현 (실행 기록)

실행일: 2026-09-20 / 기준 커밋: `9af7e91` (main, origin/main 대비 +3)
설계 계약: `docs/handoff/10_RESTORATION_TECH_DESIGN.md` (Codex lab 설계 복사본)

## 1. 기준 상태

- **HEAD**: `9af7e91` — 직전 세션의 미커밋 변경(실제 바탕쪽 파트 워터마크, Hancom 프로세스 소유권, 유효 PDF fixture)을 커밋해 기준을 고정. 이후 working tree clean.
- **테스트**: backend `python -m pytest tests -x -q` → **195 passed** (76.7s).
- **런타임**: Python 3.12.9, Windows + Hancom Office COM 사용 가능. `paddleocr`/`torch` 미설치, GPU 없음 — RESTORE-02 provider는 offline/mock로 시작.
- **보호 대상 dirty 파일**: 없음(모두 커밋됨).

## 2. 소스 자료 해시 검증

| 자료 | SHA-256 | 결과 |
|---|---|---|
| `2026 계남고 1-2 중간.pdf` (820,546 B) | `3c41e5fb…4a7` | 일치 |
| `2026-2학기중간-계남고1 (세움).hwp` (195,584 B) | `9b57f3b0…2b0` | 일치 |
| `…(진수학).hwp` (451,584 B) | `39205567…d6a5` | 일치 |
| 심원중 HWP + 사진 5장 (`심원중2`) | lab audit `494ca9d3…` | 존재 확인 (negative regression용) |

원본은 읽기 전용으로만 사용. 파이프라인 실행 전후 해시 동일 확인(`source_immutable: true`).

## 3. PDF 인벤토리 (pypdfium 직접 측정)

- 7페이지, 모든 페이지 `text_chars=0` — 완전 image-only.
- 페이지 크기 595×842pt. **촬영 이미지(책상 배경·그림자·원근)가 포함된 사진 기반 스캔** — 평판 스캔 가정이 성립하지 않음.

## 4. 기존 파이프라인 재현 (`restore00/run_baseline.py`)

입력: 원본 복사본을 job workdir에 두고 7 Page(`pdf_page_index` 0–6)로 Document 구성, providers 비움(offline).

| stage | 결과 | 비고 |
|---|---|---|
| preprocessing | ok 5.0s | 200dpi raster + grayscale/high_contrast/binarized variants 생성 |
| student_trace | ok 11.4s | trace mask + `trace_removed` 생성, print-overlap 가드 동작 |
| print_layer | ok | `clean_uri = trace_removed` (실제 복원 아님 — 설계 §7 지적과 일치) |
| segmentation | ok | provider 없음 → **문항 0개** |
| recognition | ok | **ATU 0개** |
| source_verification | ok | ATU 없음 |
| logic_verification / solving | ok | 대상 없음 |
| rendering | ok | 빈 preview + HWPX 생성됨 |
| export_verification | ok 5.5s | Hancom 워커로 HWP 역검증 시도 |
| zero_typo_gate | ok | **NEEDS_REVIEW** (정직한 fail-closed) |

소스 해시 불변, 총 26.2s.

### 페이지별 trace 마스크 결과

| page | trace px | 비율 | 인쇄 겹침 보존 영역 |
|---|---|---|---|
| 1 | 38,869 | 1.0% | 10 |
| 2 | 32,212 | 0.8% | 0 |
| 3 | 56,513 | 1.5% | 89 |
| 4 | 33,696 | 0.9% | 59 |
| 5 | 22,718 | 0.6% | 1 |
| 6 | 35,331 | 0.9% | 16 |
| 7 (정답표) | **386,852** | **10.0%** | **206** |

## 5. 재현된 결함 (콘택트 시트 증거 `contact_pN.png`)

- **D1 인쇄물 소거 위험**: trace mask가 정답표(7쪽)의 인쇄 표 테두리·정답 텍스트를 대량으로 "필기"로 분류(페이지의 10%). 문항 페이지에서도 인쇄 도형(Q10/Q11 벤다이어그램 원), 보기 표 테두리, 머리말 인쇄선이 마스크에 잡힘. `PRESERVE_PRINT_OVERLAP` 가드가 `<55` 코어는 살리지만 사진 노출로 얇아진 인쇄선·표선은 일부 소거됨 — lab 측정(도형 인쇄 픽셀 47.1%/34.0% 겹침)과 정합.
- **D2 페이지 역할 미분류**: 7쪽 정답·배점표가 문항 페이지와 동일하게 처리됨. 역할 확인·제외·manifest 반영 경로가 없음.
- **D3 recognition 무무장**: provider 없으면 문항 0/ATU 0 — 정직하지만 기능 없음. OCR은 candidate-only 어댑터로 추가 필요.
- **D4 `trace_removed`가 곧 clean**: print_layer는 복원이 아니라 마스크 적용본 전달. 가려진 인쇄 복원 경로 없음.
- **D5 source anchor 부재**: transform은 `pdf_raster` 기록뿐 — bbox→원본 픽셀 역추적 체인 미비.
- **D6 consensus 약식**: 단일 candidate `confidence≥0.9` → AUTO_VERIFIED — critical token 정책 없음.

## 6. 고정 사실 인벤토리 (lab gold manifest 인용)

- 페이지 역할: 1–6 QUESTION(문항 1–19 + 서술형), 7 ANSWER_KEY.
- 문항 구성: 객관식 19 + 서술형 부모 1/하위 3. 배점 합 94.0+6.0=100.0.
- 참조 HWP: 수식 스크립트 각 213개, 서열 일치; 점수 앵커 19; 서술형 마커 1. 선택지 17개 수식 토큰 일치, 조합형 8/12번 자동 감사 제외.
- 심원중: HWP 점수 19개 vs 원본 객관식 20개, Q12 `[3점]` 누락 — 참조도 오류 가능(oracle 금지).
- 참조 HWP는 **candidate reference**이지 source truth가 아님.

## 7. 다음 WP

**RESTORE-01** — provenance/source anchors + PDF 페이지 인벤토리:
- `RawSource`/`PdfPageInventory`/`TransformChain`/`SourceAnchor` 모델, 페이지별 text/vector census, `image_only` 플래그.
- DoD: 모든 crop/bbox가 원본 픽셀 좌표로 역추적, 소스 해시 불변, 실패 페이지는 silent-skip이 아니라 review/block.
- Blocker: OCR provider 없음(RESTORE-02에서 mock→PaddleOCR offline 평가 순서로).
