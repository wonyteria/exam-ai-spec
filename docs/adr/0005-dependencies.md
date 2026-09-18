# ADR-0005: 신규 의존성 승인 기록

상태: 각 항목별 상태 표기. 운영 경로 신규 의존성은 승인 전 설치/커밋하지 않음
날짜: 2026-09-19

의존성 추가는必要性·대안·라이선스·운영 비용·보안·마이그레이션 영향을 기록한 뒤 승인한다. 새 버전은 공개 후 최소 7일 경과한 릴리스를 우선하고, `latest`/`*`/상한 없는 범위를 쓰지 않는다.

## 이번 WP00에서 설치된 것

| 패키지 | 버전 | 용도 | 상태 | 라이선스 | 비고 |
|---|---|---|---|---|---|
| `pywin32` | 311 | Hancom COM 자동화(기술 검증·중앙 worker) | 승인됨(dev/QA + worker 경로) | PSF | Windows 전용. 비Windows CI에서는 import 격리 필요 |

## 승인 대기 (구현 전 결정 필요)

| 패키지 | 용도 | 대안 | 상태 |
|---|---|---|---|
| `openai` | OpenAI Responses 서버 어댑터(운영 기본) | `httpx` 직접 호출 | 보류 — RG-03 계정/예산과 함께 승인. 그 전까지 mock/cache-only |
| `psycopg`(또는 `SQLAlchemy`+driver) | PostgreSQL 접속 | `asyncpg`, stdlib sqlite3(dev 병행) | 보류 — ADR-0001과 함께 WP01에서 최종 선택 |
| `alembic` | 스키마 마이그레이션·롤백 | 수동 SQL 스크립트 | 보류 — WP01 |
| S3 호환 클라이언트(`boto3` 등) | private object storage | 로컬 FS 어댑터만으로 dev 진행 | 보류 — RG-01 스토리지 선택과 함께 |

## 설치하지 않기로 한 것

| 항목 | 이유 |
|---|---|
| `google-genai`(운영 경로) | Gemini는 운영 기본·자동 폴백에서 제외(ADR-0003). dev 격리 경로도 예산 승인 전 실제 호출 없음 |
| Redis/broker 클라이언트 | DB 기반 durable queue로 시작(ADR-0001) |

## 보안 메모

- API 키·개인 토큰은 환경 변수/시크릿 매니저로만 주입하고 저장소·로그·아티팩트에 기록하지 않는다.
- provider 어댑터는 outbound 호스트를 allowlist로 제한해 SSRF·데이터 유출 경로를 차단한다.
