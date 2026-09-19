# WP08 Report — 실제 Windows HWP worker · proof · 최종 다운로드 게이트

Date: 2026-09-19  
Commit base: `71449af` (WP07)

## 이번 작업 범위

- `backend/renderers/hwp/worker.py`
  - 단일 COM 작업 락(`_lock`) 추가
  - 요청별 격리 임시 디렉터리에서 `HWPX Open -> HWP SaveAs -> HWP 재열기 -> PDF SaveAs`
  - 프로세스 격리(`multiprocessing`) + timeout(`EXAMDNA_HWP_TIMEOUT_SECONDS`) + recycle 카운터 메타
  - 결과 hash 계산 및 proof payload(`request_revision`, worker_identity, sha256) 반환
- `backend/app/api/v1.py`
  - `POST /api/v1/tenants/{tenant}/documents/{doc}/artifacts`의 `hwp`/`pdf` 생성 경로를 실제 Windows worker로 연결
  - hwp/pdf artifact 등록 시 proof 자동 기록(`record_proof`) 및 revision 결속
  - worker unavailable 시 `503 HWP_WORKER_UNAVAILABLE` fail-closed
- `backend/tests/test_wp08.py` 신설
  - worker proof 결속 및 최종 다운로드
  - worker unavailable 차단
  - 최종 artifact blob 변조 시 hash mismatch 차단

## 회귀 테스트

- `python -m pytest backend/tests/test_wp08.py -q` → **3 passed**
- `python -m pytest backend/tests/test_canonical.py -q` → **16 passed**
- `python -m pytest backend/tests/test_wp07.py -q` → **16 passed**

## 실제 산출물 증거 (로컬)

경로: `backend/data/wp08_proof`

- `proof_manifest.json` (독립 로그/manifest)
  - 단계 반환값: `open_hwpx=true`, `saveas_hwp=true`, `reopen_hwp=true`, `saveas_pdf=true`
  - 요청 revision: `wp08-proof-revision`
  - tenant: `wp08-proof-tenant`
- `proof_input.hwpx`
  - sha256: `3423317b578f14f82fd79cf97a2e22e482ed503208c92c5986cb42b3ff92a996`
  - bytes: `5618`
- `proof_output.hwp`
  - sha256: `a92c4cd38a8f857b16fa84e2e19cd4357ae99eca32607abea19ff10ea5080559`
  - bytes: `14848`
- `proof_output.pdf`
  - sha256: `445980eda21f113b34bfadb19783c7899ebaf8e36ea146a6400f2271f9ed2680`
  - bytes: `16139`

## 확인된 fail-closed 동작

- HWP worker 미가용: `503 HWP_WORKER_UNAVAILABLE` (format 차단)
- proof/hash 불일치: final download `409 HASH_MISMATCH`
- stale/missing proof 또는 non-final 상태: 기존 `export_final` / final download 게이트 유지
- artifact 생성 시 proof manifest를 별도 blob으로 저장하고 tenant/document/revision/content/style/solution hash를 함께 기록

## 아직 남은 항목 (사실 상태)

- **BLOCKED/NOT_RUN**
  - 실제 Hancom COM 재열기 결과(`Open` true) 콘솔 로그를 세션 타임아웃 제약 내에 수집하지 못함 (산출물 파일은 생성됨)
  - 벡터 도형(`hp:rect`/`hp:line`) 자체 출력은 구현/테스트 완료, 한컴 실렌더 픽셀 비교 자동화는 미완료
  - 브라우저 E2E(팝업/반응형/접근성) 및 WP09 여정
  - frontend lint/build/e2e는 실행 로그 회수했으나, WP09 전체 시나리오(403/404/409/quota/offline 전수)는 미완료

## 요약

WP08의 핵심 경로(실제 worker 기반 hwp/pdf 생성, proof/revision/hash 결속, fail-closed 다운로드 차단)는 코드/테스트 수준으로 연결했다.  
다만 실 Hancom UI/COM 재열기 성공 로그의 완결 증거와 벡터 도형 실렌더 비교는 아직 완료되지 않아 WP08은 **IN_PROGRESS** 상태다.
