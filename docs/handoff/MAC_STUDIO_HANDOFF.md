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

1. **로컬 LLM solver 어댑터** — `providers/local/provider.py` 신설:
   Ollama `http://localhost:11434/v1/chat/completions` 호출(Responses API 아님 —
   `providers/openai`는 재사용 불가, `providers/gemini`의 `_SOLVE_PROMPT`/
   `_SOLVE_BATCH_PROMPT`/`_parse_json` 재사용). `runner.py`에 등록.
   추천 모델: `qwen3:32b` 또는 `qwq:32b`. 31문항 실측 후 Gemini와 일치율 비교.
2. Gemini 무료티어 503(수요 폭주) — 재시도로 흡수 중, 로컬 solver로 보강 가능
3. Gemini 키 회전(노출 이력) + `.env` → 안전한 시크릿 관리
4. 독립 holdout 코퍼스 확보, EasyOCR 라이선스 결정
5. HWP 최종 증명은 Windows 한컴 머신에서만 가능 — Mac 단독 출시 시
   HWP는 `NOT_RUN` 명시 유지(절대 PASS로 위장 금지)

## 7. 인증/접속

- dev auth: `localStorage`의 `examdna_dev_user`/`examdna_tenant` + dev stub 헤더.
- 실데이터 문서는 `data/` 복사 후 기존 tenant로 로그인하면 그대로 보임.
