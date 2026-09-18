# WP00 — 기준 확정·환경 검사·회귀 기반 (실행 기록)

실행일: 2026-09-19 / 기준 커밋: `0c1fb5dc8223d52889ca676bed13ad2e7d93fa4a`

## 1. Git·환경 기준

- HEAD = `0c1fb5d` (감사 기준 커밋과 동일), working tree clean, `origin/main`과 동기화. 기준 이후 변경 없음.
- Python 3.12.9, pytest 9.1.1, Node/npm(Next 16.3.5, Turbopack), Windows(Hancom Office 2020 설치됨).
- `__pycache__` 잔여 바이트코드가 과거 경로(`D:\Devin\Exam_ai_spec\...`)를 traceback에 표시 — 실행 환경 자체 문제 아님.

## 2. Baseline 측정 결과

| 검사 | 명령 | 결과 |
|---|---|---|
| backend pytest | `cd backend && python -m pytest -q` | **수정 전:** 21 passed, 1 error (`test_golden_replay`: `ModuleNotFoundError: google` — google-genai 미설치 환경에서 SDK import 경로 진입, A34) → **수정 후: 26 passed, 0 fail** |
| frontend lint | `cd frontend && npm run lint` | **수정 전:** 1 error (`react-hooks/set-state-in-effect`, `review/page.tsx:63`, A36) → **수정 후: clean** |
| frontend build | `cd frontend && npm run build` | PASS (TypeScript 포함) |

## 3. A/S 유효성 대조 (WP00 범위)

- A33 — harness가 `missing` 문항을 regression에 미포함 → `harness.py` 수정으로 missing>0도 regression 처리.
- A34 — replay cache miss 시 실제 SDK 호출 경로 존재 → `tests/golden/replay.py`의 `CacheReplayProvider`로 교체. SDK 미설치 환경에서도 동작, miss는 `CacheMiss` 즉시 실패, 네트워크 경로 없음.
- A36 — `review/page.tsx` effect 내 동기 setState → cancelled-flag 구독 패턴으로 수정.
- S02 — seeded expected의 오답 7개(2·4·8·9·10·14·20)를 `reference_draft.json`의 독립 기준과 대조해 `test_seeded_baseline.py`로 고정. seeded가 조용히 "수정"되거나 새 drift가 생기면 실패.
- S03 — seeded 29행/114점 ≠ 요구 31노드/28채점단위/100점. 행 수를 합격 기준으로 쓰지 않도록 테스트로 고정.
- S10 — `reference_draft.json`은 `F2_DRAFT_PENDING_INDEPENDENT_REVIEW` 상태. `must_not_feed_model_input: true` — 모델 입력·평가 오라클 주입 금지를 데이터에 명시.
- S11 — replay provider name은 `replay_cache`로 기록해 cache provenance를 live 추론과 구분.

## 4. HWP 최소 기술 검증 (W 증거)

실행: `python backend/scripts/hwp_tech_check.py <out_dir>` → `backend/data/hwp_tech_check/tech_check_result.json`

| 항목 | 결과 |
|---|---|
| 한글 버전 | Hancom Office 2020, `HWPFrame.HwpObject` v11.0.0.2129, COM 등록 확인 (`HwpAutomationApp2`, `HWPCONTROL`, `HWPEQ5X`도 등록) |
| 수식 객체 | `HAction "EquationCreate"` + `HEqEdit.string`/`BaseUnit=1100` → `<hp:equation baseUnit="1100" font="HYhwpEQ"><hp:script>…` 실제 객체 생성 (11pt = baseUnit 1100, 100 units/pt) |
| 벡터 도형 | `HAction "InsertLine"` + `HShapeObject` → `<hp:rect>` 그리기 개체 생성 |
| 미주 | `HAction.Run("InsertEndnote")` → `<hp:endNote>` 실제 미주 객체 + autoNum |
| 저장·재열기 | `SaveAs(path,"HWPX")` → 유효 zip; `SaveAs(path)` → HWP 바이너리; `Open(hwp)` 재열기 성공 |

