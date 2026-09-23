# 기존 감사의 추적 가능한 요약

이 문서는 이전 감사의 관측 사실 요약이다. 새 명세의 기능이 구현되거나 AT 테스트가 통과했다는 뜻이 아니다.
코드 기준: `0c1fb5dc8223d52889ca676bed13ad2e7d93fa4a`. 원본/제품 소스는 당시 변경하지 않았다.

## 관측 증거

- 기존 backend pytest 22개 통과, frontend webpack 빌드/타입 통과, lint1개 실패. 기존 테스트가 아래 결함을 막지 못했다.
- 합성 backend/module 재현과 실제 브라우저5개경로,390/768/1280px 검토를 수행했다.
- 사용자 원본5장의 전처리에서 인쇄선 삭제·학생 필기 잔존을 확인했다.
- 신규 Gemini 인식은 연결 거부/외부전송승인검토로 완료하지 못했다. 이는 역사적 실행 제한이며 현재 운영안은Gemini를제외한다.
- 별도 Golden cache replay는29노드/27답/27풀이/19도형설명과VERIFIED_FINAL을냈지만객관식7개답이틀렸다. 새모델정확도아님.
- 생성HWPX를실제한글에서열어6쪽1단/rawLaTeX/도형·미주누락을확인했다. 실제수식·그림·미주객체0.
- 참고HWP를실제한글에서열고8쪽렌더로검토했다. 수식372중232개10pt,객관식미주풀이없음,13번그림누락등을확인했다.

## 기존 A01–A36 / 실물 S01–S12

A/S 항목 일부는 같은 문제의 코드·실물 증거이므로 합계를 독립 버그 수로 해석하지 않는다.

<a id="A01"></a>
### A01 — P1 — 검토 확정이 본문/게이트에 미반영
기존 근거: U/R / B01, F01; documents.py:120–130
요구사항: REQ-12, REQ-14 / 개발: WP02, WP06 / 인수: AT-024, AT-034, AT-046

<a id="A02"></a>
### A02 — P1 — 편집 후 정답·해설·최종 검증 상태 유지
기존 근거: R/S / B02, F06; editing.py:52–69,121–133
요구사항: REQ-10, REQ-11, REQ-13, REQ-14 / 개발: WP02, WP06 / 인수: AT-033, AT-034, AT-046

<a id="A03"></a>
### A03 — P1 — label/position 충돌로 다른 문제 수정
기존 근거: R / B03; editing.py:72–76
요구사항: REQ-07, REQ-13 / 개발: WP02, WP06 / 인수: AT-019, AT-032, AT-033

<a id="A04"></a>
### A04 — P1 — 역검증 미실행을 0건으로 보고 최종 완료
기존 근거: R/S / EX-01; zero_typo_gate/gate.py:9, qa/hwp_proof.py:16–20
요구사항: REQ-11, REQ-17, REQ-18 / 개발: WP02, WP08 / 인수: AT-045, AT-047, AT-053

<a id="A05"></a>
### A05 — P1 — ATU/검증 증거 없는 필드도 gate 통과
기존 근거: R / EX-07; document/verification.py:54–68
요구사항: REQ-06, REQ-07, REQ-11 / 개발: WP02, WP04 / 인수: AT-019, AT-020, AT-023, AT-025, AT-028

<a id="A06"></a>
### A06 — P1 — 미검증/빈 문서도 정상 내보내기
기존 근거: U/R / F02/B08/EX-06; documents.py:168–190
요구사항: REQ-11, REQ-17, REQ-19 / 개발: WP02, WP08, WP09 / 인수: AT-025, AT-045, AT-046

<a id="A07"></a>
### A07 — P1 — PDF 한글 손상, 선택지·수식·도형·페이지 분할 누락
기존 근거: R/S / EX-02; renderers/pdf/renderer.py:11–30
요구사항: REQ-09, REQ-15, REQ-17, REQ-19 / 개발: WP07 / 인수: AT-039, AT-040, AT-041, AT-042, AT-043, AT-047

<a id="A08"></a>
### A08 — P1 — HWPX/웹 도형 누락, 수식 객체 미출력
기존 근거: R/U / EX-03/F05; hwpx/renderer.py:54–70, web/preview.py:23–33
요구사항: REQ-08, REQ-09, REQ-17 / 개발: WP05, WP07 / 인수: AT-039, AT-040, AT-047

