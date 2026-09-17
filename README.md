# AI 시험지 복원·편집·제작 에이전트

학생이 풀고 채점한 학교 시험지 사진·스캔·PDF를 입력하면 학생 흔적을 제거하고 원래 인쇄 시험지를 복원한 뒤, 원본 대조·문항 논리 검증·HWP 역검증까지 거쳐 편집 가능한 HWP/HWPX/PDF로 출력하는 AI 시험지 제작 에이전트입니다.

## 핵심 원칙
- **ZERO TYPO FINAL**: 최종 검증 완료본은 `UNVERIFIED=0`, `CONFLICT=0`, `HWP_MISMATCH=0`이어야 함.
- **TEACHER ZERO-WORK**: 시스템이 할 수 있는 작업은 선생님에게 시키지 않음.
- **STRUCTURED DOCUMENT**: HWP가 Source of Truth가 아니라 구조화 Document JSON이 Source of Truth.
- **RESTORE → UNDERSTAND → PROVE → EDIT → EXPORT → PROVE AGAIN**.

## 현재 범위
Phase 1은 **중학교 수학**. 이후 국어/영어/과학/사회는 별도 Subject Guide로 추가.

## 권장 읽기 순서
1. `MASTER_SPEC.md`
2. `ARCHITECTURE.md`
3. `CODEX_START_PROMPT.md`
4. `features/*.md`
5. `guides/mathematics/*.md`
6. `ROADMAP.md`
7. `GOLDEN_SAMPLE_001.md`
