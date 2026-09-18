# WP01 — 학원 인증·권한·영속 저장소 (구현 기록)

커밋 범위: WP00 이후 두 번째 단위. **REQ:** 01·02·24·25·26·28. **A:** A13(영속성)·A22(권한) 부분. **AT:** AT-001~004 방향(미실행).

## 변경된 동작

- 모든 문서·작업·아티팩트 조회가 **학원 범위**로 제한된다. cross-tenant 요청은 404(존재 비공개), 역할 부족은 403.
- 인증은 세션 쿠키(`examdna_session`, HttpOnly) + **개발 전용** 헤더 stub(`x-dev-user`)이다. stub은 `EXAMDNA_ENV=production`이면 항상 비활성(ADR-0002). 실제 IdP는 RG-02 보류.
- 역할: `owner` / `teacher` / `reviewer`. reviewer는 read·review만 가능 — export·artifact 바이너리 다운로드·canonical 변경 불가(`ROLE_ACTIONS`).
- 원본 업로드는 **private object storage**(`local://` URI)에 불변 저장되고, 파일명은 sanitize된다(경로 탐색·ADS·드라이브 문자 차단). derived 파일은 job workdir에만 기록.
- `tenant_id` 없는 기존 문서는 API에 노출되지 않는다. 이관은 `scripts/import_legacy.py`로 명시적 학원 매핑 + 백업 + 재검증 후에만 이뤄진다.
- 기본 audit log: 업로드·review resolve·편집·export·다운로드·tenant 생성/초대/참여를 SQLite `audit_log`에 기록. owner만 열람.
- 최소 UI: dev 로그인, 학원 선택/생성/전환, 교사·검토자 초대 코드 발급/수락, 학원 범위 문서 보관함.

## 변경 파일

신규:
- `backend/tenancy/{models,db,auth}.py` — Tenant/User/Membership/Invite/Session/DocumentGrant/AuditEvent + SQLite 스토어 + FastAPI 인가 deps
- `backend/storage/local.py` — ObjectStore 계약 + LocalObjectStore + `sanitize_filename`/`check_key`
- `backend/app/api/auth.py` — `/api/auth/{dev-login,logout,me}`, `/api/tenants`(CRUD·switch·invites), `/api/invites/{code}/accept`, `/api/tenants/{id}/audit`
- `backend/scripts/import_legacy.py` — legacy 문서 명시적 이관(dry-run 기본)
- `backend/tests/test_tenancy.py` — 10개 인가/격리 테스트
- `frontend/components/AcademyBar.tsx`

수정:
- `document/models.py`·`jobs/models.py` — `tenant_id` 추가
- `jobs/store.py` — `list_documents(tenant)`·`list_unmigrated()`
- `app/deps.py` — tenancy/object-store 싱글턴, env를 호출 시점에 읽음
- `app/api/uploads.py` — 인가 + tenant 지정 + object storage + 크기/개수 한도 + audit
- `app/api/documents.py` — 모든 라우트 `doc_access` Depends(본문 검증 전 인가), 목록 endpoint, 다운로드 sanitize
- `app/api/jobs.py` — job tenant 인가(SSE 포함)
- `jobs/runner.py`·`core/examdna/{context,preprocessing}`·`recognition/*`·`student_trace/separator.py` — `ctx.resolve_uri`로 `local://` 해석, 전처리는 `document.pages` 사용
- `frontend/lib/api.ts` — credentials/tenant 헤더 + auth/tenant/library 함수
- `frontend/app/page.tsx` — AcademyBar + 문서 보관함

## 실행한 검증

- `python -m pytest` — **36 passed**(기존 26 + 신규 10)
- `tests/test_tenancy.py` 10개: 401 미인증, tenant 생성/membership, 문서 학원 scoping, cross-tenant 전 라우트 404, legacy 문서 비공개, invite/accept, reviewer 권한(읽기 O·export/다운로드/수정 403), teacher export 200, audit 기록/owner-only 열람, 파일명 sanitize, 활성 학원 없음 400
- 세션 쿠키 end-to-end 수동 확인: dev-login → tenant 생성(자동 활성) → upload → list → logout
- `import_legacy.py --data data` dry-run — 기존 31개 unmigrated 문서 탐지 확인
- `npm run lint` clean, `npm run build` 성공(Next 16.3.5)

## 남은 FAIL/NOT_RUN

- IdP 미연결(RG-02 보류) — dev stub만 존재.
- `document_grants` 테이블과 reviewer 역할 제한은 구현됐으나 grant 부여 API는 미구현(필요 시 WP06).
- PostgreSQL/object-storage 외부 서비스 자격증명 미승인(RG-01) — SQLite/로컬 FS 어댑터로 구현.
- SSE `Last-Event-ID` 재접속·idempotency 키·lease/fencing은 WP02 범위 — 미구현.
- AT-001~060 전체 미실행.

## 롤백

`git revert` 이번 커밋. `data/tenancy.db`·`data/objects/`는 새로 생기는 파일이며 삭제하면 이전 상태로 복귀. 기존 문서 JSON은 `tenant_id` 필드만 추가되므로 이전 코드도 파싱 가능(필드 무시).

## 다음 WP

WP02 — canonical revision·CAS·proof/gate 상태·durable job 계약(`baseVersion` 409, idempotency, SSE cursor, artifact 불변 키).
