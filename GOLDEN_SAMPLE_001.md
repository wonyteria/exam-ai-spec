# GOLDEN SAMPLE #001

현재 제공된 실제 학생 시험지 이미지를 첫 Golden Dataset으로 사용한다.

## 대상
6번~10번 문항.

## 포함 난점
- 연필 풀이
- 객관식 체크
- 빨간 동그라미/채점
- 도형 위 계산
- 인쇄 선과 학생 표시 겹침
- 수학 기호/숫자와 필기 혼재

## 사람이 확정할 Expected Data
- 문제 번호
- 원문 지문
- 숫자
- 수식/기호
- 단위
- 배점
- 선택지
- 도형 Topology/Labels/Relations
- 정답

## Regression
모든 코드/모델/Provider 변경 시 EXPECTED vs ACTUAL 비교.
이전 버전에서 정확했던 ATU가 틀리면 Regression. P0 Regression은 `DEPLOY BLOCKED`.
