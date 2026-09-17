# MASTER SPEC — AI 시험지 복원·편집·제작 에이전트

## 1. 제품 정의
학생이 풀고 채점한 시험지를 업로드하면 AI가 학생 필기·채점 흔적을 분리하고 원래 인쇄 시험지를 복원한다. 문제·수식·도형·선택지·배점·서술 공간을 구조화하고, 원본과 복원본을 다중 대조하며, 문제를 실제로 풀어 문항 논리까지 검증한다. 이후 학원 브랜드 적용, 자연어 문제 수정, 편집 가능한 HWP/HWPX/PDF 출력, HWP 역검증까지 수행한다.

## 2. P0 원칙
### P0-A ZERO TYPO FINAL
최종 `VERIFIED_FINAL` 조건:
```text
UNVERIFIED = 0
CONFLICT = 0
MISSING_OBJECT = 0
MATH_CONFLICT = 0
LOGIC_CONFLICT = 0
HWP_MISMATCH = 0
```
애매한 원문은 추측하지 않고 `NEEDS_REVIEW`로 보낸다.

### P0-B TEACHER ZERO-WORK
```text
시험지 업로드
→ 자동 복원
→ 자동 검증
→ 판단 불가 극소수만 확인
→ 필요한 수정은 자연어 요청
→ 한글파일 생성
```
25문제를 복원했다고 25문제를 다시 검수시키지 않는다.

## 3. 전체 파이프라인
```text
UPLOAD
→ PAGE ANALYSIS
→ IMAGE PREPROCESSING
→ STUDENT TRACE SEPARATION
→ PRINT LAYER RESTORATION
→ QUESTION SEGMENTATION
→ TEXT / MATH / FIGURE RECOGNITION
→ DOCUMENT STRUCTURING
→ SOURCE VERIFICATION
→ QUESTION LOGIC VERIFICATION
→ ANSWER / SOLUTION VERIFICATION
→ BRAND / TEMPLATE APPLICATION
→ HWPX/HWP RENDERING
→ HWP ROUND-TRIP VERIFICATION
→ ZERO TYPO GATE
→ VERIFIED_FINAL
```

## 4. ExamDNA
```text
ExamDNA Core
├ StudentTrace Separator
├ PrintLayer Engine
├ Source Truth Map
├ Atomic Truth Unit
├ Multi-Recognition Consensus
├ ExamDiff
├ LayoutGuard
├ HWP Proof
└ ZeroTypo Gate

Mathematics Guide
├ MathGuard
├ FigureDNA
├ Math Question Parser
├ QuestionLogic Guard
├ Math Solver Verification
└ Curriculum Guard
```
외부 OCR/Vision/Math OCR/LLM은 Candidate 생성용 Provider이며 최종 판정은 ExamDNA가 한다.

## 5. Phase 1 범위
- 대상: 중학교 수학
- 입력: JPG/PNG/PDF/스마트폰 사진/스캔
- 출력: HWP/HWPX/PDF
- 문항: 객관식/주관식/서술형/수식/기하 도형/표·간단 그래프

## 6. 복원 규칙
- 원문 임의 교정 금지
- 문제 번호/배점/보기/선택지 순서 유지
- 학생 풀이·채점·낙서 제거
- 논술형 답안 공간 유지
- 도형 관계와 구조 유지
- 수식은 HWP 수식편집기에서 수정 가능한 객체
- 기본 수식 크기 11pt
- 단위는 Roman 스타일

## 7. 기본 레이아웃
- A4
- 한 행에 2문항
- 같은 행 문항 높이는 긴 문항 기준
- 짧은 쪽 자동 여백
- 다음 행 시작 Y 좌표 동일
- 문제 단위가 페이지 경계에서 부자연스럽게 잘리지 않도록 처리

## 8. 해설
- 문제별 정답 + 풀이과정
- 해당 학년 수준 개념/공식만 사용
- 미주/별도 정답지/별도 해설지/교사용/문제 하단 지원

## 9. AI 편집
예: “6번 숫자만 바꿔줘”, “9번을 조금 어렵게”, “8번과 비슷한 문제 3개”, “우리 학원 스타일 적용”.
조건이 바뀌면 수식/도형/선택지/정답/해설을 함께 갱신하고 재검증한다.

## 10. 브랜드
학원명/로고/심볼/전화/주소/색상/QR/기본 폰트/기존 시험지 샘플/기본 Template 저장. Brand와 Template 분리.

## 11. 최종 출고 Gate
```text
Text Conflict = 0
Number Conflict = 0
Math Conflict = 0
Choice Conflict = 0
Figure Conflict = 0
Missing Condition = 0
Missing Object = 0
Logic Conflict = 0
Unsolvable Question = 0
Ambiguous Answer = 0
Unverified = 0
HWP Mismatch = 0
```

## 12. KPI
- Verified Final Defect = 0
- Final Unverified = 0
- Human Review Count 최소화
- Teacher Active Time 최소화
- Golden Dataset Regression = 0
