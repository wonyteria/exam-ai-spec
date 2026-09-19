# 매쓰테일러 도움말·업데이트 심층 검토

검토일: 2026-09-19  
범위: 로그인하지 않은 공개 도움말, 업데이트 내역, 설치 안내, 공개 문제은행 로그인 화면. 실제 변환 품질과 로그인 뒤 기능은 검증하지 않았다.

출처:
- https://xn--vl2b19ao0ssqc39r.kr/manual
- https://xn--vl2b19ao0ssqc39r.kr/setup-download
- https://xn--vl2b19ao0ssqc39r.kr/
- https://que.xn--vl2b19ao0ssqc39r.kr/

## 1. 출시 우선순위

이번 검토에서 가격보다 중요한 경쟁 기준이 확인됐다.

1. 기능적 안정성: 기존에 되던 파일이 업데이트 뒤 깨지지 않고, 실패를 정확히 차단·설명한다.
2. 편리함: 설치, 로컬 설정, 외부 API 가입, 파일 구조 규칙, 수동 번호 관리가 없어야 한다.
3. 성능: 빠른 결과보다 정확한 first useful preview와 예측 가능한 완료 시간이 중요하다.
4. 가격: 위 조건을 지키면서 낮춘다. 검증·복구를 제거해 낮추지 않는다.
5. 기능 수: 문제은행·변형 기능보다 복원→검토→최종 파일의 완결성이 우선이다.

## 2. 설치·환경 도움말에서 얻은 정보

공개 설치 오류 문서는 최신 업데이트가 적용되지 않거나 로그인 시 파일 비교 오류가 나는 원인으로 Windows 날짜 표시 형식과 시스템 로캘을 든다. 날짜에 요일이 포함된 경우 서버와 PC 날짜를 비교하지 못할 수 있어 날짜 형식을 바꾸고, 시스템 로캘이 한국어인지 확인한 뒤 다시 로그인하도록 안내한다. HWP 2014에서는 상위 버전 문서 경고가 나타날 수 있어 업데이트 패치를 요구한다.

### ExamAI Spec 반영

- 교사 PC 환경을 변환 성공 조건으로 사용하지 않는다.
- 중앙 worker image에 OS locale, timezone, 날짜 형식, HWP 버전, patch, font, COM 등록 버전을 고정한다.
- worker 시작 시 health probe를 실행하고 drift가 있으면 새 job을 받지 않는다.
- 파일 생성 proof에 worker image/app/font 버전을 포함한다.
- 지원 HWP 버전별 open/save/reopen compatibility fixture를 유지한다.
- 환경 오류는 교사에게 Windows 설정 변경을 요구하지 않고 운영자에게 자동 진단과 교체 runbook을 제공한다.

## 3. 사용자 API 키 등록에서 얻은 정보

Gemini Vertex 안내는 Google Cloud 프로젝트 생성, 약관 동의, 결제 연결, 2단계 인증, 경우에 따라 카드·신분증 검토, Vertex 파일 키 생성까지 요구한다. 잘 되지 않으면 원격 지원을 안내한다. Claude 키는 풀이·변형에는 쓸 수 있지만 도형을 다시 그리는 이미지 AI에는 사용할 수 없다고 설명하며 Vertex 키를 권장한다.

### ExamAI Spec 반영

- 학원 사용자는 provider 계정·결제·키·service account 파일을 만들지 않는다.
- 플랫폼이 provider 자격 증명, rotation, budget, rate limit, capability matrix를 관리한다.
- 기능마다 사용자가 모델을 고르지 않는다. `task→지원 capability→가격→품질` routing policy가 선택한다.
- 특정 provider 장애나 기능 미지원은 자동 유료 fallback이 아니라 명시적인 대기/차단/승인 정책으로 처리한다.
- 키·provider 응답·학생 원문은 브라우저와 일반 로그에 노출하지 않는다.
- provider 변경 뒤 고정 corpus 회귀 없이는 production default를 바꾸지 않는다.

## 4. PDF-PRO 도움말에서 얻은 정보

도움말은 이미지·수식이 많은 페이지에서 이미지 위치 오류가 나면 정밀 변환을 사용하도록 안내한다. 특정 PDF에서 도형이 빠질 때는 이미지 영역을 수동으로 정밀 지정하고, 그래도 해결되지 않으면 사용자가 직접 도형을 잘라 HWP에 붙여넣도록 한다.

수동 영역 화면은 다음 기능을 제공한다.

