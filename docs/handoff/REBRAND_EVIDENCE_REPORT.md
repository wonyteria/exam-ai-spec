# HWP/HWPX 안전 리브랜딩 — 구현·검증 보고 (AT-061)

범위: `docs/handoff/HWP_REBRANDING_SPEC.md` — 타학원 HWP/HWPX의 상단 제목을
현재 학원명으로 교체, 모든 페이지 중앙에 학원 로고 behind-text 워터마크,
쪽번호만 제거. 원본 불변·structure census·사용자 후보 확인·allowlisted
mutation·실제 Hancom proof·허용 mask 밖 diff 0.

## 구현 범위

- `backend/rebranding/`: `models`, `scanner`, `planner`, `hwpx_mutator`,
  `proof`, `hwp_worker_operation`, `fixtures`
- `backend/document/page_roles.py`: PDF 페이지 역할 분류
  (QUESTION / ANSWER_KEY / UNKNOWN, 이미지 전용 페이지는 UNKNOWN으로
  보류 — 조용히 문제 페이지로 추정하지 않음)
- `backend/app/api/rebrand.py`: tenant/revision/artifact 계약 위의
  import·scan·confirm·apply API
- `frontend/app/rebrand/`: 후보 확인 UI
- `backend/renderers/hwp/worker.py`: COM watchdog, spawned-PID 추적,
  timeout 시 해당 작업 프로세스만 종료

### 구조 센서스가 다루는 실제 형상

| 구조 | 후보 kind | 처리 |
|---|---|---|
| 머리말 직접 텍스트 | TITLE_HEADER_TEXT | 확정 시 REPLACE_TEXT_RUNS |
| 머리말 표 셀 텍스트 | TITLE_HEADER_TABLE_CELL | 선택 셀만 교체 |
| 머리말 글상자(container>rect>drawText) | TITLE_HEADER_TEXT | 확인 필수 |
| 바탕쪽 텍스트/글상자 | TITLE_MASTER_TEXT | 확인 필수 |
| 본문 상단 단락/글상자 | TITLE_BODY_TOP | 확인 필수 |
| 머리말/바탕쪽/본문 글상자 그림 | TITLE_IMAGE | 확인 시 REPLACE_SELECTED_SHAPE |
| 셀 배경 이미지(borderFill, header.xml) — 머리말·바탕쪽·본문 표 | TITLE_IMAGE | 확인 시 REPLACE_CELL_BACKGROUND — 공유 fill을 복제해 확인된 셀만 재지정, 다른 셀의 fill은 바이트 동일 |
| pageNumCtrl / pageNum | PAGE_NUM_CONTROL | REMOVE_PAGE_NUM_CONTROL |
| header/footer/master autoNum·fieldBegin PAGE | PAGE_NUM_FIELD | REMOVE_PAGE_NUM_FIELD |
| 리터럴 번호 텍스트 | LITERAL_PAGE_NUMBER | 확인 필수, 자동 제거 금지 |
| settings.xml printHeader/printFooter `^p` 토큰 | PRINT_PAGE_TOKEN | 확인된 블록만 스크럽 |

- 후보 id는 결정적(종류+섹션+경로+digest 해시) — 스캔과 계획 사이에
  확인 id가 안정적으로 유지된다.
- 글상자 내부 경로(`container[i]/rect[j]/drawText[k]/sublist/p[m]/run[n]`)는
  동명 형제 인덱스로 기록되며 mutator가 정확히 해석한다.
- mutator는 변형 전 모든 대상의 digest를 pin하고, 허용 mask 밖 변경은
  digest-multiset 비교로 탐지하여 산출물을 생성하지 않는다.

## 검증 결과 (실측)

- `python -m pytest tests/test_hwp_rebranding.py` → **42 passed**
- `python -m pytest tests/` (전체 백엔드) → **190 passed**
- `npx eslint` (rebrand 페이지+spec) → clean, `npm run build` → PASS
- `npx playwright test` → **9 passed** (`rebrand.spec.ts` 3개 신규:
  가져오기→후보 확인→적용 계약, fail-closed 오류 표시, source flag 배너)

### 실제 Hancom 증거 — `backend/data/local_evidence/` (gitignored)

`run_local_proof.py`는 복제본에 대해 HWP→HWPX 변환→센서스→확정/거절 시뮬레이션→
계획→변형→HWPX→HWP→재열기→PDF 렌더를 수행한다. 원본 SHA-256 불변,
산출물 hash 바인딩, spawned-PID 잔류 0을 매 실행 검증한다.