<a id="A09"></a>
### A09 — P1 — 인쇄 번호/선택지 라벨을 출력에서 변경
기존 근거: R/U / EX-04/08/F05; web/preview.py:22,28–31
요구사항: REQ-07, REQ-17 / 개발: WP02, WP07 / 인수: AT-019, AT-020, AT-032, AT-046, AT-047

<a id="A10"></a>
### A10 — P1 — 편집 후 HWP가 이전 HWPX를 변환
기존 근거: R / EX-05/B09; documents.py:180–185
요구사항: REQ-14, REQ-17, REQ-18 / 개발: WP08 / 인수: AT-034, AT-046, AT-047

<a id="A11"></a>
### A11 — P1 — 상충 OCR 결과를 별도 ATU로 모두 자동 승인
기존 근거: R / B04; recognition/runner.py:76–107
요구사항: REQ-06, REQ-11 / 개발: WP04 / 인수: AT-020, AT-023, AT-028

<a id="A12"></a>
### A12 — P1 — 풀이 한 회차 누락을 합의 완료로 취급
기존 근거: R / B05; verification/solving.py:34–73
요구사항: REQ-10, REQ-11 / 개발: WP04 / 인수: AT-027, AT-028, AT-029

<a id="A13"></a>
### A13 — P1 — 업로드 filename으로 저장 경로 이탈
기존 근거: R / B06; app/api/uploads.py:29–31
요구사항: REQ-03, REQ-25 / 개발: WP01, WP03 / 인수: AT-009, AT-052, AT-053

<a id="A14"></a>
### A14 — P1 — 중복 파일명 페이지 덮어쓰기·페이지 순서 변경
기존 근거: R/S / B07/F07; uploads.py:29–31, preprocessing.py:15
요구사항: REQ-03, REQ-04 / 개발: WP03 / 인수: AT-007, AT-008, AT-019

<a id="A15"></a>
### A15 — P1 — 허용한 PDF 입력이 실제 파이프라인에서 실패
기존 근거: U/S / F03; preprocessing.py:28–34
요구사항: REQ-03, REQ-04 / 개발: WP03 / 인수: AT-007, AT-009

<a id="A16"></a>
### A16 — P1 — 편집 실패 후 요청 버튼 영구 disabled
기존 근거: U/S / F04; editor/page.tsx:15–38, lib/api.ts:85–95
요구사항: REQ-13, REQ-23 / 개발: WP06, WP09 / 인수: AT-033, AT-037

<a id="A17"></a>
### A17 — P2 — 본문 누락에도 추출 충분 판정, fallback 생략
기존 근거: R / B10; recognition/runner.py:123–134
요구사항: REQ-06, REQ-11 / 개발: WP04 / 인수: AT-020, AT-023, AT-025

<a id="A18"></a>
### A18 — P2 — provider 초기화 실패가 영구 UPLOADED로 남음
기존 근거: R/S / B11; jobs/runner.py:52–61
요구사항: REQ-20, REQ-23 / 개발: WP02, WP04 / 인수: AT-013, AT-015, AT-017

<a id="A19"></a>
### A19 — P2 — gate 완료 전 COMPLETED 공개, SSE 조기 종료 경로
기존 근거: S / B12; pipeline.py:25, jobs/runner.py:62–72
요구사항: REQ-20 / 개발: WP02 / 인수: AT-013, AT-014, AT-016, AT-018

<a id="A20"></a>
### A20 — P2 — 무효 edit op를 성공 처리하거나 500 발생
기존 근거: S / B13; editing.py:56–64,103–118
요구사항: REQ-13, REQ-25 / 개발: WP06 / 인수: AT-032, AT-033, AT-037, AT-052

<a id="A21"></a>
### A21 — P2 — 작업 실패 이유 숨김·실패 단계에 초록 체크
기존 근거: U / F10; jobs/[id]/page.tsx:46,75–90
요구사항: REQ-20, REQ-22, REQ-23 / 개발: WP09 / 인수: AT-006, AT-013, AT-014

