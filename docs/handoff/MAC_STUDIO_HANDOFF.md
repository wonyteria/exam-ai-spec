# Mac Studio 이관 핸드오프 (2025-XX-XX)

Windows 개발 머신(D:\플랫폼\exam_ai_spec)에서 Mac Studio로 작업을 이어가기 위한
실제 상태·설정·제약 요약. git에 없는 것들이 핵심이다.

## 1. 코드

- repo: `https://github.com/wonyteria/exam-ai-spec` — `main` @ `90b2012` push 완료
- hwpilot은 별도 repo(프로젝트 외부): `git clone https://github.com/devxoul/hwpilot`
  → 예: `exam_ai_spec/tools/hwpilot`. bun 필요 (`bun run typecheck` / `bun test src/`)

```bash
git clone https://github.com/wonyteria/exam-ai-spec
cd exam-ai-spec/project
```

## 2. git에 없는 것 — 수동 복사 필수

| 대상 | 크기 | 내용 |
|---|---|---|
| `backend/.env` | — | `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.1-flash-lite`, `GEMINI_MODEL_SOLVER=gemini-3-flash-preview`, `EXAMDNA_ENABLE_GEMINI=1` (+ OpenAI 등) |
| `backend/data/` | ~395MB | canonical.db(실제 문서 상태), 업로드 원본, 크롭, exports, local_evidence |

- `backend/data/` 없이는 실제 문서(doc_8dc95bea7fcb, rev 67)가 존재하지 않음.
  AirDrop/rsync/scp로 통째로 복사.
- `.env`의 Gemini 키는 대화 로그에 노출된 적 있음 — 이관 후 회전 고려.

## 3. macOS에서 되는 것 / 안 되는 것

| 기능 | macOS | 비고 |
|---|---|---|
| FastAPI 백엔드, canonical, 검수, export flow | O | `uvicorn app.main:app --port 8871` |
| Next 프론트 | O | `npm run dev` :3000 |
| HWPX 읽기/쓰기, hwpilot 변환·리드백 | O | 크로스플랫폼 |
| **한컴 COM (HWP_ACTUAL_REOPEN)** | **X** | `renderers/hwp/worker.py` — Windows 전용. Mac에서는 `HWPWorkerUnavailable` → 증명이 `NOT_RUN`/`BLOCKED`. fail-closed로 HWP final export 불가 |
| PaddleOCR fidelity audit | △ | mac 설치 가능하나 ARM 환경 검증 필요 — 없으면 `ORIGINAL_SOURCE_FIDELITY`는 NOT_RUN(정상 fail-closed) |
| Gemini solver | O | API 호출이라 플랫폼 무관 |
| **로컬 LLM solver** | **O — 이번 이관의 핵심** | Mac Studio가 Ollama/LM Studio 호스트 → `localhost` 호출로 무료·프라이빗 독립 solver |

## 4. 서버 띄우기

```bash
cd project/backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # pyproject deps: fastapi, uvicorn, pypdfium2, openai, google-genai, ...
uvicorn app.main:app --port 8871 --reload

cd ../frontend
npm install && npm run dev        # :3000, NEXT_PUBLIC_API_URL 비우면 same-origin 프록시 경로 사용
```

- E2E: `npx playwright test` (dev 서버 자동 기동, 18개 통과 확인됨)
- 백엔드 테스트: `cd backend && pytest` — Windows에서 456 passed / 1 skipped.
  Mac에서는 win32 의존 테스트가 skip/실패로 갈 수 있음 → 실패 목록 비교 필요.

## 5. 현재 실데이터 상태 (복사했다면)

- tenant `tn_19e257c96c4b`, doc `doc_8dc95bea7fcb`, head rev **67**
- 콘텐츠 체크 11개 전부 PASSED, HWPX/HWP/PDF 3종 final export 완료(Windows 한컴 증명 포함)
- Mac에서는 HWP 포맷의 final eligibility가 NOT_RUN으로 떨어지는 게 정상 — 버그가 아님

## 6. 다음 작업 (우선순위)