알아낸 제약(WP08 입력):
- 수식 삽입 action id는 `InsertEquation`이 아니라 **`EquationCreate`** (구형·신형 API 모두). `HAction.Execute` 반환값 False를 검사해야 함.
- 문서 창이 숨겨진 상태(`XHwpWindows.Visible=False`)에서 EquationCreate가 블로킹 — worker는 창 표시 또는 세션 정책이 필요.
- `SaveAs`는 확장자가 아니라 **format 인자**로 HWPX/HWP를 결정. 기존 파일 덮어쓰기는 확인 대화상자로 블로킹 가능 — 작업 디렉터리를 매번 새로 생성.
- 파일 열기 보안 대화상자는 `RegisterModule("FilePathCheckDLL", …)` 정책이 필요할 수 있음 — 이번 세션 저장본 재열기는 대화 없이 통과했으나 운영 worker에서 별도 검증 필요.
- pywin32는 현 환경에 미설치였으며 dev/QA + 중앙 worker 의존성으로 추가함 → ADR-0005.

## 5. 운영 결정표 (확정된 것 / 제안 / 보류)

| 항목 | 상태 | 결정 |
|---|---|---|
| 지원 입력 | 제안 고정 | JPG/PNG + 페이지 PDF. BMP/WebP는 회귀 통과 시 capability로만 개방. HEIC·암호PDF·손상파일 거절 |
| 파일 상한 | 제안 고정(측정 후 조정) | 파일당 50MiB, 문서당 50쪽/200MiB, 디코드 후 40MP, AI 재시도 최대 2회 |
| 수식 범위 | 제안 고정 | AST: number,variable,unit,operator,relation,fraction,power,root,group,segment,angle,triangle,quadrilateral,degree. 미지원은 `UNSUPPORTED_MATH` issue로 final 차단 |
| 도형 범위 | 제안 고정 | point/segment/polyline/circle/arc/bezier/text/math-label/right-angle/tick/arrow/fill-pattern primitives. 표·좌표 그래프(축/눈금/점/선/라벨) |
| QA 제안 수치 | 제안(07 문서 그대로) | 자동처리 기준: 인쇄 텍스트 99.5%·도형 관계 98%·풀이 95%, 최종 critical 0. 평가 30시험/1000채점단위 — RG-07/RG-10에서 고정 |
| 운영 AI | 보류(RG-03) | OpenAI Responses adapter 기본안(gpt-5.6-luna 추출 / terra 검증 후보). 계정·단가·예산 승인 전까지 mock/cache-only |
| 인증 | 보류(RG-02) | 서버 세션 + tenant membership interface 먼저 구현, 외부 인증 서비스는 승인 후 연결. 자체 비밀번호 보관 구현하지 않음 |
| 저장소 | 제안 고정 | PostgreSQL + private object storage + DB durable queue (ADR-0001). 로컬 dev는 SQLite/로컬 FS 병행 |
| Windows 한글 | 환경 확인 완료, 운영 보류(RG-05) | 이 개발기에서 COM 검증 통과. 운영 서버 라이선스·계정·헤드리스 조건은 운영 결정 |

## 6. 남은 blocker

- RG-01~RG-10은 `docs/handoff/07_DECISIONS_AND_RELEASE_GATES.md` §3 그대로 — 외부 가입/결제/학생 원본 전송/공개 배포는 승인 전까지 수행하지 않음.
- F1 실물 원본(JPG 5장·참고 HWP)은 `evidence/RESTRICTED_DATA_MANIFEST.md` 대로 별도 관리 — 이 저장소·로그·공개 이슈에 넣지 않음.
- HWP 자동화는 이 개발기에서 확인됐으나 중앙 worker 자격증명·헤드리스 정책은 RG-05 보류.
