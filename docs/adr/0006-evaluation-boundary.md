# ADR-0006: 평가 경계 — seeded 골든·캐시 replay·독립 검증

상태: 확정(테스트로 강제됨)
날짜: 2026-09-19

## 결정

- `samples/golden_001/expected.json`은 **seeded replay 자료**다. 정답 오라클이나 모델 정확도 증거로 사용하지 않는다.
- `samples/golden_001/reference_draft.json`은 **독립 검산 초안**(`F2_DRAFT_PENDING_INDEPENDENT_REVIEW`). QA 확정 전까지 golden으로 승격하지 않으며, `must_not_feed_model_input: true`로 모델 입력 주입을 금지한다.
- cache replay 결과는 provenance `replay_cache`로 기록한다. 두 번의 캐시 읽기는 독립 검증으로 인정하지 않는다.
- offline 테스트는 실제 SDK import·네트워크 호출 없이 동작한다(`tests/golden/replay.py`의 `CacheReplayProvider`). 캐시 miss는 즉시 실패다.
- `VERIFIED_FINAL` 같은 상태 문자열은 증명 없이 표시하지 않는다. seeded가 그 상태를 주장해도 테스트는 구조·정답 결함을 그대로 고정한다.

## 근거

- seeded expected는 오답 7개(2·4·8·9·10·14·20)와 구조 결함(29행/114점 vs 요구 31노드/28채점단위/100점)이 확인됐다(S02/S03).
- A34: 캐시 miss가 실제 SDK 호출로 이어지는 경로는 offline CI를 깨고 비용·네트워크 통제를 무력화한다.
- A33: missing 문항을 무시하면 회귀가 실패를 숨긴다.

## 강제 수단

- `backend/tests/test_seeded_baseline.py` — 오답 7개·구조 결함·승격 금지 플래그를 고정.
- `backend/tests/golden/harness.py` — missing>0도 regression에 포함.
- `backend/tests/golden/replay.py` — SDK 미의존 replay provider, miss=CacheMiss.
- `backend/tests/test_golden_replay.py` — provider를 replay로 교체.

## 영향

- 이후 독립 평가는 잠금 평가 세트·별도 QA 환경에서 수행하며, 개발 세트 정답은 평가 입력으로 재사용하지 않는다(08_CORPUS_AND_CONTINUOUS_TESTING.md §4).
- "두 독립 풀이 일치" 요구는 같은 캐시 두 번 읽기로 충족되지 않는다 — 별도 실행 경로가 필요하다(ADR-0003).
