# Devin 개발 순서·의존성·완료 증거

대상 저장소: `https://github.com/wonyteria/exam-ai-spec.git` / 기준 `0c1fb5d`.
제품 구현은 아직 수행되지 않았다. 아래 WP는 개발자가 완료해야 할 작업이며, 감사에서 통과했다고 표시하는 항목이 아니다.

## 1. 실행 규칙

- 시작할 때 최신 branch/HEAD/미커밋 변경을 기록하고 기준 이후 변경을 대조한다. 기존 사용자 변경을 되돌리지 않는다.
- 첫 PR에서 이 패키지를 저장소의 명세 문서로 도입하고 실제 파일 경로·ADR·테스트 명령을 연결한다. 본문에서 말하는 신규 파일은 제안 위치이며 기존 파일처럼 인용하지 않는다.
- 코드를 일괄 다시 쓰지 않는다. 기존 provider/document/API 경계를 활용하되, 잘못된 데이터·검증 계약은 테스트를 만든 후 교체한다.
- 새 의존성·관리형 서비스는 필요성/대안/라이선스·운영비/보안/마이그레이션을 비교표로 남긴 뒤 저장소의 승인 규칙을 따른다. 실제 가입·결제·공개 배포는 이 계획 작성의 범위가 아니다.
- 각 WP는 기능 코드, 해당 회귀 테스트, 오류 복구, 문서, 관측 항목, 인수 증거를 함께 제공한다. 후속 단계에 테스트를 몰아넣지 않는다.
- 약속한 기능을 구현하지 못했다면 capability를 끄고 이유를 표시한다. 성공 배지나 enabled 버튼으로 대신하지 않는다.
- 커밋 메시지는 저장소 Lore 형식으로 의도·검증·미검증·제약을 기록한다. 실제 수행하지 않은 테스트를 Tested로 적지 않는다.

## 2. 작업 그래프

```text
WP00 기준/환경/운영 결정
  └ WP01 학원 인증·저장소·보안 토대
      └ WP02 canonical revision·검증·작업 계약
          ├ WP03 업로드·페이지·비파괴 전처리
          │   └ WP04 AI 추출·원본/풀이 검증
          │       └ WP05 수식·도형·표 scene/AST
          ├ WP06 검토·AI 편집·이력·동시성
          └ WP09 웹 UX 구현(계약별 mock부터 가능)
WP05 + WP06 + WP02
  └ WP07 레이아웃·브랜드·미주·HWPX/PDF/web
      └ WP08 실제 Windows HWP·포맷 proof
WP01..09
  └ WP10 운영·사용량·보관·보안·복구 강화
      └ WP11 독립 품질 평가·파일럿·출시 인계
```

WP10의 최소 로깅·한도·권한은 WP01부터 적용한다. WP10까지 보안을 미루라는 뜻이 아니다. 문서 객체와 API가 확정되면 UI·renderer·테스트를 병렬로 작업할 수 있다. 같은 schema/state/API 파일을 여러 작업자가 동시에 임의 변경하지 않는다.

## 3. WP별 변경 범위와 완료 조건

### WP00 — 기준 확정·환경 검사·회귀 기반

**필수 입력:** 01~04 명세, A01–A36/S01–S12, 실제 원본/참고 HWP의 해시, 독립 답/출처 초안.

**작업:**

- HEAD와 현재 코드의 차이를 확인하고 린트/타입/백엔드 테스트/프런트 빌드를 baseline으로 기록한다.
- 기존 Golden을 `seeded regression`으로 표시하고, 잘못된 7개 답·본문/보기/도형 누락을 원본 근거로 재검수한다. 모델 입력에 정답을 주지 않는 평가 경계를 만든다.
- 지원 수식/도형/표/그래프 범위, 파일 제한, 제안 QA 수치, API 모델 접근/가격·예산, 인증/스토리지/DB, Windows 한글 서버 환경을 결정표에 기록한다.
- 한글 수식 1개·벡터 도형 1개·실제 미주 1개를 가진 기술 검증용 문서를 생성하고 실제 앱에서 열기/편집/렌더 성공을 확인한다. 이것이 제품 완성은 아니다.
- Next.js를 수정하기 전 `frontend/AGENTS.md`와 설치된 버전의 문서를 읽는다. API/SDK도 실제 사용 버전의 공식 문서를 읽는다.