1. ~~로컬 LLM solver 어댑터~~ → **구현 완료(§8)** — 남은 건 Mac Studio에
   Ollama + 모델을 띄우고 31문항 코퍼스로 Gemini 대비 일치율을 실측하는 것뿐.
2. Gemini 무료티어 503(수요 폭주) — 재시도로 흡수 중, 로컬 solver로 보강 가능
3. Gemini 키 회전(노출 이력) + `.env` → 안전한 시크릿 관리
4. 독립 holdout 코퍼스 확보, EasyOCR 라이선스 결정
5. HWP 최종 증명은 Windows 한컴 머신에서만 가능 — Mac 단독 출시 시
   HWP는 `NOT_RUN` 명시 유지(절대 PASS로 위장 금지)

## 7. 인증/접속

- dev auth: `localStorage`의 `examdna_dev_user`/`examdna_tenant` + dev stub 헤더.
- 실데이터 문서는 `data/` 복사 후 기존 tenant로 로그인하면 그대로 보임.

## 8. 맥스튜디오 = LLM 서버로만 쓰기 (LAN 연결) — 구현 완료

프로젝트를 Mac에 옮기지 않고 **Windows 백엔드 → Mac Studio의 Ollama/LM Studio를
LAN으로 호출**하는 경로. `providers/local/provider.py`가 OpenAI 호환
chat-completions 어댑터(`solve`/`solve_batch`/`complete`)로 이미 구현돼 있고
`jobs/runner.py`가 `EXAMDNA_ENABLE_LOCAL_LLM=1`일 때 solver·reasoning 목록 맨 앞에
등록한다. 학생 시험지가 외부 API로 안 나가는 유일한 solver 경로.

### Mac Studio 측 (한 번만)

맥에 이미 로컬 LLM 서버가 있다면 그걸 쓴다. **실제 설치 모델(확인됨)**:

| alias | 모델 | 용도 |
|---|---|---|
| `local-small` | Qwen3 4B (Q4_K_M) | 너무 약함 — solver 비추천 |
| `local-large` | Qwen3.5 27.8B (NVFP4) | **solver 기본** |
| `local-long` | Qwen3.5 27.8B, 긴컨텍스트 | 대배치/긴 프롬프트용 예비 |

없을 때 설치하는 경우:

```bash
# Ollama — 외부 바인딩 필수 (기본은 localhost만 들음)
OLLAMA_HOST=0.0.0.0 ollama serve
ollama pull qwen3:32b
# LM Studio라면: 개발자 탭 → Start Server → "Serve on local network" 체크
```

`ifconfig | grep "inet "`로 맥 IP 확인. 서버 포트 확인: Ollama 11434 /
LM Studio 1234 / llama.cpp 8080. **포트를 공인망에 열지 말 것**.

### Windows 측 `backend/.env`

```dotenv
EXAMDNA_ENABLE_LOCAL_LLM=1
LOCAL_LLM_BASE_URL=http://<맥-IP>:<포트>/v1
LOCAL_LLM_MODEL=local-large       # 27.8B — solver용
# LOCAL_LLM_TIMEOUT=600
# LOCAL_LLM_DISABLE_THINKING=1    # <think> 생략(지원 서버만)
```

### 연결 확인

```powershell
# Windows에서 맥에 도달하는지:
curl http://192.168.0.10:11434/v1/models        # 모델 목록이 오면 연결 OK
```

백엔드 재시작 후 `default_providers()`의 `solver[0]`이 `local-llm`이면 등록 완료.

### 동작/실패 규약

- 프롬프트·JSON 복구는 `providers/gemini`의 상수/`_parse_json` 재사용 →
  프롬프트 변경이 모든 백엔드에 일관 적용.
- 10문항 청크, `<think>` 블록 제거, 파일 캐시(`data/cache/local_llm/`),
  재시도 시 nonce로 캐시 우회.
