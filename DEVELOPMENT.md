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
GEMINI_MODEL=gemini-2.5-flash
```

키가 없으면 stub provider로 동작 (항상 NEEDS_REVIEW). 키가 있으면 Gemini가
문항 영역 탐지 → 문항 구조 추출 → 문제 풀이를 수행하고, consensus 규칙
(2+ provider 일치 또는 confidence ≥ 0.9)으로 AUTO_VERIFIED를 결정한다.

## 현재 상태 (수직 슬라이스 골격)

- 업로드 → 전 단계 파이프라인 → ZERO TYPO GATE → HWPX/PDF 출력까지 연결됨
- 인식 계열(stub provider)은 후보를 만들지 않으므로 결과는 항상 NEEDS_REVIEW
- HWP 변환은 Windows + pywin32 + 한컴 설치 환경에서만 동작 (renderers/hwp/worker.py)
- 다음 작업: 실제 Vision/OCR Provider 연결 → 문항 분리 → Golden Sample #001 expected.json 확정