**현재 파일:** `MASTER_SPEC.md`, `ARCHITECTURE.md`, `frontend/package.json`, `backend/pyproject.toml`, `backend/tests/test_golden_replay.py:25–65`, `backend/tests/golden/harness.py:20–38`.

**완료 증거:** baseline 로그, 정답 기준 변경 근거, 의존성/인프라 ADR, cache-only 테스트, Windows 최소 객체 검증 기록. 도구/계정이 없으면 해당 항목을 차단 상태로 남기고 모의 테스트와 계약 구현은 계속한다.

### WP01 — 학원 인증·권한·영속 저장소

**의존:** WP00. **REQ:** 01·02·24·25·26·28.

- 중앙 DB에 tenant/membership/role/document grant를 만들고 asset·job·revision·artifact의 모든 조회를 학원 범위로 제한한다.
- 인증 세션과 API authorization, private object storage, 원본 불변 저장, 기본 audit log를 구현한다.
- 기존 file JSON 자료는 명시적 학원 매핑/백업/검증을 거친 import로 이관한다. 어느 학원 소유인지 모르는 기존 문서를 자동 공개하지 않는다.
- 학원 초대/생성/전환과 문서 보관함 최소 UI를 제공한다.

**현재 파일:** `backend/app/main.py`, `app/deps.py`, `jobs/store.py:11–77`, `app/api/{uploads,jobs,documents}.py`; 신규 auth/tenant/storage 모듈은 ADR로 위치를 확정한다.

**완료 증거:** 학원 A/B의 문서·crop·history·SSE·export·download 교차 접근 거부, 권한 회수 반영, 명시적 import 결과/rollback, private storage 접근 시험.

### WP02 — canonical revision·검증·지속 작업 계약

**의존:** WP01. **REQ:** 06·07·11·14·17·20.

- 02 문서의 schema/entities와 상태 전이를 구현한다. 내용/스타일/검증/artifact의 hash와 version을 구분한다.
- mutation service에 CAS, idempotency, audit, dependency invalidation을 모은다. API마다 다른 후처리를 붙이지 않는다.
- DB job queue/checkpoint/lease/fencing과 nonterminal 검증 단계를 구현한다. terminal은 결과 저장 후 공개한다.
- 내부 draft 생성과 final 다운로드를 분리하고 포맷별 proof를 구현할 자리를 만든다.

**현재 파일:** `document/models.py`, `document/verification.py`, `jobs/models.py`, `jobs/store.py`, `jobs/runner.py:47–82`, `core/examdna/pipeline.py:25`.

**완료 증거:** stale update 409, 오래된 worker 결과 거부, 취소/완료 경합, 미실행 proof 차단, ATU 없는 필드 차단, revision 증가·undo 시 새 revision 생성 계약 테스트.

### WP03 — 원본 업로드·페이지 순서·비파괴 전처리

**의존:** WP02. **REQ:** 03·04·05·23·25.

- UUID 저장명/원본명/순서/해시 manifest, 타입·크기·픽셀·PDF 페이지 검증, 재시도와 중복 방지를 구현한다.
- PDF rasterization, EXIF 회전/원근·크롭과 변환 행렬, metadata 및 전체/부분 시험지 모드를 처리한다.
- 원본과 clean/mask를 별도 보존하고 인쇄선 파괴 검사를 추가한다. 불확실한 삭제 영역은 원본 대조로 돌아갈 수 있어야 한다.
- UI 업로드 큐/페이지 순서 확인과 오류를 서버 capability에 연결한다.