- 맥이 꺼지거나 타임아웃 → solver 예외 → `run_checks`가 `NOT_RUN`으로 기록
  (500 크래시 아님, fail-closed 유지). Gemini가 목록에 남아 있지만
  `solvers[0]`만 쓰므로 **로컬이 죽으면 자동 fallback이 아니라 NOT_RUN** —
  의도된 동작(로컬만 믿기로 한 상태에서 조용히 외부 API로 새는 것 방지).
- 도입 전 **31문항 코퍼스로 Gemini 대비 일치율 실측** 후 게이트 승격 여부 결정.

### 알려진 주의점

- `response_format={"type":"json_object"}`: Ollama·LM Studio 최신판 지원.
  구버전 Ollama는 무시하고 프리폼 텍스트 반환 → `_parse_json` 복구가 흡수,
  그래도 실패 시 3회 재시도 후 빈 결과(=검증 불가, FAILED로 정직 처리).
- 비전 모델이 아니면 OCR/vision 역할에 넣지 않음 — 현재 등록은 solver·reasoning뿐.

## 9. 문항 중심 복원 레이어 (신규)

### 상태 모델
- 문항 상태(`document/models.py`): `AUTO_RESTORED`, `AUTO_CORRECTED`,
  `NEEDS_USER_REVIEW`, `USER_EDITED`, `USER_CONFIRMED`, `BLOCKED`.
- 문서 상태: `RESTORED_BEST_EFFORT` / `NEEDS_USER_REVIEW` /
  `READY_FOR_FINAL_EXPORT` — 근거(ATU, 교정 플래그, logic flag, 사용자 편집,
  차단된 스테이지)로부터 파생. 스테이지가 "돌았다"로 판단하지 않음.
- 파생 로직: `document/restoration.py`. ATU 해소 시 연결된 이슈도 함께 제거됨.

### 교정 스테이지
- `core/examdna/correction.py` + `correction_stage.py`, 파이프라인에서
  `source_verification` 직후 실행.
- 자동 교정: 선택지 라벨 중복, 음수 기호 누락, OCR 오탈자, 줄 결합,
  단위/기호 정규화(㎝·㎜·˚·⊿·< 등), 선택지 순서, 하위 번호.
- 자동 확정 금지: 의미 변경 숫자, 도형 치수, 필기 겹침(uncertain_regions 중
  reconstruction이 REVIEW_REQUIRED로 남긴 것만), 완전 가림, 다해석 수식
  → `NEEDS_USER_REVIEW`.

### 문항 API (`app/api/documents.py`)
- `GET /documents/{id}/restoration/summary` — 상태 카운트 + 문제 문항만.
- `GET /documents/{id}/questions/{qid}` — crop 경로 + 구조화 필드 + 이슈.
- `POST .../questions/{qid}/edit` — 자연어 명령 → canonical op 미리보기
  (store 미변경), `POST .../edit/confirm` — revision 생성 + `USER_EDITED`.
- 타깃 해소: 정확한 ID > 유일 번호/라벨 매치 > 모호하면 409. 복수 문항에
  조용히 적용하지 않음.

### 자연어 파서 (`agent/question_ops.py`)
- `①번 보기를 -35로 수정해`, `배점을 5점으로`, `정답을 3번으로`,
  수식/본문/도형라벨 → `SetChoice`/`SetPoints`/`SetAnswer`/`SetEquation`/
  `SetBody`/`SetField`.
- canonical op 신규: `SetQuestionStatus` (`canonical/models.py`,
  `canonical/service.py` — `figure_label` SetField 처리 포함).

### 로컬 모델 라우팅 (`providers/local/router.py`)
- 기본 `local-large`; 긴/서술형 문항은 `local-long`.
- `local-small`은 solver로 만들지 않음. 동일 모델 응답은 독립 근거 2회 계산 금지.
- bounded concurrency(semaphore) + `.model` 프로퍼티로 기존 테스트 호환.
- `jobs/runner.py`의 `default_providers`에서 ALT 슬롯은 독립 근거로 유지.

