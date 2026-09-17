# CODEX START PROMPT

이 저장소의 개발 전에 `README.md`, `MASTER_SPEC.md`, `ARCHITECTURE.md`, `features/`, `guides/mathematics/`를 모두 읽어라.

## 핵심 목표
1. 최종 검증 완료본의 미검증 요소 0개.
2. 선생님에게 전체 문항 검수를 요구하지 않음.
3. 애매한 부분을 추측하지 않음.
4. HWP 출력 후에도 재검증.
5. 수학 전용 로직을 ExamDNA Core에 하드코딩하지 않음.

## 절대 금지
`OCR → LLM이 적당히 정리 → HWP`만으로 구현하지 말 것.

## 코딩 전 보고
1. Repository 구조
2. 재사용 가능한 기능
3. 부족한 기능
4. 권장 Architecture
5. Document/Question Schema
6. Source Truth/ATU Schema
7. Verification State Machine
8. Mathematics Guide 구조
9. AI Provider 구조
10. HWP 생성 방식
11. Golden Sample #001 테스트 설계
12. 첫 Vertical Slice
13. 기술 리스크
14. Phase별 개발 순서

## 첫 Vertical Slice
```text
Golden Sample #001 업로드
→ 학생 필기/채점 흔적 분리
→ 6~10번 문항 분리
→ 본문/수식/선택지/도형 복원
→ Source Truth 대조
→ 실제 문제 풀이
→ 논리 검증
→ 판단 불가 부분만 사용자 확인
→ 편집 가능한 HWP 생성
→ HWP 역검증
→ VERIFIED_FINAL
```

## 판단 우선순위
`정확성 → 검증 가능성 → 선생님 효율 → 유지보수성 → 비용`