| 파일 | 결과 |
|---|---|
| `2026 계남고 1-2 중간.pdf` (7쪽) | PAGE_COUNT_MATCHES_VISUAL_REVIEW / EVERY_PAGE_REPRESENTED / ANSWER_PAGE_ROLE_USER_CONFIRMABLE — **PASSED**. 7쪽 전원 매니페스트 포함, 이미지 전용 페이지는 UNKNOWN 보류, 7쪽 정답표는 ANSWER_KEY로 확인 가능 |
| `2026-2학기중간-계남고1 (세움).hwp` | HWP_OPEN_SAVEAS_HWPX, OUTSIDE_MASK_DIFF_ZERO, SOURCE_IMMUTABLE, FORMAT_OPEN_VALIDITY, FORMAT_CONVERSION_PROVENANCE, HWP_ACTUAL_REOPEN, ARTIFACT_HASH_BINDING, PROCESS_LEAK_ZERO, PAGE_COUNT_PRESERVED — **전부 PASSED**, 출력 PDF 7쪽 |
| `…공통수학2 (진수학).hwp` | 동일 체크 **전부 PASSED**, 출력 PDF 6쪽 |

proof 체크(두 파일 공통): SOURCE_IMMUTABLE / CONTROL_MANIFEST_BOUND /
PLAN_ALLOWLIST_ONLY / OUTSIDE_MASK_DIFF_ZERO / HWP_ACTUAL_REOPEN /
HWP_PDF_RENDER / PROCESS_LEAK_ZERO — PASSED.

### 운영자 확인 시뮬레이션(증거 스크립트의 선택 규칙)

- 외국 조직명(계남·세움·진수·학원·교육원·아카데미)이 든 제목 후보만 확인
- 시험 메타데이터(고사·학년 표기)와 문제 단락은 거절 — 거절 후보는
  바이트 동일하게 보존되며 census에는 전부 공개됨
- 셀 배경 로고(borderFill) 후보는 확인 시 복제-재지정으로 실제 교체

세움: `2026 계남고1` 머리말 셀 → `테스트학원` 교체, `고등 1학년 수학`·
`2학기 중간고사` 시험 정보 보존, `pageNum` 제거, 세움 로고 셀 배경
(`borderFill id=6` → 복제본으로 재지정)은 **실제 브랜드 로고로 교체** —
원본 fill은 다른 셀을 위해 바이트 동일 보존. 진수학: 머리말·본문 글상자의
`계남고 1 공통수학2` → `테스트학원` 교체, 시험 정보 보존, 두 개의
진수학 로고 pic → 브랜드 로고, 중앙 워터마크 병합. 렌더링된
`{seum,jinsu}/rebrand_page1.png`로 시각 확인 완료.

## 한계 / BLOCKED·NOT_RUN

- 셀 배경 이미지(borderFill) 교체는 지원 — 단, 참조 fill에 이미지가
  없거나(`STRUCTURE_UNSUPPORTED`) `header.xml`이 없거나(`PATH_MISS`)
  스캔 후 `borderFillIDRef`가 바뀐 경우(`DIGEST_MISMATCH`)는
  여전히 fail-closed.
- COM 세션은 Hancom 보안/승인 다이얼로그를 watchdog이 닫으며 완주 —
  무인 환경의 다이얼로그 정책 차이는 운영 환경에서 추가 검증 필요.
- Hancom 버전별 HWPML 렌더 차이, 대용량 다중 섹션 문서는 실물 표본이
  더 필요 — synthetic fixture는 회귀용, 실물 증거는 로컬 전용.
- `/rebrand` 브라우저 E2E는 3개 시나리오 추가·통과 — 실제 파일을
  올리는 end-to-end(실제 백엔드+COM)는 로컬 증거 스크립트로만 검증됨.

## 산출물 위치

- `backend/data/local_evidence/evidence.json` — 해시·후보·거절·체크·proof
- `backend/data/local_evidence/{seum,jinsu}/` — scan.hwpx, rebranded.hwp/hwpx/pdf, rebrand_page1.png
- `backend/data/local_fixtures/` — 원본 복제본 + SHA-256 (`SOURCE_HASHES.json`)
- 원본 사용자 파일은 읽기 전용 참고 — 절대 덮어쓰지 않음
