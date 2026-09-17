# Feature 02 — StudentTrace Separator
## 목적
학생 흔적과 인쇄층 분리.
## 클래스
PRINTED_TEXT/MATH/FIGURE/TABLE, PENCIL/PEN/RED_GRADING/HIGHLIGHTER/ERASER/CORRECTION_TAPE, PAPER/SHADOW/NOISE/UNKNOWN.
## Critical Cases
글자 위 필기, 수식 위 계산, 도형 선 위 보조선, 검정 볼펜.
## 금지
단순 색상 제거만으로 구현 금지.
## 실패
분리 불가 → `UNKNOWN → NEEDS_REVIEW`.
