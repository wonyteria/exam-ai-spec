# AI 실행·비용·운영 설계

이 문서는 모델을 실제로 호출한 성능 보고서가 아니다. 사용자가 확정한 운영 방식인 **다학원 웹 전용 + 중앙 AI/한글 변환 + Codex 구독은 개발·검증**을 구현하기 위한 기준이다.

## 1. 인증과 역할을 분리한다

| 환경 | 인증/실행 | 자료/결과 |
|---|---|---|
| 개발자의 코드 작성·검토 | 개인 Codex 구독으로 앱/CLI 사용 가능 | 코드, 합성/승인된 QA 자료. 계정 사용 한도 소비 |
| 오프라인 CI | API 없는 mocks/cache-only fixtures | network call 0을 강제. 모델 정확도라고 보고하지 않음 |
| 승인된 새 추론 평가 | 별도 평가용 서버 계정·예산 또는 승인된 개발 Codex 실행 | 원본/input hash·model/prompt/schema·usage·결과를 기록 |
| 운영 학원 요청 | 플랫폼의 서버용 OpenAI API 자격 증명 | tenant-scoped jobs, 예산/권한/보관 정책 적용 |
| HWP 변환/proof | 중앙 Windows worker의 별도 서비스 신원 | 최소 권한으로 해당 job의 자료에만 접근. 한컴 환경/사용 조건 확인 |

개인 `auth.json`, 브라우저 세션, Codex 로그인 토큰을 Devin·공개 저장소·운영 서버에 복사하지 않는다. 운영 UI에서 학원 선생님에게 API 키나 Codex/한글 설치를 요구하지 않는다. Gemini는 기본적으로 비활성화하며, 실패 시 자동으로 사용하지 않는다.

