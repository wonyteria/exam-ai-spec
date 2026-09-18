# ADR-0004: 중앙 Windows/Hancom 변환 worker

상태: 개발기 검증 완료, 운영 서버 조건 보류(RG-05)
날짜: 2026-09-19

## 결정

- HWP/HWPX/PDF 생성·검증은 **중앙 Windows worker의 Hancom COM 자동화**로 수행한다. 학원 PC에 Hancom·worker·Codex 설치를 요구하지 않는다.
- 변환·검증은 같은 revision에 대해 **draft 생성 → proof(재열기 검사) → final 승격** 순서로 진행하며, draft는 명시 표시되고 final 증명으로 재사용하지 않는다.
- worker는 문서 창 표시가 필요한 action(EquationCreate 등)을 고려해 세션 정책을 갖는다. 덮어쓰기 대화상자·보안 대화상자 같은 블로킹 UI는 허용하지 않고, 발생 시 작업을 실패 처리한다.

## 검증 근거

`backend/scripts/hwp_tech_check.py` 실행 결과(`backend/data/hwp_tech_check/`):
- Hancom Office 2020, `HWPFrame.HwpObject` v11.0.0.2129.
- 실제 `hp:equation`(baseUnit=1100 → 11pt), `hp:endNote`, `hp:rect` 생성.
- HWPX(zip) 저장, HWP 저장, HWP 재열기 성공.

## 운영 미결 사항 (RG-05)

- 운영 서버의 한글 라이선스·수량·계정 정책.
- 헤드리스/서비스 계정에서의 COM 세션 정책(대화형 세션 필요 여부).
- `RegisterModule("FilePathCheckDLL", …)` 파일검사 정책 적용 여부.
- 작업 디렉터리 격리·권한·타임아웃·좀비 프로세스 회수 정책.

## 영향

- WP08: `renderers/hwp_worker`에 검증된 COM 호출 시퀀스를 이식. 수식 삽입은 `EquationCreate` + `HEqEdit.string`/`BaseUnit`, 미주는 `InsertEndnote`, 도형은 `InsertLine`/`HShapeObject` 계열 사용.
- 기존 `renderers/`의 XML 템플릿 경로는 유지하되, 실제 한글 재열기 검사를 proof로 분리한다.
