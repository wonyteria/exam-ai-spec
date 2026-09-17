# Feature 08 — QuestionLogic Guard
## 목적
문자상 자연스러워도 문제 자체가 틀린 복원을 탐지.
## 검사
등장점/변수 존재, 조건 충분성/모순, 도형-본문 일치, 풀이 가능, 답 유일, 선택지에 정답 존재.
## Solver
Solver A + Solver B + 가능한 Symbolic/Numeric Check.
## 원칙
Logic Guard가 원문을 추측해 수정하면 안 됨. Conflict는 Source Crop 재분석으로 연결.
