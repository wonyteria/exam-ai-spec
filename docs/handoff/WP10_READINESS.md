# WP10 구현 준비 — 운영·비용·보안·보관·복구

작성일: 2026-09-19  
기준 HEAD: `2add7b8`

## 현재 확인된 구현

- `providers/telemetry.py`: provider/model/hash/token/latency/outcome을 기록하지만 process-wide `max_calls`와 메모리 counter다.
- `providers/openai/provider.py`: 호출 전 budget check와 실제 usage 기록 지점이 있다.
- `tenancy/db.py`: tenant·membership·session·grant·audit SQLite 계약이 있다. production DB/SSO가 아니라 dev adapter다.
- `canonical/store.py`: revision·job·artifact 계약과 retention 필드가 있으나 운영 보관 정책 실행기는 없다.
- `storage/local.py`: 안전한 key 검사와 private local URI가 있으나 delete/list/lifecycle/backup 계약이 없다.
- `jobs/store.py`: legacy 파일 저장과 process-local subscriber를 사용한다. tenant fairness와 global capacity 예약이 없다.
- 실제 HWP worker proof와 브라우저 WP09 E2E는 별도 증거가 있다.

## 출시 차단 누락

1. 학원별 월 예산·동시 작업·rate와 전체 provider/worker 한도가 원자적으로 예약되지 않는다.
2. 예상 비용 예약, 실제 usage 정산, 실패/불명 usage, 환불, idempotency 중복 방지 ledger가 없다.
3. 긴 시험지나 한 학원이 큐를 독점하지 않는 fairness scheduler가 없다.
4. soft delete, 복원 가능 기간, purge, 원본·crop·revision·artifact·backup의 일관된 lifecycle이 없다.
5. backup manifest/hash, restore dry-run, 실제 restore·rollback 증거가 없다.
6. support access의 시간 제한·사유·승인·감사와 권한 회수 즉시 반영 시험이 부족하다.
7. 민감 로그 redaction과 prompt/model-output 비신뢰 입력 방어가 운영 경계 전체에 적용되지 않았다.
8. 비용·queue age·worker health·proof 실패·검토율·margin을 tenant/format/model별로 보는 운영 API가 없다.

## 구현 순서

### WP10-A — durable usage ledger

- `backend/operations/models.py`: `PlanPolicy`, `UsageReservation`, `UsageSettlement`, `CostRateSnapshot`, `QuotaDecision`.
- `backend/operations/store.py`: SQLite contract와 PostgreSQL 이동 가능한 transaction interface.
- key: `(tenant_id, idempotency_key, task_kind, revision_id)` unique.
- reserve→dispatch→settle/unknown/refund 상태 전이. unknown usage를 0으로 정산하지 않는다.
- 단가 snapshot, 환율 budget, image/input/cached/output token, provider attempt, worker seconds, storage/egress를 저장한다.

### WP10-B — capacity와 공정 큐

- tenant 동시성, global provider/worker semaphore, weighted round-robin 또는 deficit round-robin.
- queue age 상한과 starvation test. retry는 새 작업처럼 앞줄을 차지하지 않는다.
- quota 부족은 `WAITING_QUOTA`; 인증/지원 불가 모델은 terminal blocker. 무한 retry 금지.

### WP10-C — retention·삭제·복원

- document soft delete→복원 기간→purge request→blob·crop·artifact·cache·audit tombstone 순서.
- legal/support hold가 있으면 purge를 차단하고 이유를 기록한다.
- tenant 폐쇄와 membership 회수 뒤 기존 URL·SSE·download를 즉시 차단한다.
- backup 보관 기간과 production primary 보관 기간을 분리한다.

### WP10-D — backup/restore와 worker recovery

- DB dump + object manifest + sha256 + schema/app version을 하나의 backup set으로 묶는다.
- restore dry-run은 hash·tenant count·document/revision/artifact 관계를 검사한다.
- 새 임시 환경 restore→대표 문서 open/proof→승인 뒤 전환. 기존 환경 rollback 경로 유지.
- HWP worker heartbeat, lease expiry, stuck COM recycle, disk/temp cleanup, font/app version drift를 지표화한다.

### WP10-E — 보안·관측·운영 화면

- 원본 본문·학생 정보·API 키·전체 모델 응답을 기본 로그에 남기지 않는다.
- prompt injection 문자열은 데이터로만 전달하고 경로/코드/도구 지시로 실행하지 않는다.
- `/ops`는 별도 platform operator 권한이며 tenant owner가 접근할 수 없다.
- 학원 owner에게 예상/실제 페이지·비용·quota·재처리와 plan 사용량을 제공한다.
- rolling 30-day gross margin, API cost/revenue, hard-page 승격률, 무료 재처리율을 계산한다.

## 필수 테스트

- 같은 idempotency key의 reservation/settlement 중복 비용 0건.
- 100개 동시 reservation에서 예산 음수·초과 승인 0건.
- 대형 tenant와 소형 tenant 혼합 시 소형 tenant starvation 0건.
- 권한 회수 직후 list/SSE/crop/export/download 모두 403/404 계약.
- soft delete 중 final download 차단, 복원 뒤 revision/hash 동일, purge 뒤 blob 없음.
- backup 한 파일 변조 시 restore 차단; 정상 backup은 새 DB에서 tenant/document/artifact 관계 동일.
- provider 429/503/timeout/unknown usage와 worker crash/restart의 정확한 정산·상태.
- cross-tenant reservation, usage, audit, backup manifest 조회 거부.
- prompt injection fixture가 실행·경로 변경·provider 전환을 일으키지 않음.
- 로그 캡처에 key·학생 이름·원문 전체가 없는 redaction test.

## 완료 증거

- backend 전체 회귀 + `test_wp10_operations.py`, `test_wp10_retention.py`, `test_wp10_security.py`.
- concurrency/fairness 반복 결과와 max wait.
- backup set manifest와 isolated restore report.
- worker restart 전후 동일 artifact proof hash 또는 명시적 새 proof.
- 200페이지 파일럿 사용량을 받기 위한 cost ledger export. 실제 데이터가 없으면 가격/margin은 `PROVISIONAL`.
- `WP10_REPORT.md`, `BACKLOG.csv`, `TRACEABILITY.csv`의 PASS/PARTIAL/NOT_RUN.

production SSO, 관리형 DB/object storage, 결제, 실제 고객 자료, 장기 soak가 없다는 이유로 위 계약·테스트 구현을 멈추지 않는다. 반대로 로컬 SQLite 테스트를 production 준비 완료라고 보고하지 않는다.