**현재 파일:** `app/api/uploads.py:17–36`, `preprocessing.py:14–56`, `student_trace/separator.py`, `print_layer/engine.py`, `frontend/app/page.tsx`.

**완료 증거:** 중복 파일명과 page1/page2/page10, 경로 공격, 다중 PDF, 손상 파일, 심원중 실제 순서, S01 인쇄선/학생 필기 구분, 원본 해시 불변.

### WP04 — 운영 AI adapter·추출·원본/풀이 검증

**의존:** WP03 + WP00의 승인된 데이터/모델 설정. **REQ:** 06·07·10·11·21·27.

- 운영 OpenAI Responses adapter를 구현하고 Gemini 자동 삽입을 제거/기본 비활성화한다. developer Codex CLI는 별도 QA 도구로 둔다.
- schema-constrained 페이지/문항 추출, 동일 필드 후보 병합, completeness와 source coverage, 필요한 필드 retry를 구현한다.
- 정답/풀이/기호 매칭과 필수 검증 회차 수를 확인한다. 기준 캐시를 재사용해 독립 검증을 가장하지 않는다.
- 호출별 model/prompt/schema/input hash, 실제 usage, timeout/rate limit/retry/거절을 기록하고 budget을 적용한다.

**현재 파일:** `providers/base.py`, `providers/gemini/provider.py`(현재 계약 참고), `jobs/runner.py:18–44`, `recognition/{segmenter,runner}.py`, `source_truth/consensus.py`, `verification/{logic,solving}.py`.

**완료 증거:** 원본에서 전사/보기/도형 관계, 서로 다른 후보 conflict, 누락 회차 실패, 7개 잘못된 기준 탐지, 답과 풀이 모순 탐지, API 429/503/JSON 오류·한도·캐시 분리. 새 inference와 cache replay 결과를 별도로 보고한다.

### WP05 — 수식 AST·도형 scene·표/그래프 객체

**의존:** WP02·04; renderer와 협업. **REQ:** 06·08·09·10·25.

- math AST/단위/스타일 토큰, 한글 수식 변환과 지원 범위를 구현한다.
- 도형의 관계/라벨/표식/선 종류와 허용 primitive scene, 표/간단한 그래프 객체를 구현한다. 모델 코드를 직접 실행하지 않는다.
- source relation 대조 및 불가능/불완전 조건을 issue로 연결한다. 기하 모양을 그럴듯하게 바꾸어 통과하지 않는다.

**현재 파일:** `document/models.py:74–120`, `core/examdna/layout`, `guides/mathematics`, 신규 scene/math 모듈.

**완료 증거:** 실제 수식 객체 편집, 숫자/단위 스타일, 11pt, 원본 주요 직각/평행/등길이·라벨 보존, 그래프 축/눈금·표 머리말 보존, malicious/invalid scene 거부.

### WP06 — 검토 확정·AI 편집·버전·되돌리기

**의존:** WP02·04의 문서/operation 계약. **REQ:** 12·13·14·23.

- review API의 typed resolution과 canonical mutation을 연결한다. 재추출/누락 추가/논리 이슈 복구 경로를 만든다.
- AI는 변경 계획을 생성하고, 서버는 대상·값·영향·권한·baseVersion을 검사한다. 의도된 편집 후 원문 비교와 답/풀이 검증의 기준을 구분한다.
- 저장된 이력, before/after, undo/redo, 그룹 전파, 실패/부분 적용 정책을 구현한다. 원자적 정책에 맞춰 partial mutation을 방지한다.

**현재 파일:** `app/api/documents.py:81–160`, `core/examdna/editing.py`, `frontend/app/documents/[id]/{review,editor}/page.tsx`.

**완료 증거:** 확정값이 실제 preview/출력에 동일, 편집 후 과거 답/VERIFIED_FINAL 폐기, label 충돌로 다른 문제 수정 안 함, 동시 탭 409, no-op/잘못된 op, 재로드 후 이력/undo, 입력 A/B 응답 경합.

