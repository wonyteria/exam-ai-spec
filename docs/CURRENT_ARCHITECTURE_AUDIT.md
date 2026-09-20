# CURRENT_ARCHITECTURE_AUDIT

Master Spec v3.1 §59 산출물. 작성일: 이 커밋 기준.
분석 대상: `D:\플랫폼\exam_ai_spec\project` (backend), 기존 RESTORE-00~09 커밋 완료 상태.

---

## 1. 현재 구현 상태 요약

기존 파이프라인은 `backend/core/examdna/pipeline.py`의 `STAGES`로 정의된
선형 단계 집합이다:

```
preprocessing → student_trace → print_layer → segmentation →
recognition → source_verification → logic_verification → solving →
rendering → export_verification → zero_typo_gate
```

실행 경로는 두 갈래다:
- `jobs/worker.py::_execute` — canonical `JobV2` 리스 하에 STAGES를 돌리고
  RESTORE revision + content checks를 커밋하는 **프로덕션 경로**.
- `jobs/runner.py::run_pipeline` — 레거시 `jobs.Store` 기반 실행
  (테스트/골든 리플레이/로컬 개발용).

| 영역 | 상태 | 근거 |
|---|---|---|
| 소스 불변성·해시·PDF 인벤토리·좌표 앵커 | 구현됨 (RESTORE-01) | `preprocessing.py`, `document/anchors.py` |
| OCR/레이아웃 provider = 후보 전용 | 구현됨 (RESTORE-02) | `providers/`, `recognition/runner.py` |
| 페이지 역할·문항/단 분할·검수 패키지 | 구현됨 (RESTORE-03) | `document/page_roles.py`, `document/review.py` |
| 6클래스 층 마스크·겹침→검수·안전 복원 | 구현됨 (RESTORE-04) | `student_trace/layers.py`, `separator.py` |
| 독립 출처 합의·confidence 단독 확정 금지 | 구현됨 (RESTORE-05) | `source_truth/consensus.py` |
| FigureGraph 시맨틱 검증 | 구현됨 (RESTORE-06) | `document/scene.py`, `scene_semantics.py` |
| 기대 manifest 커버리지·산출물 해시 게이트 | 구현됨 (RESTORE-07) | `document/manifest.py`, `qa/artifact_proof.py` |
| HWPX/HWP/PDF 왕복 증명·역검증 | 구현됨 (RESTORE-08) | `qa/hwp_proof.py`, `renderers/hwp/worker.py` |
| family 홀드아웃 분할·릴리스 게이트 | 구현됨 (RESTORE-09) | `eval/splits.py`, `eval/report.py` |
| 파이프라인 산출물 → canonical artifact 등록 | 구현됨 | `jobs/artifact_bridge.py` |
| 테스트 | 272 passed | `backend/tests/` 36개 파일 |

Baseline 재현 (Gyenam 7p image-only PDF, provider 미설치):
`questions=0, atus=0, source_immutable=true, elapsed≈118s → NEEDS_REVIEW`.
이는 fail-closed 정상 결과다(인식 증거 없음 → 미검증).

## 2. 신규 명세(v3.1)와의 매핑 — 간극 분석

| 명세 개념 | 현재 대응 | 간극 |
|---|---|---|
| SourceDNA | `PageImage` + SHA-256 + PDF 인벤토리 | 필드 대부분 존재. DPI/orientation/color_profile 일부만 |
| Derived Asset + transform chain | `variants`(grayscale/high_contrast/binarized) + 역변환 앵커 | variant가 3종뿐. 명세는 300/400dpi·deskew·dewarp·shadow·channel 분리 등 다수 후보 요구 |
| PDF 분류 DIGITAL/SCANNED/HYBRID | `image_only` 플래그 수준 | 3-way 분류 + native text/vector/font 추출 미구현 |
| LayerDNA (14클래스) | 6클래스(print/figure/red/dark/pencil/overlap) | PENCIL/BLACK/BLUE/RED/GRADING/HIGHLIGHTER/PAPER_ARTIFACT 분리와 PRINT_WRITING vs PRINT_GRADING overlap 구분 부족 |
| RegionDNA (영역 어휘) | 문항/단 분할 + page_role | HEADER/FOOTER/CONDITION/SCORE/ANSWER_SPACE 등 영역 타입 체계 없음 |
| ReadDNA (RecognitionCandidate 공통 인터페이스) | Candidate/ATU + provider provenance | 인터페이스는 유사하나 다중 observer benchmark 연결 없음 |
| MathDNA/MathATU (critical token·AST) | `document/math_ast.py` + critical token 정책 | Math OCR provider는 stub 수준. AST 동치 검증은 부분적 |
| FigureGraph | scene.py + 시맨틱 검증 | 어휘·관계는 확장됐으나 픽셀→그래프 추출기 자체는 미구현 |
| ProblemDNA/ProblemGraph | **없음** | 문항 의미 모순 검출·교육과정 guard 없음 |
| SolveDNA (SymPy 결정적 검증) | solver provider stub + LLM 경로만 | SymPy 미사용. LLM 결과의 deterministic 재검증 없음 |
| EvidenceDNA (EvidenceBundle 4클래스) | consensus.py의 출처군 분리 | SOURCE/OBSERVATION/CONSISTENCY/HUMAN 클래스 명식화 부족 |
| Reconstruction Status taxonomy | ATU status (UNVERIFIED/CONFLICT/…) | occlusion(NONE/PARTIAL/FULL)과 SOURCE_CONFIRMED/CROSS_VERIFIED 체계 미분리 |
| Routing Engine (Tier 0~5) | 없음 | region 타입별 provider 라우팅·escalation 정책 없음 |
| ProofDNA / VERIFIED_FINAL | manifest + zero_typo_gate + artifact proof | 가장 잘 정렬된 영역 |
| Document Engine (HWPX/HWP/DOCX/PDF) | HWPX + HWP(COM) + PDF | DOCX 렌더러 없음 |
| AcademyDNA | 리브랜딩 경로 존재 (검수·allowlist·한글 증명) | style profile 추출/학습은 없음 |
| QuestionDNA/Exam Agent/Variation | `editing.py`의 op 변환만 | 난이도/변형/작문 엔진 없음 (명세상 후속 단계) |
| Benchmark harness | 골든 리플레이 + eval split만 | 동일 fixture 다중 provider 비교 프레임워크 없음 |
| Review UI | 검수 패키지 JSON만 | overlay/diff/layer 시각 UI 없음 |
| Gold Reference 격리 | family split + sealed_at | fixture dir 분리는 규약 수준. 코드 강제 없음 |