<a id="A22"></a>
### A22 — P2 — 없는 job/SSE 단절을 무한 진행, 처리 중 배지도 UPLOADED 유지
기존 근거: U/S / F09/F12; jobs/[id]/page.tsx:28–44
요구사항: REQ-20, REQ-23 / 개발: WP02, WP09 / 인수: AT-006, AT-013, AT-014, AT-015

<a id="A23"></a>
### A23 — P2 — `?doc` 없는 정상 작업 URL은 후속 링크 없음
기존 근거: U / F11; jobs/[id]/page.tsx:25–26,115
요구사항: REQ-02, REQ-20, REQ-22 / 개발: WP09 / 인수: AT-005, AT-014, AT-048

<a id="A24"></a>
### A24 — P2 — 검토 필드 식별/확정 오류 처리/누락·logic 복구 부재
기존 근거: S / F13–14; documents.py:89–97, review/page.tsx:66–71,183–198
요구사항: REQ-12, REQ-22, REQ-23 / 개발: WP06, WP09 / 인수: AT-024, AT-025, AT-026, AT-037

<a id="A25"></a>
### A25 — P2 — 검토 카드 0개를 gate 통과로 오안내
기존 근거: U / F15; review/page.tsx:49–55,73,106–108
요구사항: REQ-11, REQ-12, REQ-23 / 개발: WP06, WP09 / 인수: AT-025, AT-045

<a id="A26"></a>
### A26 — P2 — 에디터 탐색 막힘·목록/preview 선택 미연결
기존 근거: U/S / F16; editor/page.tsx:41–92,119–137
요구사항: REQ-02, REQ-22 / 개발: WP09 / 인수: AT-005, AT-032, AT-048, AT-049

<a id="A27"></a>
### A27 — P2 — 문서 조회 실패를 빈 목록/무한 로딩으로 숨김
기존 근거: U/S / F17; editor/page.tsx:99–117, export/page.tsx:35–45
요구사항: REQ-22, REQ-23 / 개발: WP09 / 인수: AT-001, AT-006, AT-037, AT-048

<a id="A28"></a>
### A28 — P2 — 앞선 편집 응답이 다음 입력을 지울 수 있음
기존 근거: S / F19; editor/page.tsx:37,73–83
요구사항: REQ-13, REQ-23 / 개발: WP06, WP09 / 인수: AT-033, AT-035, AT-037

<a id="A29"></a>
### A29 — P2 — 모바일 3열이 무너져 내용 확인 불가
기존 근거: U / F21; editor/page.tsx:42–43; screenshot07
요구사항: REQ-22 / 개발: WP09 / 인수: AT-049, AT-050

<a id="A30"></a>
### A30 — P2 — dark scheme의 흰 카드에 밝은 글씨 상속
기존 근거: S / F22; globals.css:15–24와 bg-white 카드
요구사항: REQ-22 / 개발: WP09 / 인수: AT-049, AT-050

<a id="A31"></a>
### A31 — P2 — 업로드 시작 컨트롤에 키보드 포커스 불가
기존 근거: U/S / F23; app/page.tsx:35–60
요구사항: REQ-03, REQ-22 / 개발: WP03, WP09 / 인수: AT-007, AT-011, AT-050

<a id="A32"></a>
### A32 — P2 — 업로드 실패 후 동일 파일 재선택 복구 누락
기존 근거: S / F08; app/page.tsx:21–24,54–60
요구사항: REQ-03, REQ-23 / 개발: WP03, WP09 / 인수: AT-011, AT-037

<a id="A33"></a>
### A33 — P2 — Golden 문항 누락을 regression=false로 판정, 내용 검사 부족
기존 근거: R/S / EX-09; tests/golden/harness.py:20–38
요구사항: REQ-27 / 개발: WP00, WP11 / 인수: AT-019, AT-027, AT-028, AT-031, AT-058, AT-059

<a id="A34"></a>
### A34 — P2 — replay 테스트의 cache miss 시 실제 SDK 호출 경로
기존 근거: S / EX-10; provider.py:276–289
요구사항: REQ-21, REQ-27 / 개발: WP00, WP04 / 인수: AT-017, AT-028, AT-057, AT-058, AT-059

<a id="A35"></a>
### A35 — P2 — HWP worker 가용성/실패 반환/종료 처리 불완전
기존 근거: S / EX-11; hwp/worker.py:23–30,44–46
요구사항: REQ-18 / 개발: WP08 / 인수: AT-047, AT-053, AT-060