### WP07 — 레이아웃·브랜드·미주·HWPX/PDF/web

**의존:** WP05·06·02. **REQ:** 09·15·16·17·19.

- 구조 문서로부터 공통 layout plan을 만들고 각 renderer의 결과를 이 계획과 대조한다. 픽셀 기반 임의의 빈 줄을 쌓지 않는다.
- 2열×2문항 및 row pairing, 긴 문항 흐름, 논술형 answer space, source label을 구현한다.
- 브랜드/템플릿 version과 콘텐츠 semantic hash를 분리한다. 실제 미주에 모든 채점 단위의 답+풀이를 넣는다.
- 학생용/미주 포함/정답·해설/교사용 출력 모드를 구분하고, Unicode·수식·도형·페이지 넘김을 확인한다.

**현재 파일:** `renderers/{web,hwpx,pdf}`, `core/examdna/rendering.py`, `document/models.py:193–194`, `features/11_brand_template.md`.

**완료 증거:** raw LaTeX/한글 물음표 없음, 실제 equations/endnotes/graphics 존재, 답안 28개의 coverage, 행 정렬·폰트·최종 문항·소문항 공간, 브랜드 변경 전후 내용 동일, 학생용 답안 비노출.

### WP08 — 실제 한글 worker·산출물 proof·최종 다운로드

**의존:** WP07 + Windows 환경 gate. **REQ:** 17·18·19·20.

- 중앙 Windows worker의 상태/단일 COM 작업/격리 디렉터리/timeout/recycle을 구현한다.
- 요청 revision의 HWPX만 변환하고 Open/SaveAs/파일/재열기를 검증한다. proof는 실제 생성 파일을 대상으로 한다.
- 구조 비교와 독립 렌더 검사로 수식/도형/미주/내용/배치 불일치를 검출한다. OCR이 수식을 못 읽으면 확인 불가로 남기고 구조 검사만으로 통과하지 않는다.
- 최종 다운로드 권한은 artifact별 proof와 tenant/삭제/권한을 확인한다.

**현재 파일:** `renderers/hwp/worker.py`, `qa/hwp_proof.py`, `core/examdna/export_verification.py`, `zero_typo_gate/gate.py`, `documents.py:168–198`.

**완료 증거:** 최신 v2에서 바로 HWP 생성, 한글 미설치/파일 없음/SaveAs 실패/멈춤/재시작 처리, 악의적인 중간 파일 혼입 방지, 두 학원 작업의 교차 오염 0건, HWP 실패 시 해당 포맷 차단, 독립 PDF proof를 통과한 파일의 정확한 상태.

### WP09 — 웹 전체 여정·팝업·반응형 완성

**의존:** WP01·02; 계약별 mock으로 병렬 작업을 시작한 후 WP03–08과 실제로 연동한다. **REQ:** 01·02·12·13·16·19·22·23·28.

- 03 문서의 모든 페이지/역할/빈·로딩·실패 상태를 구현한다. 교사에게 CLI/API 키/COM 설정 작업을 요구하지 않는다.
- source comparison/변경 계획/이력/충돌/삭제 등의 팝업은 정해진 포커스·닫기·중복 제출 정책에 따라 만든다.
- 모바일 패널 전환, 문항 선택과 preview 연결, 한국어 IME, 키보드/색 대비를 검증한다.

**현재 파일:** 기존 5개 `frontend/app/**/page.tsx`, `layout.tsx`, `globals.css`, `lib/api.ts`; 신규 경로는 03 문서에서 정의한다.

**완료 증거:** 새 학원의 웹 온보딩부터 다운로드까지 E2E; 360/390/768/1280px, light/dark, keyboard, 한국어 IME, 404/403/offline/409/quota/중단 복구. 스크린샷만으로 버튼 연결이 완료되었다고 보고하지 않는다.

### WP10 — 운영·보안·개인정보·비용·복구

**의존:** WP01–09. 최소 관측 기능은 앞 단계부터 적용한다. **REQ:** 20·21·24·25·26·28.