- 문제와 이미지 사이 여백이 작으면 bounding box를 정밀하게 지정한다.
- 지정하지 않으면 자동 영역을 사용한다.
- 이미지 주변 낙서를 지우는 `원본 지우기` 동작이 있다.
- 영역 초기화, zoom, 페이지 이동, crop, clipboard 저장을 제공한다.

미주 도움말은 혼합 번호(`1-1`, `01`) 처리를 별도 case로 설명하고, 문제 HWP와 풀이 HWP의 미주 위치를 맞춘 뒤 합친다.

### ExamAI Spec 반영

- 페이지 위험도를 계산해 일반/정밀 처리를 자동 선택하고 이유를 표시한다.
- 빠른 모드가 spacing·수식·도형을 생략할 가능성이 있으면 최종 출고용으로 쓰지 않는다.
- 원본은 절대 수정하지 않는다. erase는 mask/clean variant로 저장하고 원본과 언제든 비교한다.
- review 화면에 non-destructive bounding-box 편집, reset, 원본/clean 토글, 확대, keyboard 이동을 제공한다.
- 수동 crop은 최종 해결책이 아니라 해당 객체만 재추출·재검증하는 입력이다.
- 문제·소문항 번호는 canonical label과 내부 UUID로 분리한다. `01`, `1-1`, 논술형 번호를 문자열 규칙 하나로 처리하지 않는다.
- 미주 anchor 위치와 coverage를 renderer가 생성하고 실제 HWP에서 검사한다.

## 5. DB 구축·단원관리 도움말에서 얻은 정보

DB 구축 화면은 폴더 트리, HWP 목록, 문제/풀이 preview, metadata table을 함께 제공한다. 사용자는 정해진 폴더 깊이에서 HWP를 불러오고, 기존 최대 번호를 확인한 뒤 다음 번호를 지정해 DB 구축을 실행한다.

원본 HWP는 미주가 문제 번호의 시작 위치에 있어야 하며 중간에 있으면 안 된다고 안내한다. 이는 HWP import가 anchor 위치와 수동 numbering 규칙에 의존한다는 뜻이다.

단원관리는 다음 power-user 기능을 제공한다.

- 여러 행 선택 뒤 대단원·중단원·소단원을 일괄 수정한다.
- 직접 단원명을 입력하거나 분류표에서 단원을 더블클릭한다.
- 주제/시험명과 시작 번호를 일괄 적용한다.
- 문제·풀이 preview와 표를 한 화면에서 본다.

### ExamAI Spec 반영

- 사용자가 폴더 깊이, 최대 번호, 다음 번호, 미주 위치를 맞추지 않아도 된다.
- HWP import가 생기면 preflight가 anchor·numbering·section·table·equation·endnote 구조를 검사하고 자동 정규화/차단한다.
- canonical UUID와 사람이 보는 label을 분리해 번호 변경이 데이터 identity를 바꾸지 않게 한다.
- V1 핵심 복원 흐름을 먼저 완성하고, 문제은행은 이후 structured taxonomy와 bulk selection을 재사용해 만든다.
- 일괄 분류·일괄 metadata 변경·다중 선택은 좋은 power-user 패턴이므로 향후 library에 반영한다.
- preview와 metadata table 선택이 항상 같은 문제를 가리키도록 selection state를 하나로 둔다.

## 6. 업데이트 내역에서 추출한 반복 결함 분류

| 반복 결함 | 공개 내역의 사례 | ExamAI Spec 출시 gate |
|---|---|---|
| 특정 파일 변환 실패 | 특정 PDF 실패 수정 반복 | 형식·생성기·암호화·페이지 크기 corpus, 실패 원인 코드, 부분 재시도 |
| 수식 직렬화/줄바꿈 | 긴 수식 한 줄, 표 안 수식 깨짐, 수식 많은 페이지 오류 | math AST roundtrip, table equation, multiline, raw LaTeX 0건 |
| roman/italic/단위 | P/E/V, sin/cos, cm/kg, 벡터 대문자 보정 반복 | token별 style oracle, 11pt, unit dictionary, 실제 HWP 검사 |
| 도형·crop | 도형 누락, 축 label 누락, 잘못된 crop, 중학교 도형 개선 | bbox coverage, 관계/label/axis diff, non-destructive manual recovery |
| 표·조건·박스 | 표 속도, 테두리 소실, 조건/보기/BOX 변환 | 표 구조·border·header·box semantic 비교 |
| 번호·미주 | 혼합 번호, 미주 위치 제약, 미주 합치기 | canonical ID/label 분리, endnote coverage·anchor·번호 회귀 |
| spacing·기호 | 조사 띄어쓰기, 수식 간격, 나눗셈/평행 기호 | Unicode/spacing rule과 원문 diff, 수학 기호 normalization |
| provider/model | Gemini↔Claude 전환 오류, 서버 속도 변동 | capability routing, circuit breaker, provider/version별 회귀 |
| 회귀 위험 | 처리 방식 변경 뒤 기존 정상 자료 오류 가능 공지 | canary corpus, 이전 버전 비교, staged rollout, rollback |
| 성능 | HWP→PNG 10배 개선, 표 생성 개선 | 단계별 p50/p95, first preview, worker throughput·timeout |