## 3. 유지할 코드

- `document/models.py`, `anchors.py`, `manifest.py`, `scene*.py`,
  `page_roles.py`, `review.py` — canonical 모델·앵커·검수 spine.
- `student_trace/` 6클래스 증거 기반 분리기(정책 기반, 비파괴).
- `source_truth/consensus.py` 독립 증거 정책.
- `qa/`, `eval/`, `jobs/artifact_bridge.py`, `renderers/hwpx|hwp|pdf`,
  `canonical/` — 증명·게이트·export spine.
- `providers/` 어댑터 골격(이미 provider-인터페이스 분리).

## 4. 수정할 코드 (우선순위)

1. `preprocessing.py` — variant 집합 확장(deskew/dewarp/shadow/channel)과
   variant별 OCR 라우팅을 위한 자산 메타데이터.
2. `student_trace/layers.py` — 6→14 클래스 taxonomy 확장, 색상 채널별
   분리 증거, overlap subclass.
3. `recognition/` — RecognitionCandidate 공통 인터페이스 명식화
   (bbox_original/bbox_asset/model_version/raw_output/timestamp 필드).
4. `verification/solving.py` — SymPy deterministic verifier 추가
   (LLM 결과 재검증).
5. `consensus.py` → EvidenceDNA bundle 형태로 승격 (4 evidence class).
6. PDF 분류기: DIGITAL/SCANNED/HYBRID + native evidence 추출.

## 5. 격리할 코드

- `providers/gemini/`, `providers/openai/` — operational adapter는 유지하되
  기본값 비활성 정책 유지. 고객 데이터는 기본 로컬/mock.
- `jobs/runner.py` 레거시 경로 — 테스트/리플레이 전용으로 한정 문서화.

## 6. 폐기 후보

- 없음. 다만 `renderers/web/preview.py`는 검수 UI의 프로토타입으로만 간주.

## 7. 신규 architecture와 충돌하는 부분

- **LayerDNA taxonomy 불일치**: 현재 6클래스는 명세 14클래스의 부분집합.
  마스크 스키마 버전업 + fixture 재생성 필요 (RESTORE-04 캐시 마이그레이션
  경험 있음).
- **단일 전처리 결과 소비**: recognition이 variant 선택 없이 기본 이미지를
  주로 사용 → 명세의 "고정 전처리 결과만 사용하지 않는다"와 충돌.
- **problem/solve 단계 없음**: 현재 `solving`은 답 생성 위주. ProblemGraph
  기반 모순 검출과 분리 필요.

## 8. 현재 known failure

- provider 없는 환경에서 image-only PDF → `questions=0` → NEEDS_REVIEW
  (의도된 fail-closed).
- PaddleOCR/torch 미설치 환경에서는 로컬 OCR 경로 자체가 NOT_RUN.
- 실제 Hancom 미설치 환경에서 HWP 증명 NOT_RUN (의도됨).
- DOCX export 부재.

## 9. 현재 test coverage

272 tests 전체 통과. 영역별: canonical/tenancy, 업로드/작업, 전처리·층분리,
segmentation, consensus, scene semantics, manifest/gate, HWP 증명,
골든 리플레이, rebrand(47), eval split(14), artifact bridge(10).
모든 수치는 dev-split 증거다 — 홀드아웃 미확보로 실사용 정확도는 미측정.
