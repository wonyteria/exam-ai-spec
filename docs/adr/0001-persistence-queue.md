# ADR-0001: 영속성·객체 저장·내구 작업 큐

상태: 제안(구현 방향 고정), 외부 서비스 자격증명 보류(RG-01/RG-02)
날짜: 2026-09-19

## 결정

- canonical metadata·revision·job·event·proof·audit는 **PostgreSQL**에 저장한다.
- 원본 blob·업로드·최종 artifact는 **private object storage**(S3 호환 또는 블록 스토리지)에 두고, API는 서버 검증 뒤 단기 서명 URL로만 노출한다.
- durable 작업 큐·job event·SSE replay cursor는 **같은 DB의 테이블 기반 durable queue**로 시작한다(worker lease·fencing·at-least-once). 단일 broker 구성이라도 멱등 실행·재시도·dead-letter는 API 계약에 포함한다.
- 로컬 개발 환경에서는 SQLite + 로컬 FS 어댑터를 병행 지원해 개발기에 DB 서버 설치를 강요하지 않는다. 단, CI/검증은 PostgreSQL 대상으로 수행한다.

## 근거

- process-local dict/JSON file은 재시작·다중 인스턴스·병행 갱신·증명 불변성을 충족할 수 없다(A03/A13).
- 구독형 외부 DB·broker는 계정/결제 승인이 필요하므로, 자기 호스팅 PostgreSQL + 로컬 dev 어댑터가 승인 없이 진행 가능한 최소 경로다.
- DB 기반 큐는 전용 broker 추가 없이 lease/fencing/replay 커서를 구현할 수 있고, 이후 필요 시 broker 교체가 어댑터 뒤에 숨는다.

## 대안

- Redis/외부 broker 즉시 도입 — 불필요한 운영 복잡성과 비용. 멀티 노드 성능 병목이 확인되면 재검토.
- 파일 시스템만 사용 — 거절(위 근거).

## 영향

- 신규 의존성: `psycopg`(또는 `SQLAlchemy`+driver), 마이그레이션 도구(`alembic`), 객체 저장 어댑터. → ADR-0005 승인 대상.
- 스키마: `tenant/membership/document/revision/artifact/proof/job/job_event/idempotency` 테이블 — WP01~WP03에서 정의.
