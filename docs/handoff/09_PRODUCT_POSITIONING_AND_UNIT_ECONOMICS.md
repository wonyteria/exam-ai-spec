# 제품 포지셔닝·디자인·성능·단위경제성

작성일: 2026-09-19  
상태: 제품·개발 의사결정 기준. 가격은 실측 파일럿 전 provisional이며 결제 화면에 확정가처럼 노출하지 않는다.

## 1. 반드시 이겨야 하는 지점

제품 의사결정 순서는 **기능적 안정성 > 편리함 > 성능 > 가격 > 기능 수**다. 낮은 가격이나 빠른 응답을 위해 검증·proof·복구를 줄이지 않는다. [경쟁 서비스 도움말·업데이트 심층 검토](./MATHTAILER_HELP_UPDATE_DEEP_DIVE.md)의 반복 결함을 출시 gate에 반영한다.

ExamAI Spec은 설치형 PDF→HWP 도구가 아니라 여러 학원이 브라우저에서 바로 쓰는 시험지 복원 운영체제다.

- 설치 0: 교사 PC에 한글, 변환 프로그램, worker, CLI를 설치하지 않는다.
- 외부 API 키 0: 교사가 OpenAI·Gemini·Claude 계정이나 키를 만들지 않는다.
- 설정 0에 가까운 시작: 가입→학원 생성/초대→파일 업로드까지 3분 이내가 목표다.
- 품질 실패 은폐 0: 원본 충실도와 실제 한컴 proof가 부족하면 해당 파일 다운로드를 차단한다.
- 반복 작업 최소화: preview·재렌더·브랜드 변경은 canonical revision을 재사용하고 같은 AI 작업을 다시 청구하지 않는다.
- 다학원 운영: 역할·비용·문서·작업·원본·crop·artifact·감사 로그를 학원별로 격리한다.

## 2. 디자인 방향

경쟁 서비스의 어두운 기술 홍보형 화면을 복제하지 않는다. 작업 앱은 종이 시험지와 교사의 판단이 중심인 밝고 정돈된 editorial workspace로 만든다.

| 항목 | 기준 |
|---|---|
| 시각 계층 | 흰 종이 preview, 중성 배경, 짙은 ink 텍스트, cobalt 동작색, teal 성공, amber 검토, red 차단 |
| 한국어 | 본문 15–16px, 최소 14px, Noto Sans KR 계열, 숫자·배점·상태의 줄맞춤 고정 |
| 정보 구조 | 전역 학원 바 + 문서 바 + 원본/검토·편집·출력·이력 탭. 내부 용어를 교사 화면에 노출하지 않음 |
| 검토 UX | 원본 crop·현재 값·후보·영향 범위를 한 화면에서 보여 주고 확정 뒤 preview와 revision이 같이 바뀜 |
| 진행 UX | 단계, 현재 작업, 예상 범위, 재시도/취소, 오류 원인과 복구 동작을 표시. 무한 spinner 금지 |
| 모바일 | 360px에서 단일 작업 패널. 원본/편집/preview를 전환하며 가로 스크롤 금지 |
| 접근성 | WCAG AA 대비, 항상 보이는 focus, keyboard-only, Escape·focus trap, 한국어 IME, screen reader 이름 |

첫 결과 전에 보여 주는 필수 선택은 학교/학년/시험 종류와 파일뿐이다. 모델명, API 키, 수식 엔진, COM, worker, 프롬프트, 좌표는 고급 운영 화면에도 기본 노출하지 않는다.

## 3. 성능 예산과 SLO

아래 수치는 지원 corpus의 파일럿에서 측정한 뒤 공개 약속으로 승격한다. 미측정 수치를 마케팅 문구로 사용하지 않는다.

| 구간 | 내부 목표 |
|---|---:|
| 주요 웹 화면 LCP p75 | 2.5초 이하 |
| INP p75 | 200ms 이하 |
| 파일 선택 후 큐 표시 | 100ms 이하 |
| 업로드 완료 후 job 생성 p95 | 2초 이하 |
| 작업 시작/재시도 후 첫 진행 이벤트 p95 | 2초 이하 |
| 10페이지 standard preview p50 / p95 | 90초 / 180초 이하 |
| 승인 후 HWP proof p50 / p95 | 30초 / 60초 이하 |
| API 오류 뒤 사용자 입력 보존 | 100% |
| 최종 artifact proof 통과율 | 99.5% 이상, 실패는 다운로드 차단 |
| 교차 tenant 데이터 노출 | 0건 |

처리량은 페이지를 병렬로 무조건 호출해 얻지 않는다. provider 한도, 학원별 공정성, 비용 예약, HWP COM 단일 작업을 함께 만족해야 한다. first useful preview를 먼저 만들고 나머지 검증은 단계적으로 표시한다.

## 4. 원가 모델

운영 추론은 서버용 OpenAI API 계정으로 결제한다. 개인 Codex 구독은 개발·검증용이며 SaaS 원가를 대체하지 않는다.

2026-09-19 공식 문서 기준 `gpt-5.6-luna`는 이미지 입력·Structured Outputs를 지원하고 100만 토큰당 입력 $0.20, 캐시 입력 $0.02, 출력 $1.20이다. `gpt-5.6-terra`는 입력 $2.00, 캐시 입력 $0.20, 출력 $12.00이다. 환율·가격 변동을 흡수하기 위해 내부 예산 환율은 1달러=1,500원으로 잡는다.

출처:
- https://developers.openai.com/api/docs/models/gpt-5.6-luna
- https://developers.openai.com/api/docs/pricing
- https://platform.openai.com/docs/api-reference/batch