- 학원별 rate/budget/concurrency와 global provider 한도, usage reservation/settlement, 공정성을 시험한다.
- retention/삭제/복원/backup expiry와 권한 회수/지원 접근을 시험한다. 장애·migration rollback·restore runbook을 완성한다.
- 비용/대기/실패/누락 검토/worker health 지표를 운영자 dashboard에 제공한다. 학생 본문·키·전체 모델 응답을 기본 로그에 남기지 않는다.

**완료 증거:** cross-tenant 부정 테스트, queue fairness, quota 경합/중복 정산, backup 복구 실행, worker 재시작/DB 복구, 업로드 공격/프롬프트 인젝션, 보관 정책 설정의 일관성. 실제 사용 예산이 없으면 무제한 기본값으로 출시하지 않는다.

### WP11 — 독립 평가·파일럿·출시 패키지

**의존:** 모든 필수 WP 완료 및 배포 gates. **REQ:** 전부.

- 04 테스트 문서의 F0–F4 구분과 AT001–060을 실행하고, REQ/A/S/WP 결과를 TRACEABILITY에 기록한다.
- 원본의 실제 추론/미사용 평가 세트/한글 실행/브라우저 흐름/운영 복구를 독립적으로 확인한다. 모델 결과를 expected로 역산해 평가에 쓰지 않는다.
- 파일럿 관측 기간에 critical 문제가 발견되면 해당 출고를 차단하고, 원인·영향받는 revision·회귀 테스트·재발 방지를 기록한다.
- README/setup/config/migrations/backup/지원/장애/rollback/계정·사용권/모델 버전/known limitations를 인계한다.

**완료 증거:** REQ별 PASS/FAIL/NOT_RUN, proof 첨부, 실제 artifact hash, 테스트 환경과 버전, 수동 검토자/범위, 배포 결정. `NOT_RUN`을 PASS로 합산하지 않는다. 모든 format을 지원한다고 출시하려면 3종 모두 실제 환경에서 통과해야 한다.

## 4. 배포 단계와 비용·기간 보고

1. **개발 baseline:** 기존 코드/오류 재현/기준 데이터 분리/환경 결정. 외부 유료 서비스가 없어도 계약과 오프라인 테스트를 진행할 수 있다.
2. **내부 Alpha:** 심원중과 공격/오류 fixture로 문서 한 개의 전체 여정을 완성한다. 이 단계만으로 모든 학교의 정확도를 홍보하지 않는다.
3. **제한 Pilot:** 승인된 자료로 여러 학원/역할/동시성을 확인한다. 지정 QA 검토자가 출고물을 전수 점검하고, 사용 시간/비용을 측정한다. 일반 교사에게 매번 전체 재검수를 요구하는 제품 UX와는 별개인 출시 검증이다.
4. **V1 공개 출시:** 독립 holdout·실제 한글·보안·복구와 배포 gate를 통과한다. 지원 범위/제약을 명시한다.

달력 일정과 총비용을 근거 없이 확정하지 않는다. Devin은 WP00 종료 시 기술 검증 결과에 따라 각 WP의 예상 소요·병목·외부 의존·검증 시간을 업데이트한다. HWP 객체/도형 재작도/실제 proof를 단순 CRUD와 같은 난이도로 견적 내지 않는다.

## 5. Devin의 매 PR 보고 형식

```text
WP / REQ / 관련 A·S·AT:
문제와 수정 후 동작:
변경 파일/계약 및 마이그레이션:
실행한 테스트와 결과(로그/환경/commit):
실제 사용자 흐름/산출물 증거:
남은 FAIL / NOT_RUN / 운영 결정:
기존 자료 보존 및 rollback 방법:
다음 진행 가능한 WP / 실제 blocker:
```

독립 검토자는 구현자가 “문제없음”이라고 적은 문장을 승인 근거로 삼지 않는다. 원본 입력·실제 파일·불변 조건·테스트 실행 결과를 확인한다.


