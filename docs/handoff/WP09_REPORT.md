# WP09 Report — 웹 전체 여정·팝업·반응형·오류 복구

Date: 2026-09-19

## 구현 결과

- 업로드
  - 파일 큐의 대기/업로드 중/완료/실패 상태와 구조화된 오류 코드·설명을 표시한다.
  - 성공 상태를 렌더한 뒤 작업 화면으로 이동해 즉시 응답에서도 상태가 사라지지 않는다.
  - offline 배너와 삭제 확인 팝업을 제공한다.
- 작업 진행
  - 취소와 재시도 API를 연결했다.
  - 재시도 시 EventSource를 새로 연결해 재처리 상태가 다시 갱신된다.
- 검토
  - 원본 source 비교 모달, Escape 닫기, focus trap, typed resolution, 중복 제출 방지를 연결했다.
- 편집
  - AI 변경 계획 승인/거부, 409 충돌 복구, undo/redo, 한국어 IME 조합 중 Enter 제출 방지를 연결했다.
- 출력
  - STUDENT, STUDENT_WITH_ENDNOTES, ANSWER_SOLUTION, TEACHER 모드를 제공한다.
  - 변환 완료 뒤 실제 다운로드 링크를 눌러 파일을 받는 흐름을 검증했다.
- 렌더 안정성
  - SSR과 브라우저의 초기 네트워크 상태를 동일하게 두고 mount 후 동기화해 hydration mismatch를 제거했다.
  - Playwright와 Next 개발 서버를 동일한 localhost origin으로 통일했다.

## 검증 증거

- `npm run lint` → PASS, 오류·경고 0건
- `npm run build` → PASS, Next.js production build 및 TypeScript 완료
- `npm run e2e` → Chromium **6 passed**
  - 학원 문맥→업로드→작업 취소/재시도→검토→AI 변경 승인→undo/redo→출력→다운로드 전체 여정
  - quota 429, revision 409, HWP worker 503, offline 상태와 복구 안내
  - source 비교/AI 변경 팝업, Escape, 중복 실행 방지, 한국어 IME
  - 360/390/768/1280px, 기본 light 및 전체 여정 dark 환경
- `python -m pytest -q` → backend **148 passed**

## 현재 판정

WP09의 브라우저 계약과 대표 사용자 여정은 통과했다. 다음 항목은 출시 전 WP11 인수시험에서 실제 backend·운영 환경으로 확인해야 하므로 WP09 상태는 **IN_PROGRESS**로 유지한다.

- production 인증/SSO와 실제 신규 학원 생성부터의 비모의 E2E
- 모든 화면의 403/404 및 삭제·초대 팝업 전수 시험
- screen reader 수동 점검과 자동 대비 분석
- 실제 HWP worker가 연결된 다운로드의 브라우저 E2E(WP08의 실제 COM proof는 별도 통과)
- 장시간 처리 중 새로고침·브라우저 종료·재접속 복구

`NOT_RUN` 항목은 PASS 합계에 포함하지 않는다.
