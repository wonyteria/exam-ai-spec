# WP09 Report — 웹 전체 여정/반응형/오류 복구 (진행 중)

Date: 2026-09-19

## 이번 반영

- 업로드 페이지
  - 파일 큐 상태 표시(대기/업로드 중/완료/실패)
  - offline 배너 추가
- 검토 페이지
  - source 비교 모달 추가(ESC 닫기, 포커스 트랩)
  - resolve 중복 제출 방지(atu 단위 busy)
- 에디터 페이지
  - 모바일/태블릿 대응 레이아웃(`1열 -> md 3열`)
  - 한국어 IME 조합 중 Enter 제출 방지
  - undo/redo 버튼을 v1 revision API와 연결
- 작업 페이지
  - cancel/retry 버튼 연결(`POST /api/jobs/{id}/cancel`, `POST /api/v1/tenants/{id}/jobs/{id}/retry`)
  - offline/오류 상태 표기
- 내보내기 페이지
  - output mode 선택(`STUDENT`, `STUDENT_WITH_ENDNOTES`, `ANSWER_SOLUTION`, `TEACHER`) 연결
- 공통 API
  - HTTP status/code를 포함한 에러 파싱/표준화

## 실행 결과

- Frontend lint: `npm run lint` → PASS (exit 0)
- Frontend build: `npm run build` → PASS (exit 0)
- Browser E2E: `npm run e2e` (Playwright, chromium) → `4 passed`
  - 360 / 390 / 768 / 1280 viewport에서 review 페이지 여정 기본 확인

## 한계 / 미완료

- **IN_PROGRESS**
  - popup focus trap/Escape: source 비교 모달 구현은 했지만 전체 팝업(편집 승인/충돌/삭제 등) 전수 검증은 미완료
  - 오류 복구 전수(403/404/409/quota/offline)를 Playwright에서 모든 화면에 대해 자동화하지 못함
  - 학원 온보딩→업로드→진행→검토→편집→출고 전 경로를 단일 E2E로 완주 검증하지 못함

WP09는 구현을 계속 진행 중이며, 현재 상태는 **IN_PROGRESS**다.