<a id="A36"></a>
### A36 — P2 — 프로젝트 lint 기본 검사 실패
기존 근거: T / review/page.tsx:63; react-hooks/set-state-in-effect
요구사항: REQ-27 / 개발: WP00, WP11 / 인수: AT-059, AT-060

<a id="S01"></a>
### S01 — P1 — 필기 제거가 인쇄선/문자 훼손, 원본과clean 복수 증거·보존 gate 필요
기존 근거: 새 실물 재현
요구사항: REQ-05, REQ-08 / 개발: WP03, WP05 / 인수: AT-010, AT-021, AT-022, AT-026, AT-040

<a id="S02"></a>
### S02 — P1 — expected/캐시 정답7개 오류 및 두 회차 같은 seeded답 → 기준 재검수
기존 근거: A11·12·33·34 강화
요구사항: REQ-10, REQ-11, REQ-27 / 개발: WP00, WP04 / 인수: AT-027, AT-028, AT-029, AT-031, AT-058

<a id="S03"></a>
### S03 — P1 — 공유 부모/자식 비일관,31노드/28답/100점·집계 규칙 필요
기존 근거: A03·05·24 강화
요구사항: REQ-07 / 개발: WP02 / 인수: AT-019, AT-020, AT-032, AT-043

<a id="S04"></a>
### S04 — P1 — boxed 보기·도형 관계·학생 스케치 구분 실패
기존 근거: A05·08·17 강화
요구사항: REQ-06, REQ-08 / 개발: WP04, WP05 / 인수: AT-020, AT-021, AT-022, AT-040

<a id="S05"></a>
### S05 — P1 — 실제 한글수식0·미주0·도형0, 일단 텍스트 출력
기존 근거: A07·08 강화
요구사항: REQ-08, REQ-09, REQ-17, REQ-18, REQ-19 / 개발: WP05, WP07, WP08 / 인수: AT-039, AT-040, AT-043, AT-047

<a id="S06"></a>
### S06 — P1 — 모든28답안 단위 정답+풀이 미주 coverage 및 학년/풀이 일관성 검증
기존 근거: 기존 해설 미구현 구체화
요구사항: REQ-10, REQ-19 / 개발: WP04, WP07 / 인수: AT-027, AT-029, AT-030, AT-043, AT-044

<a id="S07"></a>
### S07 — P2 — 학교/학년/시험·교육과정 profile의 추출/확인/출력 연결
기존 근거: 메타데이터 연결 보완
요구사항: REQ-04, REQ-10 / 개발: WP03, WP04 / 인수: AT-012, AT-030, AT-051

<a id="S08"></a>
### S08 — P1 — 숫자it/단위roman/11pt 객체 수준 계약, 일반 문자열 출고 금지
기존 근거: A08·35 강화
요구사항: REQ-09 / 개발: WP05, WP07 / 인수: AT-039, AT-047

<a id="S09"></a>
### S09 — P2 — 열당2문항·행별 최대높이·논술 답안공간·overflow 정책
기존 근거: 기존 layout 미구현 구체화
요구사항: REQ-15 / 개발: WP07 / 인수: AT-041, AT-042, AT-049

<a id="S10"></a>
### S10 — P1 — reference HWP의 오타/누락을 Golden로 복제하지 않는3자 비교
기존 근거: 기준본 검증 추가
요구사항: REQ-27 / 개발: WP00, WP11 / 인수: AT-020, AT-027, AT-031

<a id="S11"></a>
### S11 — P2 — 원본순서·모델call·cache hit·사람보정·proof 수행 여부를 결과에 표시
기존 근거: A14·21·33 강화
요구사항: REQ-03, REQ-04, REQ-21, REQ-26, REQ-27 / 개발: WP03, WP04, WP10 / 인수: AT-007, AT-008, AT-012, AT-017, AT-023, AT-057, AT-058

<a id="S12"></a>
### S12 — P1 — 의미/도형/서식/미주/학년/파일역검증을 독립 통과한 동일revision만 final
기존 근거: A04·05·06 강화
요구사항: REQ-11, REQ-17, REQ-18, REQ-27 / 개발: WP02, WP08, WP11 / 인수: AT-028, AT-045, AT-046, AT-047, AT-048, AT-060
