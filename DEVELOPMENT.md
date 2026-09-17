# DEVELOPMENT

## 구조

```text
backend/          Python + FastAPI — ExamDNA 파이프라인 코어
  app/            API 서버 (uploads/jobs/documents 라우터)
  core/examdna/   전처리·필기분리·인쇄복원·인식·검증·게이트 단계
  document/       Document/Question/ATU 스키마 (Source of Truth)
  providers/      OCR/Vision/MathOCR/LLM/Solver 인터페이스 + stub
  renderers/      web(hwpx/hwp/pdf) — hwpx는 실제 파일 생성
  guides/         과목 가이드 (mathematics)
  jobs/           Job 상태머신 + 파일 기반 저장소
  qa/             HWP 역검증
  tests/          pytest + Golden Sample 하네스
frontend/         Next.js — 업로드/스캔/검토/에디터/내보내기 UI
```

## 실행

```bash
# 백엔드 (port 8000)
cd backend
./.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# 프론트엔드 (port 3000)
cd frontend
npm run dev
```

## 테스트

```bash
cd backend
./.venv/Scripts/python -m pytest
```

## Provider 설정

`backend/.env` 생성 (`.env.example` 참고):

```bash
GEMINI_API_KEY=<AI Studio에서 발급>
GEMINI_MODEL=gemini-3.1-flash-lite          # 인식용 (무료 일일 한도 큼)
GEMINI_MODEL_SOLVER=gemini-3.5-flash        # 풀이용 (정확도 우선)
GEMINI_MIN_INTERVAL=4.0                     # 요청 간 최소 간격(초)
GEMINI_CACHE=1                              # 응답 디스크 캐시 (0=끔)
```

키가 없으면 stub provider로 동작 (항상 NEEDS_REVIEW). 키가 있으면 Gemini가
문항 영역 탐지 → 문항 구조 추출 → 문제 풀이를 수행하고, consensus 규칙
(2+ provider 일치 또는 confidence ≥ 0.9)으로 AUTO_VERIFIED를 결정한다.

### 무료 티어 쿼터 주의

- 일일 한도(모델별, 프로젝트별) 소진 시 `DailyQuotaExhausted`로 즉시 실패하고
  해당 모델은 작업 내에서 스킵된다 — 무한 재시도 없음.
- 5페이지 전체 실행은 인식 ~90회 + 풀이 ~60회 호출을 소모한다.

### 응답 캐시 / 오프라인 재생

- `backend/data/cache/gemini/`에 (모델+프롬프트+이미지 바이트) 해시로 응답 저장.
- 같은 이미지 재실행은 API 호출 없이 수 초 내 완료.
- 완료된 문서로 캐시를 역산 시딩 가능:

```bash
./.venv/Scripts/python scripts/seed_gemini_cache.py <document_id>
```

## 현재 상태 (수직 슬라이스 골격)

- 실제 시험지 5페이지로 E2E 동작 확인: 29문항 영역 분리, 1–20번 선택지/도형/풀이 추출,
  논술형 소문항 라벨(논술형 2, 2-1…) 보존, 읽기 순서 정렬
- `number` = 안정적 위치 인덱스, `label` = 인쇄된 표기 (덮어쓰기/중복 없음)
- 미해결: 학생 필기 분리 실구현, 일부 문항 선택지 누락(7, 13번), 논술형 공통 지문,
  HWP 실변환(한컴 필요), golden expected.json 사람 확정
- HWP 변환은 Windows + pywin32 + 한컴 설치 환경에서만 동작 (renderers/hwp/worker.py)