### 다운로드 정책
- final export는 기존 `_require_verified_final` fail-closed 유지.
- best-effort draft 다운로드(JSON/HWPX/DOCX/PDF)는 검토 필요 문항이
  남아 있어도 허용 — 응답에 review 카운트 노출, `VERIFIED_FINAL` 표기 금지.

### 프론트
- `app/documents/[id]/review/page.tsx` + `components/QuestionReview.tsx`:
  상태 카운트, 문제 문항만 기본 표시, 문항 상세(crop+필드+이슈),
  자연어 수정창, 전/후 미리보기, 명시적 적용.
- `components/Modal.tsx`: 긴 내용 스크롤 처리. export 페이지에
  best-effort 다운로드 섹션 + 검토 카운트.
- `playwright.config.ts`: `E2E_BASE_URL`/`PORT` 환경변수로 포트 변경 가능
  (로컬 3000 충돌 시).
- 주의: Chromium이 same-origin `download` 클릭에서 `page.route` 모킹을
  우회함 → 다운로드 E2E는 href/contract를 검증해야 함(wp09 스펙 참조).

### 벤치마크
- `backend/eval/bench/simwon_bench.py` — `samples/심원중 샘플/` 5장,
  31문항 recall·필드 정확도·상태 카운트·시간 측정.
  기준 HWP는 런타임 입력이 아니라 평가용.

### 관측자(Observer) 다양성 — Tesseract
- `providers/ocr/tesseract.py` + `providers/vision/tesseract_page.py`:
  시스템 `tesseract` 바이너리(TSV 모드, 패키지 불필요, `kor` traineddata 필요).
  LSTM 계열이라 VLM/Paddle과 다른 엔진 → consensus에서 진짜 독립 소스로 인정.
- `EXAMDNA_TESSERACT=1`로 opt-in (vision get_page_extractors + ocr get_providers).
- 라벨 정규화 `segmenter.normalize_label`: `논술2`/`논술형 2` 등 별칭 통일,
  엔진 간 같은 영역이 라벨만 달라 중복 문항이 되는 것 방지.

### 심원중 벤치 결과 (eval/bench/out/simwon_final, 2026 측정)
- 31/31 실제 문항 분리 + `?mark1` 모호 앵커 1개(검토용, 정상) → recall 1.0
- ATU 합의: AUTO_VERIFIED 10 / CONFLICT 8 / UNVERIFIED 268
  (local VLM + tesseract 2-엔진 일치 필드만 자동 확정)
- field_accuracy (gold: `samples/심원중 샘플/expected.json` —
  `eval/bench/extract_simwon_gold.py`가 HWP 바이너리의 EQEDIT 레코드에서
  수식 스크립트까지 복구한 31문항 전체 gold):
  - points 1.0, choice_exact 0.979, figure_label_recall 0.80,
    critical_token_recall 0.77, body_exact 0.45 (CONFLICT 본문은
    fail-closed로 비워 둠 → 정직한 저점수)
  - answer 0.0 — solver는 검증된 문항만 푸는데 전부 미검증이라 skip(정상)
- 상태: 전 문항 NEEDS_USER_REVIEW. 잘못 자동 확정 0. 문서 NEEDS_USER_REVIEW.
- 교정 발동: bogee_consonant ×6 (ㄱ/ㄴ/ㄷ→가/나/다 오독 교정 —
  gold 비교로 발견, `<보기>`/자음 마커 증거 있을 때만), ocr_typo ×3
- 시간: warm cache ~68s / cold ~1245s (VLM page extraction·trace가 지배)
- 문항별 비교 리포트: `eval/bench/out/simwon_final/comparison_report.md`
- VLM page prompt v2: figure 라벨·equations를 후보로 추출
  (figure_label_recall 0→0.80)
- Q12는 원본에 [N점] 태그 없음, 3-3은 배점 없음.
- 잔여: 손상된 한국어 사진에서 tesseract 정확도가 낮아 본문 필드는
  대부분 CONFLICT/UNVERIFIED — PaddleOCR/EasyOCR 같은 세 번째 독립
  엔진 추가 시 자동 확정 비율 상승 예상.
