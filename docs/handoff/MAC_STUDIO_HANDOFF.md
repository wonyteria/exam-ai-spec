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

```bash
# Ollama — 외부 바인딩 필수 (기본은 localhost만 들음)
OLLAMA_HOST=0.0.0.0 ollama serve
ollama pull qwen3:32b        # 96GB+ 통합메모리면 gpt-oss:120b도 가능
# LM Studio라면: 개발자 탭 → Start Server → "Serve on local network" 체크
```

`ifconfig | grep "inet "`로 맥 IP 확인 (예: `192.168.0.10`). 라우터 고정IP 예약 권장.
방화벽은 LAN 대역만 허용 — **11434 포트를 공인망에 열지 말 것**.

### Windows 측 `backend/.env`

```dotenv
EXAMDNA_ENABLE_LOCAL_LLM=1
LOCAL_LLM_BASE_URL=http://192.168.0.10:11434/v1   # 맥 실제 IP
LOCAL_LLM_MODEL=qwen3:32b                          # ollama list에 있는 이름 그대로
# LOCAL_LLM_TIMEOUT=600                            # 32B 모델 배치는 느릴 수 있음
# LOCAL_LLM_DISABLE_THINKING=1                     # qwen3/qwq의 <think> 생략(빨라짐)
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