표준 완성 페이지의 초기 비용 가설은 아래와 같다. 실제 usage ledger가 이 가설을 교체한다.

| 원가 항목 | 가설/페이지 |
|---|---:|
| Luna extraction: 3k input + 800 output | 2.34원 |
| 캐시된 Luna 검증/풀이: 2k cached input + 600 output | 1.14원 |
| Terra 예외 승격: 페이지 8%, 2k input + 600 output | 평균 1.34원 |
| Windows/Hancom·스토리지·전송 | 2.50원 |
| retry·지원·환율 reserve | 1.00원 |
| 결제비용 배분 | 약 1.00원 |
| **초기 목표 COGS** | **9.32원 이하** |

복잡 페이지 비중과 실제 이미지 토큰이 가장 큰 불확실성이다. 일별로 `revenue`, provider usage, worker 시간, storage/egress, payment fee, 무료 재처리, 지원 reserve를 합쳐 페이지·문항·학원·요금제별 contribution margin을 계산한다.

## 5. provisional 가격 구조

경쟁 공개가 40원/페이지 변환, 20원/문항 문제은행을 안내한다. 초기안은 아래처럼 더 단순하고 낮은 체감 단가를 제공하되, 할인·미사용량에 기대지 않고 100% 사용 시에도 이익을 남겨야 한다.

| 상품 | 초기안 | 포함 기능 | 목표 총이익률 |
|---|---:|---|---:|
| 빠른 복원 | 19원/페이지 | 본문·수식·도형·레이아웃 복원, HWPX/PDF | 70% 이상 |
| 검증 완성본 | 29원/페이지 | 답·풀이·미주·독립 검증·HWP proof 포함 | 65% 이상 |
| 학원 | 월 49,000원 / 2,000페이지 | 5명, 검증 완성본, 초과 25원/페이지 | 완전 사용 시 60% 이상 |
| 다학원 | 월 119,000원 / 5,000페이지 | 15명, 학원 전환·브랜드·사용량, 초과 24원/페이지 | 완전 사용 시 60% 이상 |

첫 20페이지는 품질 확인용 무료 체험으로 제안한다. 같은 revision의 preview·HWPX/PDF/HWP 재생성과 플랫폼 장애 재시도는 중복 청구하지 않는다. 사용자가 원문을 바꾸거나 새로운 풀이·변형을 요청하면 예상 비용을 먼저 보여 준다.

가격 공개 전 필수 조건:

1. 최소 200페이지·5개 난이도/형식 corpus에서 실제 COGS 분포를 측정한다.
2. p50뿐 아니라 p95와 최악 5% 페이지의 비용·지연·검토 시간을 확인한다.
3. 완전 사용 기준 요금제 총이익률 60%, 전체 혼합 총이익률 65%를 넘지 못하면 가격·라우팅·지원 범위를 조정한다.
4. 품질 실패 재처리 비용을 고객에게 넘겨 margin을 맞추지 않는다.
5. 무제한 요금제, 숨은 API 비용, 자동 유료 provider fallback을 출시하지 않는다.

## 6. 원가를 낮추는 구현 순서

1. decode, 회전, 순서, 파일 검증, 수식 AST, layout, HWP proof는 deterministic 처리한다.
2. Luna로 페이지 구조·필드 후보를 한 번 생성하고 누락 영역만 재호출한다.
3. program verifier와 수학 solver가 통과한 항목은 Terra로 보내지 않는다.
4. 불일치·낮은 confidence·도형 관계·풀이 모순만 Terra로 승격한다.
5. 동일 prompt/schema의 고정 prefix는 prompt caching을 사용한다.
6. 즉시성이 필요 없는 풀이·대량 검증은 Batch API 적합성을 검증한다.
7. canonical content가 같으면 브랜드·출력 모드 변경은 AI 없이 재렌더한다.
8. tenant별 예산을 예약하고 실제 usage로 정산하며 중복 idempotency key는 한 번만 청구한다.

## 7. 제품·사업 KPI

| KPI | 출시 목표/guardrail |
|---|---:|
| 가입→첫 최종 파일 성공률 | 70% 이상 |
| 첫 최종 파일까지 교사 작업 시간 | 5분 이하 |
| 자동 처리 뒤 검토 채점 단위 비율 | 10% 이하 |
| 최종 파일 재작업/환불률 | 2% 이하 |
| 100개 시험당 지원 문의 | 2건 이하 |
| 월간 학원 재사용률 | 70% 이상 |
| rolling 30-day gross margin | 65% 이상 |
| AI API 비용 / 매출 | 30% 이하 |
| 플랫폼 장애 재처리 고객 과금 | 0원 |

margin이 기준 아래로 내려가면 프로모션 확대보다 원인 분해가 먼저다. 모델 승격률, output token, cache hit, hard-page 비중, worker idle/timeout, 무료 재처리, 지원 시간을 각각 확인한다.

## 8. Devin 완료 증거

- 설치·API 키 없이 새 학원이 첫 파일을 받는 E2E
- 위 SLO를 측정하는 tracing과 p50/p95 dashboard
- 페이지·문항·tenant·job별 cost ledger 및 idempotent 정산
- 가격 preview와 실제 usage 차이, quota·예산 부족 복구 UI
- Luna-only/Luna→Terra routing의 품질·비용 비교
- 100% allowance 사용 시 요금제별 margin 시뮬레이션
- 실제 한컴 proof 실패·provider 재시도 비용을 포함한 monthly close report

실측 증거 없이 `더 빠름`, `더 정확함`, `더 저렴함`, `고수익`을 출시 문구로 선언하지 않는다.