## 7. 우리가 반드시 채택할 편의 기능

- 입력 직후 페이지 순서·누락·회전 확인과 원본 thumbnail.
- 위험 객체만 모은 source comparison review.
- 도형/이미지 bounding box 수동 보정과 즉시 preview.
- bulk select와 일괄 metadata/단원 변경.
- 변환 전 preflight와 변환 뒤 실제 HWP proof를 한 상태 흐름으로 표시.
- 실패한 객체만 재처리하고 전체 시험을 다시 과금·대기시키지 않음.
- 오류 신고에 source crop, revision, job, provider/model, worker version, proof hash 자동 첨부.
- 수정·풀이·변형 결과의 revision history, undo/redo, 안전한 재사용.
- 사용자에게 알려진 문제·수정 버전·우회 방법을 공개하는 release note.

## 8. 피해야 할 방식

- 원본 이미지를 직접 지우거나 덮어쓰기.
- 교사에게 Windows 날짜/locale/HWP patch를 바꾸게 하기.
- 교사에게 Google Cloud 결제·신분 확인·API 키 파일 생성을 요구하기.
- 빠른 모드 누락을 안내 문구만으로 허용하고 최종 파일을 제공하기.
- 정해진 폴더 깊이·미주 위치·시작 번호를 맞춰야 import되는 구조.
- provider 변경을 사용자에게 떠넘기거나 capability 차이를 숨기기.
- 한 화면에 기능을 계속 쌓아 power-user 밀도와 초보자 onboarding을 같은 UI로 해결하기.

## 9. 출시 전 기능 안정성 체크리스트

### 입력

- 서로 다른 PDF 생성기, 사진, 기울기, 그림자, 낙서, 축·표·다단, 혼합 번호 corpus.
- 원본 불변 hash, 페이지 순서, crop transform, clean/mask provenance.
- 파일별 실패 코드와 다시 올리지 않고 복구하는 경로.

### 처리

- 일반→정밀 자동 승격 기준과 비용·시간 기록.
- provider version별 canary와 이전 버전 결과 비교.
- timeout/429/503/부분 응답에서 동일 job resume와 중복 비용 방지.
- 수식·도형·표·미주 coverage가 부족하면 final 차단.

### 검토

- 원본 crop·현재 값·후보·영향 범위가 함께 보임.
- manual crop/mask는 revision으로 저장되고 되돌릴 수 있음.
- bulk action은 대상 수·변경 전후·부분 실패 정책을 보여 줌.

### 출력

- HWPX/HWP/PDF별 Open→SaveAs→reopen proof.
- 지원 HWP 버전/폰트/locale matrix.
- 미주 anchor, 표 border, multiline equation, 도형 label/축, 마지막 페이지 검증.

### 운영

- worker image drift·font/HWP update를 배포 전에 감지.
- canary→일부 학원→전체 rollout과 한 클릭 rollback.
- 알려진 문제·영향 범위·수정 버전·재처리 대상을 운영 dashboard에서 추적.

## 10. 우선순위

### P0 — Alpha 전에 필요

- immutable original + non-destructive crop/mask editor
- 자동 일반/정밀 승격과 객체별 재처리
- 번호·미주·수식·표·도형 preflight와 실제 HWP proof
- 중앙 provider key/capability routing과 중앙 worker health
- 오류 신고 evidence bundle과 release/canary/rollback 체계
- Windows/HWP/font/locale version 고정 및 drift 차단

### P1 — 제한 Pilot 전에 필요

- bulk metadata/taxonomy editing
- HWP import preflight/normalization
- 학원별 corpus regression과 failure clustering
- 지원자가 원본에 접근하지 않고도 재현 가능한 diagnostics

### P2 — 핵심 V1 뒤

- 완전한 문제은행·단원 출제·변형 문제
- 범용 도형 그림판
- 외부 HWP를 대량 import하는 migration suite

공개 도움말의 문구·화면을 복제하지 않는다. 반복 실패와 복구 부담을 제품 요구사항과 테스트로 변환하는 데만 사용한다.