Codex CLI가 이미지와 JSON Schema 출력을 지원한다는 것은 개발 평가 도구를 만들 수 있다는 뜻이다. 구독이 중앙 서비스의 모든 사용자 추론 비용을 제공한다는 뜻으로 확장하지 않는다. [Codex 인증](https://learn.chatgpt.com/docs/auth), [비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode).

## 2. 운영 모델 후보와 검증

2026-09-19 공식 API 문서 확인 결과, `gpt-5.6-luna`와 `gpt-5.6-terra`는 이미지 입력과 구조화 출력을 지원한다. 후보 가격은 아래와 같으며, **텍스트 100만 토큰 기준 공개 단가**다. 이미지 입력량, reasoning/output량, 캐시 쓰기, 도구, service tier, 계정/지역, 향후 가격 변경을 별도로 확인해야 한다.

| 후보 | 입력 | 캐시 입력 | 출력 | 평가 역할 제안 |
|---|---:|---:|---:|---|
| GPT-5.6 Luna | $0.20 | $0.02 | $1.20 | 페이지/필드 추출, 정형 변환, 쉬운 검토 |
| GPT-5.6 Terra | $2.00 | $0.20 | $12.00 | 수학/도형 조건·풀이 검증, 불일치 재검토 |

출처: [Luna API 모델](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [Terra API 모델](https://developers.openai.com/api/docs/models/gpt-5.6-terra). 도입 시 계정 접근과 최신 단가를 다시 확인한다. Codex의 모델 가용성과 API 계정 가용성은 각각 확인한다.

기본 품질 비교 실험은 Luna-only와 Luna 추출+Terra 검증이다. 어떤 모델도 이 시험지에서 정확도가 입증된 상태라고 가정하지 않는다. 낮은 reasoning으로 무조건 고정하지 말고, 고정 평가 세트의 결과·예외율·비용을 비교해 가장 저렴한 합격 구성을 선택한다. 상위 모델을 쓴다고 출고 gate를 생략하지 않는다.

## 3. 처리 단계와 호출 최소화

1. 파일 decode/정렬·페이지/메타데이터 기본 검사: 프로그램 처리.
2. 원본 및 필요한 variant의 페이지 구조 추출: 페이지 단위 모델 호출. 검토 대상 bbox와 원본 anchors를 반환.
3. 필수 필드/객체 coverage·순서·배점: 프로그램 검사. 부족한 영역만 재추출.
4. 원문 충실도 및 수학 조건 검증: 초기 추출과 다른 검증 task/run으로 수행. source가 없는 모델 추정값을 사실로 승격하지 않음.
5. 채점 단위별 풀이: 공유 지문과 필요한 조건을 포함한 bounded batch. 답·선택지 매칭/배점/단위/기호는 프로그램으로 추가 검사.
6. 도형/수식 AST→실제 객체·레이아웃·미주 출력: deterministic renderer.
7. 실제 한글 생성 파일 재열기·구조·이미지/페이지 대조: 독립 proof. LLM이 자신의 HTML을 읽고 “정상”이라고 말한 것으로 대체하지 않음.

문항마다 모든 provider를 무조건 반복 호출하지 않는다. 반대로 필수 검증 회차를 줄여 비용을 맞추지 않는다. 누락·불일치는 해당 단위만 재처리하고, unresolved 항목은 검토로 보낸다.

## 4. 캐시와 평가 오염 방지

캐시 키에는 tenant boundary, canonical input hash, source variant/hash와 좌표계, model/version, prompt/schema version, reasoning/config, task kind를 포함한다. 다른 학원의 원본을 내용이 비슷하다는 이유로 캐시 검색 결과에 노출하지 않는다.

`replay_fixture`, `live_provider_cache`, `human_review_resolution`, `imported_reference` provenance를 구분한다. 두 회차에 같은 seeded 답을 넣는 것은 테스트 fixture일 뿐, 독립 풀이 합의가 아니다. 사용자가 확정한 오류 수정은 같은 원문/필드/버전에만 적용하고, 전역 정답 사전으로 무단 재사용하지 않는다.

평가 모델의 입력에는 정답 oracle·사람이 작성한 HWP의 답·이전 모델의 정답이 포함되지 않도록 통제한다. 검증기는 필요에 따라 후보를 볼 수 있지만, 평가 지표에 그 조건을 기록한다. 모델 자체 정답률과 후보 검출률을 혼합하지 않는다.

## 5. 비용·동시성·한도 계약

- 사용자가 시작하기 전에 정책상 가능한 작업인지 확인하고 tenant/project/job 예산을 예약한다. 실제 usage가 도착하면 정산한다.
- API 오류/timeout에서 usage를 알 수 없으면 0으로 가정하지 않고, 사용량 불명 상태와 정산 정책을 기록한다. 같은 요청을 재시도해도 내부 사용량 이벤트를 중복 집계하지 않는다.
- 학원별 동시 작업/페이지/월간 사용량과 전체 provider 한도를 분리한다. 한 학원의 긴 시험지가 다른 학원의 큐를 무기한 막지 않도록 한다.
- 한도 초과는 WAITING_QUOTA 또는 명시적인 budget blocker다. paid tier/다른 provider를 자동으로 결제하거나 전환하지 않는다.
- rate limit/일시 오류에는 retry-after와 지수 backoff, 최대 시도 횟수·전체 deadline을 적용한다. 일일 한도/인증 오류/지원하지 않는 모델은 무한 재시도하지 않는다.
- 취소해도 이미 진행한 외부 연산 비용이 0이 되지는 않는다. 취소 확정 후 late result를 현재 revision/final에 반영하지 않는다.

문서당 비용 추정은 실제 토큰/이미지·호출·재시도 사용량과 단가 버전으로 계산한다. “시험지 한 부당 몇 원” 또는 “구독으로 무제한”이라는 수치를 측정 없이 제시하지 않는다. 교사 화면에는 이해할 수 있는 예상/실제 사용량을, 운영자에게는 상세 ledger를 보여준다.

## 6. 중앙 Windows 한글 운영

Windows/Hancom/필수 폰트/pywin32 등의 환경과 서버 자동화 사용 조건을 WP00에서 확인한다. 한글이 사용자 PC에 설치되어 있다는 사실만으로 중앙 서비스의 운영 조건을 충족한 것으로 보지 않는다.

worker instance마다 한 번에 COM 작업 1개를 처리하고, 변환 job에는 lease와 fencing token을 적용한다. 입력 manifest와 hash를 검증하고 tenant/job별 temp에만 파일을 쓴다. tenant 문서의 script/macro가 실행되지 않는 지원 설정을 검증한다. 멈춘 앱이나 실패한 변환은 정해진 timeout 후 격리·정리하며, 다른 학원의 자료를 이어받지 않는다.

artifact output과 proof는 content revision·renderer/worker/app/font version에 묶는다. 큐 대기·변환·재열기·proof가 서로 다른 단계로 보인다. 다운된 worker를 “검증 생략 후 통과”로 처리하지 않는다.

운영자 runbook에는 cold start, 폰트 오류, COM 등록 실패, SaveAs 실패, 보안 대화상자, 프로세스 누수, 디스크 부족, worker 재시작, 누락 output, 동시 요청, 격리 temp 정리 절차를 포함한다. 실제 환경 검증 없이 mock만으로 HWP 지원 출시를 선언하지 않는다.

## 7. 관측 항목

| 지표 | 목적 |
|---|---|
| accepted jobs / tenant, queue age, active workers | 공정성·지연·용량 판단 |
| stage duration p50/p95, timeout, retry | 전처리/AI/한글 중 병목 구분 |
| provider calls, image/input/output tokens, cache hit, estimated/actual cost | 비용·한도·모델 비교 |
| source issues, print-loss issues, missing objects, solver disagreement | 복원/검증의 실제 품질 |
| review count, resolution time, teacher active time | 교사 부담과 잘못된 자동화 구분 |
| final blocked reasons, format proof failures, stale result rejected | 출고 신뢰·버전 오류 감시 |
| cross-tenant access denied, grant changes, support access, deletes | 보안·감사 추적 |

로그에는 상관 ID와 범주를 기본으로 기록하고, 원본 학생 정보/전체 prompt/응답/키는 기본으로 기록하지 않는다. 진단용 본문 확인은 최소 권한·만료·감사·보관 정책을 갖춘 별도 경로로 진행한다.

## 8. 모델 선택 최종 의사결정표

Devin은 각 구성의 동일한 지원 범위·원본·reasoning 조건을 기록하고, 텍스트/도형/정답/해설/예외 검출/비용/지연을 비교한다. critical 오류를 최종 통과시킨 구성은 비용이 저렴해도 탈락한다. 합격한 구성 중 평균과 꼬리 비용/지연·검토 부담이 낮은 구성을 채택한다.

이번 계획에서는 모델 API를 실제로 호출하거나 개인 구독의 현재 잔여량을 평가하지 않았다. 제품 계약과 비용 관측을 먼저 구현하고, 승인된 평가 예산/자료로 측정한 뒤 routing default를 고정한다.

## 9. 가격과 margin gate

가격·디자인·성능의 통합 기준은 [09 제품 포지셔닝·단위경제성](./09_PRODUCT_POSITIONING_AND_UNIT_ECONOMICS.md)을 따른다. 운영자는 rolling 30-day gross margin, AI API 비용/매출, hard-page 승격률, 무료 재처리율을 함께 본다. 100% allowance 사용 시에도 요금제 총이익률 60%를 넘는다는 실측 없이 할인이나 무제한을 출시하지 않는다.
