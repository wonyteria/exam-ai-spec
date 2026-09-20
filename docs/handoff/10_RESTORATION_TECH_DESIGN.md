# ExamDNA 시험지 복원 기술 설계

버전: 1.0 · 작성: 2026-09-20  
범위: 시험지 PDF/JPG 원본 복원, 내용 구조화, 근거 보존, 한글 출력 전 검증  
연결 대상: `D:\플랫폼\exam_ai_spec\project`의 기존 MASTER_SPEC / WP 명세  
상태: 기술 설계 제안. 구현·성능·정확도 합격을 의미하지 않음.

## 1. 결정 요약

ExamDNA 복원은 한 번의 OCR이나 사진 지우기 작업으로 끝내지 않는다. 원본을 불변 증거로 보존하고, 원본 좌표에 연결된 인쇄·필기·채점·겹침 후보를 만들고, 문항 내용·수식·도형을 별도 구조로 추출한다. 각 확정 값은 원본 영역, 추출기 버전, 후보와 판정 근거를 갖는다. 원본에서 직접 판별할 수 없는 부분은 깨끗한 대응 HWP/HWPX 또는 독립 검수로만 복구하고, 근거가 없으면 남겨두고 검수 상태로 보낸다.

**HWP/Word로 먼저 변환한 결과를 원본으로 삼지 않는다.** 이미지형 PDF에서 OCR 변환은 문장과 배치의 추정 결과다. OCR 엔진은 원본 이미지와 병렬로 실행해 후보를 제공한다. PDF의 텍스트·벡터 계층이 실제로 존재하면 해당 계층을 별도로 추출하되, 페이지 렌더와 대조한다.

최종 정확도 요구는 다음 운영 계약으로 구현한다.

- 자동 복원률을 높이되, 사람이나 승인된 대응 자료로 확인하지 못한 critical 항목은 최종본으로 내보내지 않는다.
- `VERIFIED_FINAL`은 모든 필수 검증의 증거가 실제 출력 바이트와 연결되고, critical conflict/unverified/missing 항목이 0일 때만 부여한다.
- 어떤 OCR 정확도, confidence 값, 표본 한 건도 임의의 미래 입력에 대한 100% 복원을 보장하지 않는다. 지원 범위 밖 입력은 `NEEDS_REVIEW` 또는 `BLOCKED`가 성공적인 fail-safe 결과다.

## 2. 실제 자료로 확인된 출발점

실험실의 기준 자료는 세 종류다.

| 자료 | 실제 확인 | 기술적 의미 |
|---|---|---|
| 계남고 원본 PDF | 7페이지, 모든 페이지 텍스트 계층 0자 | 원본 페이지 영상이 핵심 증거다. PDF→DOCX/HWP 사전 변환을 정답 추출로 쓸 수 없다. |
| 계남고 참조 HWP 2개 | 객관식 19개, 서술형 부모 1개/하위 3개, 수식 스크립트 213개가 파싱됨 | 대응 문항·수식·도형 후보의 교차 확인에 유용하다. 단, 두 참조가 같다는 사실은 원본과 독립적으로 참임을 입증하지 않는다. |
| 계남고 선택지 비교 | 형식 정규화 후 수식 선택지 17개 토큰열 일치, ㄱ·ㄴ 조합형 8번/12번은 자동 비교 제외 | 수식 자동 비교는 실제 효용이 있으나 지원 범위와 제외 사례를 명시해야 한다. overbar 등 표기 차이와 수식 객체 전체 검수는 별도다. |
| 심원중 사진/HWP | 객관식 점수표기 20개 중 참조 HWP 19개, 원본 12번의 `[3점]` 누락 | 참조 문서도 오류가 있을 수 있다. 참조 HWP를 gold로 무비판적으로 복사하지 않는다. |
| 겹친 도형 표본 | 기존 넓은 필기 마스크가 Q11 도형 인쇄 픽셀의 47.1%, 서술형 도형 인쇄 픽셀의 34.0%와 겹침 | 픽셀 색/밝기만으로 지우는 방식은 도형 선을 손상할 수 있다. |

따라서 첫 검증 코퍼스는 원본 PDF/JPG + 참조 HWP + 독립 검수 결과의 삼각 대조로 만들며, 참조 HWP 자체의 오탈자·배점·수식 크기·누락 도형을 이슈로 유지한다. 이 계남고 표본과 심원중 표본은 개발/회귀용이다. 이들만으로 일반 출시 정확도를 주장하지 않는다.

## 2. 우리만의 기술 핵심 — Evidence-Centered Restoration

차별점은 특정 OCR 모델이나 Github 플러그인이 아니다. 오픈소스 모델은 교체 가능한 후보 공급자다. 자체 기술(ExamDNA)은 서로 다른 증거를 문항별로 묶고, 확정과 출력 권한을 증거 기반으로 통제하는 다음 다섯 엔진의 조합이다.

1. **Source Evidence Spine:** 업로드 원본 hash와 좌표 변환을 PDF page → pixel → question region → ATU → canonical revision → output bytes까지 잇는다. 출력 내용에서 출처 영역으로 역추적할 수 있다.
2. **Overlap-Aware Layer Engine:** 인쇄 문자/수식, 도형 선, 빨간 채점, 진한 펜, 연필, 종이 artifact 및 overlap을 별도 분류한다. 분류와 삭제는 분리되고, 인쇄와 손글씨가 겹치면 preserve/review로 abstain한다.
3. **Cross-View Source Reconciliation:** PDF native objects/OCR 후보/수식 후보/참조 HWP의 표현을 field 단위로 연결한다. 후보 간 불일치를 제거하지 않고 근거와 함께 기록한다. 정확히 대응하는 clean figure/reference만 local transform으로 이용한다.
4. **FigureGraph + MathATU:** 기하·그래프와 수학 문자열을 평문 이미지가 아닌 관계 그래프로 보존한다. 선분/점/교점/각/등변/수직/평행/부호/숫자 오류를 픽셀 유사도와 독립된 의미 수준에서 발견한다.
5. **Proof-Carrying Export Gate:** 문서 결과물은 검증 상태와 최종 artifact hash를 동반한다. 모든 source-critical object가 검증된 동일 bytes에 존재함을 실제 한글 reopen/render/reparse가 보일 때만 downloadable final이 된다.

이 설계는 단일 인식 모델의 성능을 구매해 오는 것이 아니라, 영역별 confidence calibration, 고객 오류 수정 이력, 깨끗한 reference 매칭 코퍼스, 실제 HWP 렌더 결과, 어떤 케이스에서 멈춰야 하는지에 대한 abstention 데이터로 개선된다. 라벨된 데이터를 권리/개인정보 승인 없이 모델 학습이나 외부 분석에 재사용하지 않는다.

## 3. 데이터·증거 구조

### 3.1 Source Truth와 파생 데이터

```text
RawSource (immutable bytes, SHA-256)
  ├─ PdfPageEvidence (native text/vector inventory + rendered page)
  ├─ ImageEvidence (original pixels + orientation/geometry transforms)
  ├─ DerivedVariants (gray/contrast/deskew/dewarp/threshold; reversible lineage)
  ├─ LayerCandidates (print text/equation/figure, red mark, dark pen, pencil, uncertain)
  ├─ RegionCandidates (page role, column, question, choices, score, answer space)
  ├─ RecognitionCandidates (provider, model, output, bbox, confidence, version)
  ├─ ReferenceEvidence (paired HWP/HWPX and its own hash/provenance)
  ├─ HumanReviewEvidence (reviewer, field/region, decision, timestamp)
  └─ CanonicalDocumentRevision (only approved semantic content)
        ├─ VerificationManifest
        └─ Artifacts (HWPX/HWP/PDF, each with output hash and proof)
```

기존 `Document JSON`과 ATU 계약을 확장한다. ATU는 문항 전체 문자열이 아니라 승인 가능한 최소 의미 단위다: 문항번호, 문장/토큰, 숫자, 부호, 도형 라벨, 각/선분 기호, 보기 번호와 내용, 배점, 수식 노드, 도형 객체/관계, 답안 공간, 정답 및 풀이 참조.

최소 근거 필드:

```json
{
  "source_anchor": {
    "source_sha256": "...",
    "page_index": 0,
    "bbox_px": [x, y, width, height],
    "transform_chain": ["pdf_render@300dpi", "deskew:<matrix-id>"],
    "crop_sha256": "..."
  },
  "candidate": {
    "kind": "MATH_TOKEN",
    "value": "AB ⟂ CD",
    "provider": "...",
    "model_version": "...",
    "confidence": 0.0,
    "input_variant_sha256": "..."
  },
  "decision": {
    "status": "UNVERIFIED | AUTO_VERIFIED | HUMAN_VERIFIED | CONFLICT | UNREADABLE",
    "method": "...",
    "evidence_ids": [],
    "reviewer_id": null
  }
}
```

`AUTO_VERIFIED`는 confidence 숫자 하나로 성립하지 않는다. 실제 독립 holdout에서 보정한 필드별 기준, 원본 근거 품질, 다른 증거와의 일치, 입력 지원 범위가 모두 충족되어야 한다. 같은 provider 캐시를 두 번 읽은 값, 같은 모델의 재시도, 참조 HWP 두 개가 서로 같은 사실은 독립 증명으로 계산하지 않는다.

### 3.2 Annotation/레이어 분류

기존 실험 라벨 스키마의 여섯 기본 클래스를 제품 증거 모델로 승격한다.

| ID | 클래스 | 처리 원칙 |
|---:|---|---|
| 1 | 인쇄 문자·수식 | 보존 필수. 수식/숫자/부정어/각·선분 기호는 critical. |
| 2 | 인쇄 도형·그래프 | 선·꼭짓점·라벨·눈금·해칭과 관계를 보존한다. |
| 3 | 빨간 채점 표시 | 색상 기반 후보일 뿐. 인쇄와 겹치면 겹침 클래스도 표시한다. |
| 4 | 진한 펜 필기 | 인쇄 문자나 도형 위를 지날 수 있으므로 자동 제거 금지 영역을 계산한다. |
| 5 | 연필·옅은 필기 | 밝기·색상으로 자동 제거하지 않고 질감/획/주변 맥락과 같이 판단한다. |
| 6 | 인쇄와 필기 겹침·불확실 | 근거 없는 삭제/인페인팅을 금지하고 검수한다. |

부가 속성: 원본 해시, pixel 좌표, 질문/구성요소, 잉크 색 범위, 획 너비/방향, 라벨러/스키마 버전, 이전 판정. 픽셀 마스크는 클래스별로 저장한다. `print`, `annotation`, `uncertain`을 하나의 바이너리 마스크로 합치지 않는다. 라벨러 JSON v2는 실험실 기준 자료 포맷이며, Devin은 기존 스키마와 호환 마이그레이션을 설계한다.

## 4. 복원 처리 흐름

### Stage A — 안전한 수집과 입력 진단

1. 업로드 MIME/실제 signature/페이지 수/크기/압축 폭탄/손상/암호화 확인. 파일명과 사용자 입력은 데이터로만 취급한다.
2. 원본 바이트를 private tenant storage에 쓰고 SHA-256 및 source ID를 고정한다. 이후 어떤 처리도 원본 키를 덮어쓰지 않는다.
3. PDF 페이지별로 text chars, 글꼴, text span bbox, vector path, embedded image 수/해상도, 회전, crop/media box를 기록한다.
4. 페이지 역할 후보를 만든다: 표지/시험 안내/문항/이어짐/정답표/미확인. 페이지 순서 원본과 출력 페이지 순서를 별도 보존한다.
5. 텍스트 계층이 있는 PDF는 native text와 object geometry를 추출하면서도 시각 검수를 위해 PDF 렌더를 만든다. 스캔 PDF/JPG는 원본 렌더에서만 영상 인식 후보를 만든다.

### Stage B — 비파괴 영상 준비

- 페이지의 최초 raster 기준은 입력 해상도 또는 PDF 300dpi 렌더다. 200dpi 현 기준은 작은 수식·얇은 도형에 충분한지 표본 벤치마크한다. 400dpi 등 고해상도는 작은 문자 영역에 선택적으로 사용하고, 비용/latency를 기록한다.
- EXIF 회전, PDF 회전, crop, deskew, perspective/dewarp의 각 변환을 affine/homography matrix로 기록하고 역변환 가능하게 한다. 원본 좌표가 모든 bbox/crop의 공통 기준이다.
- Gray, local-contrast, 색상 채널, deskew 등 변형본은 검출/판독 후보용이다. 이진화본을 원문·복원·OCR의 단일 입력으로 사용하지 않는다.
- 그림자/접힘/번짐은 별도 artifact 후보다. 무조건 평탄화하면 연필과 얇은 인쇄선이 함께 사라질 수 있으므로 source와 variant를 나란히 비교한다.

### Stage C — 영역·레이어 후보 추출

- 우선 안전한 분할: 페이지 전체→열/영역→문항→발문/조건/보기/선택지/배점/도형/답안 공간. 상하좌우 읽기 순서를 열 단위로 유지한다.
- 인쇄/주석 분리는 선행 제거가 아니라 원본에 대한 병렬 semantic segmentation이다. OCR은 `original`과 `candidate_clean`을 모두 읽어 후보 차이를 보존한다.
- 색상(red/blue), grayscale intensity, stroke-width, morphology, connected components는 특성 입력이지 제거 규칙이 아니다. 밝기 고정값 `PRINT_MAX=55`/전역 chroma threshold는 고객 문서 전체의 물리적 print/ink 분리를 보장하지 않으므로 학년/스캔기/배경별 fixture에서 calibration한다.
- Candidate mask가 인쇄 픽셀/도형 구조와 겹치면 해당 component 전체를 `uncertain`으로 승격한다. mask에서 바로 원본을 흰색으로 덮지 않는다.

### Stage D — 인식과 대응 참조 대조

서로 독립된 candidate 경로:

1. native PDF text/vector extraction (텍스트 PDF일 때만).
2. 화면/문서 OCR: PaddleOCR PP-StructureV3 및 한국어 모델을 우선 benchmark. 제공되는 기능은 layout, table, formula, multi-column reading-order 및 structured Markdown/JSON 후보 생성이다. 이것이 잉크 제거, 원본 충실도, 정확한 수학적 의미를 증명하지 않는다. [공식 구현](https://github.com/PaddlePaddle/PaddleOCR)
3. 선택적 2차 파서: Docling 등 다른 implementation은 같은 benchmark에 비교 투입한다. 의존성을 중복 탑재하기 전 CER, math exact match, latency, RAM/VRAM, page 실패율을 평가한다. [Docling](https://github.com/docling-project/docling)
4. paired HWP/HWPX reference extraction: 같은 문항, 수식, 도형 asset 후보로 align한다. 참조마다 SHA/출처/날짜/품질 상태를 보존하고 reference candidate임을 표시한다.
5. human correction: 해당 source crop과 후보 overlay를 보고 field 단위로 결정한다. 이 기록은 source truth evidence다.

불일치를 다수결로 없애지 않는다. 각 candidate는 source crop bbox, recognition variant, confidence, engine/model version과 함께 유지한다. 번호, 배점, 부정어, 선택지 순서, 음수·소수·단위·degree·각/선분 기호·평행/수직 조건은 critical-token policy로 지정한다. Critical token mismatch가 한 개라도 남으면 final을 차단한다.

### Stage E — 수식과 도형의 구조화 복원

**수식**은 세 계층으로 저장한다: 원본 crop/pixels, parsed semantic/token representation, 출력용 HWP equation script/LaTeX. 숫자·부호·단위·괄호·근호·분수·지수·벡터/선분 overbar를 독립적으로 대조한다. print/handwriting 중첩으로 수식 형태가 숨으면 추측하지 않는다.

**도형**은 `FigureGraph`로 표현한다: vertex, segment/curve, angle, region, label, measure, equality tick, parallel/perpendicular mark, fill/hatch, graph axis/tick/plot, incidence/intersection constraints, source bbox. 복원은 검증된 vector/reference asset 또는 승인된 FigureGraph 렌더에서 생성한다. 단순 line art edge IoU만으로 일치 판정하지 않는다. 이름·연결성·교점·관계 기호·수치·선 종류의 semantic checks와 원본 overlay를 같이 사용한다.

정확한 대응 HWP 도형을 쓰더라도 해당 질문의 crop으로 local registration을 수행한다. 전체 페이지 복사, HWP 페이지 위에 사진처럼 붙이기, 보이지 않는 내용을 generative fill로 만들기는 금지한다.

### Stage F — 안전한 복원 variant

각 영역에 복원 정책을 둔다.

- `PRESERVE`: 확신이 낮거나 인쇄가 약한 부분은 모든 원본 픽셀을 보존한다.
- `REMOVE_CONFIDENT_ANNOTATION`: independent validation에서 class-specific false-removal 기준을 통과했고 print-overlap가 없을 때만 annotation mask를 후보로 적용한다.
- `RESTORE_FROM_REFERENCE`: question-level exact/near-exact reference/vector evidence를 local registration하고 허용 bbox 안에만 복원한다. transformation와 원본/참조 hash를 proof로 기록한다.
- `REVIEW_REQUIRED`: print-ink overlap, math, point/angle label, answer choice/score, fold/shadow 등은 사람 판단 전 원본을 가린 채 확정하지 않는다.

새 산출물은 `restored_candidate`로 남고 원본/마스크/overlay/변경 영역 diff를 항상 접근 가능하게 한다. 허용 mask 밖 changed pixel 수 0, 변경 안쪽도 원본 diff를 검수할 수 있어야 한다.

### Stage G — 수학 논리, 미주, 한글 렌더링

1. Verified Canonical Document JSON에서만 출력한다. RESTORE와 EDIT는 다른 revision lineage다.
2. 정답 키/독립 solver/문항 조건을 분리해 대조한다. 학생 답, HWP 정답 또는 다수 OCR을 정답 oracle로 간주하지 않는다.
3. 모든 채점 단위에 실제 한글 미주 anchor와 정답·학년 범위 풀이가 있는지 manifest count를 먼저 만든 후 출력에서 역검증한다.
4. 실제 수식 객체의 11pt, 숫자 it, 단위 roman, 도형 editable object, 2열 문항 layout/행 높이, 서술 답안 공간을 검사한다.
5. HWPX/HWP/PDF별 생성 bytes를 새로 hash하고 실제 target renderer/한컴 worker로 열기→재렌더→문서 구조 재추출→Canonical과 semantic diff한다. 중간 draft의 proof를 final 파일 proof로 재사용하지 않는다.
6. 라이선스 후보: 상용 HWP/HWPX 안정성이 우선이면 한컴 SDK 구매 조건과 capability를 benchmark. `python-hwpx`는 오픈소스 HWPX 실험 후보이며 현 repo가 Alpha로 표시하고 HWP v5 직접 처리를 지원하지 않으므로 production decision 전 실물 한글 호환을 검증한다. Codex `hwpx-plugins`는 에이전트 문서작성 워크플로이지 OCR/복원 엔진이 아니다.

## 5. 검수 UI의 역할

교사가 매 문항을 처음부터 전수 재검수하지 않게 하되, 모호한 부분은 숨기지 않는다.

- 자동 검토 페이지: 원본/clean candidate 나란히 보기, opacity toggle, difference, source bbox, mask color legend, OCR candidate/수식 token diff, paired reference preview.
- 예외 단위: question/field/figure/object가 선택되고 원본 위치로 확대·스크롤한다. “인쇄/필기/겹침/잘못된 reference/판별 불가” 결정을 기록한다.
- 검토 action: 값 채택/대안 선택/직접 수정/무시하지 않고 unreadable로 남김. 각 action은 reviewer, time, before/after, evidence IDs, revision hash를 남긴다.
- 애매한 항목 수·critical 여부·남은 이유·예상 영향·미리보기 전/후를 보여준다. 모든 예외 해결 후 재실행 범위를 변경 영향 graph로 좁힌다.
- 한 교사가 자기 문서의 일상 사용을 위해 수학 문제 전체를 손으로 다시 검수하는 흐름이 되면 제품 설계 실패로 기록한다. 독립적인 gold 검수자는 기준 데이터 구축/출시 평가용이지 모든 고객의 기본 작업자가 아니다.

## 6. Gate, benchmark와 성공 정의

### 6.1 문서 상태

```text
UPLOADED → SOURCE_ANALYZED → CANDIDATES_READY → REVIEW_REQUIRED (필요시)
→ CANONICAL_VERIFIED → DRAFT_RENDERED → FORMAT_PROVED → VERIFIED_FINAL
```

실패/모호성은 `NEEDS_REVIEW`, 지원하지 않는 형식/관계는 `BLOCKED`, 기술 오류는 `FAILED`다. 세 상태를 `COMPLETED`/`VERIFIED_FINAL`에 합치지 않는다.

### 6.2 Final exactness gate

`VERIFIED_FINAL` 조건:

- 기대 범위 manifest와 실제 문항/선지/채점 단위/수식/도형/답안 공간/미주 객체 간 coverage가 완전하다. ATU가 없다는 사실을 누락 0으로 해석하지 않는다.
- 모든 critical text/math/number/condition/score/choice-order/answer/formula/figure relation이 검증 상태이고 `CONFLICT=0`, `UNREADABLE=0`, `MISSING=0`이다.
- 모든 annotation overlap review 완료, 자동 지움이 승인된 mask만 사용, mask 밖 변경 0.
- 정답/풀이의 독립 검증, 학년 scope 확인, 정답 미주 anchor coverage 100%.
- 출력된 특정 artifact byte hash에 대해 실제 한글 reopen/render와 reverse structural/content compare가 통과한다.
- brand/style export는 content revision의 문항/수식/도형/미주 의미를 바꾸지 않고 허용 layer/mask 밖 변화가 없다.

### 6.3 Near-100 복원 목표와 이중 측정

목표는 최종본 무오류뿐 아니라 지원 범위 문항의 거의 전부를 사람 개입 없이 정확히 처리하는 것이다. 두 축을 같이 측정하고 하나의 평균 점수로 섞지 않는다.

1. **자동 문항 exactness / Precision-at-coverage:** 지원 범위 holdout에서 사람 개입 없이 자동 확정한 문항 중 발문·조건·번호·보기 순서/내용·배점·수식 기호와 숫자·도형 semantic graph가 source와 모두 같은 비율. 설계 목표는 문항 묶음 단위 **99.5% 이상 exact match**다. CER/토큰 평균이나 쉬운 페이지 점수로 critical 기호 오류를 숨기지 않는다.
2. **자동 전체 시험 완료율:** 사전 고정한 지원 범위 holdout 시험 중 어떤 문항도 사람 검수 없이 전부 exact하게 통과한 시험의 비율. 제품 목표는 해당 holdout에서 **99% 이상**이다. abstention으로 지표를 인위적으로 높이지 않도록 benchmark 전에 지원 범위/입력 품질 분포/문서 분모를 동결하고, review/block 유입률·원인·교사 소요 시간도 같이 보고한다. 지원 범위 안의 실패 문서를 분모에서 제거하지 않는다.
3. **VERIFIED_FINAL 정확성:** 최종본 집합에서 source-critical 오탈자, 인쇄 손실, 도형 관계, 답/배점 불일치의 관측치는 **0**이어야 한다. 증거가 없는 결과는 `NEEDS_REVIEW/BLOCKED`로 세고 완료된 최종본처럼 숨기지 않는다.

`99.5%`는 현재 코퍼스에서 입증된 성능 수치가 아니라 near-100 제품 방향을 구체화한 **목표 제안값**이다. RESTORE-00에서 승인된 gold/holdout의 규모와 대표성을 확인한 뒤 최종 책임자가 수치를 고정한다. 목표보다 낮으면 부족분과 원인·지원 범위·검수 비용을 공개하고, 사후에 목표를 낮춰 합격시키지 않는다. paired HWP 간 일치만으로는 이 성능을 계산할 수 없다.

평균 CER/IoU/F1 또는 여러 쉬운 문항의 높은 점수는 이 final gate를 대체하지 않는다. 99.5% 자동 exactness 목표는 지원 범위 holdout에서 machine-only 자동 판정의 정확도/coverage 목표이며, final 파일에 0.5% 오류를 허용한다는 뜻이 아니다.

### 6.4 보고할 지표

- question/choice/point/answer extraction exact precision & recall; missing, duplicate, reorder 분리.
- math exact match: number/sign/decimal/fraction/exponent/root/degree/unit/relation token별, 수식 단위 whole-expression exact.
- figure graph: vertex/edge/label/measure/tick/parallel/right-angle/hatch exact; topology mismatch count; human IoU는 부가 지표.
- pixel layer class별 precision/recall와 overlap strata별 false-removal/false-retention; 인쇄 텍스트·도형 보존을 개별 보고.
- final 자동 통과 파일의 critical defect count = 0; review abstention/교사 확인 시간/원인별 빈도도 같이 보고.
- 운영: pages/doc, p50/p95 latency, OCR/HWP worker minutes, provider cost, retry/error/reject, tenant fairness.

### 6.5 Dataset split

기존 `docs/handoff/08_CORPUS_AND_CONTINUOUS_TESTING.md`를 준수한다. 개발·회귀 표본과 봉인된 final holdout을 학교/연도/시험/문항 family 단위로 분리한다. 같은 문제의 참조 HWP, 학생 여러 답안, crop/회전은 한 family다. 초기에 계남고 paired corpus는 development corpus, 심원중은 negative regression/control corpus로 사용 가능하나, 승인·독립 검산·권리·개인정보 검토 전에는 release gold가 아니다. 인계 명세의 제안(독립 학교/시험 30종 및 채점 단위 1000개 등)은 `RELEASE_CRITERION_PROPOSAL`로 유지하고 책임자가 실제 F2/F3 확보 후 고정한다.

## 7. 기존 Devin 코드와 구현 우선순위

읽기 전용으로 확인한 기준 코드 경로(Devin repository를 이 문서 작성 중 수정하지 않음):

| 파일/모듈 | 현재 확인 | 작업 필요 |
|---|---|---|
| `backend/core/examdna/preprocessing.py` | EXIF/PDF raster + gray/autocontrast/fixed binarization, PDF 200dpi. 원본 bytes 보존 intent 있음. | per-page text/vector inventory, PDF page-role evidence, resolution benchmark, invertible full transform chain, input failures as explicit blockers; 300dpi baseline candidate is a test, not assumed truth. |
| `backend/core/examdna/student_trace/separator.py` | fixed intensity/chroma/component heuristics, print-dark overlap guard, trace mask를 grayscale 원본에 whiten하여 `trace_removed` 생성. | 칼라/연필/검정 필기 세그멘테이션 및 pixel-verified gold 부족. mask는 candidate-only이며 `clean` 승인 전 제거 금지. 인쇄 gray/thin lines 보호/uncertainty 보강. |
| `backend/core/examdna/print_layer/engine.py` | `clean_uri=trace_removed`를 고름. hidden print 복원 엔진은 아직 사실상 없음. | change mask/restore evidence + reference-local registration. 복원 출처 없는 hole은 preserve/review. |
| `backend/core/examdna/recognition/segmenter.py` | provider `extract_page` bbox 기반, page 1/2의 중앙 x로 양열 분리 후 box bottom을 다음 상단에 늘림. | 원본 읽기 순서/중앙 gutter/교차하는 열/문항 parent/answer key role을 테스트; padding heuristic가 문항끼리 합치거나 조건 잘라먹는 회귀를 차단. |
| `backend/core/examdna/recognition/runner.py` | 인식 input은 `clean_uri` 우선. Candidate/ATU 구조와 fallback retry 3회 있음. | original/variants OCR 병렬 후보 및 source bbox/variant provenance. 무제한 반복/불필요한 비용 금지. |
| `backend/core/examdna/source_truth/consensus.py` | 2개 이상 candidate 합치거나 single candidate confidence ≥0.9면 `AUTO_VERIFIED`. | `0.9` 단일 공급자 확정은 인쇄 원문 proof가 아니다. field/class별 독립 evidence+교정된 threshold/abstention을 설계하고, proof 없는 critical 항목은 `UNVERIFIED` 유지. |
| `backend/core/examdna/zero_typo_gate/gate.py` + `backend/document/verification` | 문서 게이트가 aggregate 검증 모델을 평가함. | expected manifest와 actual coverage 비교, artifact byte-bound render proof, independent ground truth requirement 강화. `ATU count==0`로 통과하지 않도록. |
| `backend/providers/{ocr,vision,math_ocr}` | provider abstraction/stub가 존재. | PaddleOCR를 optional/local or server adapter로 구현; import/runtime/model weights lazy load; feature flags; mock offline tests; provider result typed/validated. Gemini는 기본 경로에 추가 금지. |

현재 코드가 “stub”거나 테스트가 있다고 제품 기능이 완성된 것은 아니다. 각 WP에서 기준 commit/current HEAD, 미커밋 파일 소유자·diff·테스트를 먼저 확인하고, 충돌 파일/Devin의 in-progress 작업을 덮어쓰지 않는다.

## 8. Devin 구현 계획 (선행 조건과 DoD 포함)

기존 `WP00–WP11`, `BACKLOG.csv`, `TRACEABILITY.csv`, `04_ACCEPTANCE_TEST_PLAN.md`를 변경 없이 기준 삼고 아래를 복원 기술 WP로 추가한다. PR 한 개는 원인 1개/책임 module 1~3개로 작게 만든다.

### RESTORE-00 — code/fixture baseline & failure reproduction

- Start: latest HEAD, branch, all user/Devin uncommitted changes, fixture hashes, existing tests, CPU/GPU/runtime availability 기록.
- 고정 사례: Gyenam image-only PDF 7 pages; Seum/Jinsu paired HWP; Simwon five JPG + reference HWP with Q12 score mismatch; synthetic red-circle/black-tick/gray-pencil/line-crossing/shadow/dark-print/thin-line fixtures.
- Run existing pipeline on copies and export page contactsheets, masks, overlays, question crops, provider outputs. Source hash before/after equal.
- Regression manifest captures: page roles, 19+essay layout, 213 paired HWP equations (reference fact not source proof), Q12 score discrepancy, Q11/essay printed geometry overlap, all 7 source text-layer chars zero.
- No auto export and no blanket HWP COM workflow for this WP.

### RESTORE-01 — provenance, source anchors and PDF inventory

- Update `preprocessing.py` + `document.models` only after tests lock old behavior.
- Model `RawSource`, `PdfPageInventory`, `TransformChain`, `SourceAnchor`, derived variant hashes. Keep raw immutable.
- Native PDF path: text spans, font/resource, vector/path count and image geometry. Scan path: render, report DPI/page matrix. Add PDF page rotation/cropbox tests.
- Do not convert source into DOCX/HWP. Mark `image_only` and `text_layer_sparse` explicitly.
- DoD: all crops/regions map back to source pixel coordinates; source hash unchanged; unsupported/failed page render blocks or reports needs review, never silently skips.

### RESTORE-02 — inference adapter, but output remains candidates

- Provider adapter in `backend/providers/ocr` and `math_ocr`, with optional-dependency boundary and mock/replay implementations. Start with PaddleOCR KOR/general + formula/layout model benchmark. No model weights downloaded on unit-test path and no customer PII sent remotely by default.
- Candidate stores provider/model/config/input variant/coordinates/confidence/raw references/version. Preserve original image recognition results alongside candidate-clean results.
- Evaluate a second parser only if its accuracy-versus-cost is meaningfully independent; compare with Docling as a benchmark candidate, not mandatory runtime dependency.
- DoD: all offline tests run without SDK/network; cost/timeout/model-unavailable failure explicit; no provider response can directly set final value.

### RESTORE-03 — question/column/page segmentation and evidence UI payload

- Replace simplistic two-half ordering/box extension only after labeled boundaries and regression tests. Page role and column assignments can be `UNVERIFIED`/conflict.
- Detect problem/choices/score/figure/answer-space boxes; retain original normalized + pixel bbox, reading order, source anchors. Build human review package API.
- DoD on existing fixture: expected 7 page roles and 19 question boxes/page distribution; no answer key treated as problem page; all choice/score/essay subregions fit source crops; unlabeled/duplicate/missing remain visible.

### RESTORE-04 — layer mask scoring, confidence calibration and safe restoration

- Extend v2 six-class evidence into typed per-pixel masks and overlap graph. Replace one-value `trace_removed` semantics with `trace_candidate`; restoration candidate is separate artifact.
- Train/calibrate only on rights-cleared, independently labeled F2 dev data. Holdout is sealed. Separate red/black/blue/gray color, intensity, stroke shape, neighborhood, print vector/text likelihood. Add print overlap protection and source/reference constraints.
- Remove only on calibrated non-overlap cases; hidden-print recovery only by validated paired reference or human-approved structured vector. No generated/inpainted math symbols.
- DoD: per-class/overlap confusion table; print-retention and mark-removal metrics separate; no print-line loss in Q11/essay stress cases; unknown overlap always REVIEW_REQUIRED. No system-wide precision claim on one exam.

### RESTORE-05 — source consensus and atomic math/text verification

- Update recognition/ATU and `source_truth/consensus.py`: distinct candidates are not distinct proof merely because provider name differs. Confidence calibrates automation but never proves ground truth alone.
- Implement critical token classes: numeral/sign/decimal/unit/degree, negation, comparison, geometry mark, choice ID/order, points. Normalization is per field and reversible; preserve raw candidate strings/scripts.
- Pair-reference alignment is evidence with reference reliability state. Encode disagreements as `CONFLICT`, never select majority silently. Human decision attaches bbox and revision.
- DoD: q1–q19 choice/math audit (Q8/Q12 combo handling), score/key coverage, essay hierarchy, source-specific review fixtures. Test variants include visually similar 1/7, 3/8, minus/dash, angle/segment overbar, `∥/⊥`, dot, decimal, choice marker.

### RESTORE-06 — FigureGraph and semantic diagram QA

- Add typed figure graph (not prose-only descriptor) for vertices, edges, curves, labels, lengths/angles, equality/parallel/right-angle marks, hatch/fill, intersections and relation constraints.
- Generate preview from vector/object/reference; store transformation + references. Underlying raster remains source evidence.
- DoD: required object inventory vs output inventory, graph topology, labels, measures, marked relations. Human crop overlay. IoU/edge-F1 may be diagnostic only; automatic pass cannot use those metrics alone.

### RESTORE-07 — proof-bearing export gate and quality reports

- `expected manifest` generated before output; reconciliation of expected vs actual ATUs, equations, figures, answer-space, notes, pages; detect missing/duplicate (not just observed objects).
- Source/Canonical/document/artifact hashes and version chain. Quality report per class/page/question; record machine/human evidence separately.
- Final is blocked by any critical UNVERIFIED/CONFLICT/UNREADABLE/MISSING, annotation-uncertain, out-of-mask pixel difference, HWP object/structure mismatch, or incomplete proof. Preserve reason codes.
- DoD: mutation test proving stale artifact/revision cannot pass; `ATU=0` but expected items nonzero fails; fake scalar confidence cannot pass.

### RESTORE-08 — production document generation and round-trip

- Use approved HWP/HWPX renderer/SDK behind adapter. First compare supported capability/cost/licensing and fixed-reference layout; do not choose based only on whether a blank HWPX opens.
- Render and reopen actual HWPX/HWP in production-equivalent HWP worker; inspect actual equation objects, point/diagram geometry, note references, 2-column aligned row heights, page breaks, 11pt/it/roman. Reverse parse the produced file and compare to Canonical plus expected object counts.
- DoD: each fixture demonstrates open→render→extract→proof for exact final output hash. Any unsupported object routes to explicit error/review.

### RESTORE-09 — blind eval / pilot / release

- Do not tune on final holdout. After opening a holdout error and changing code, recategorize it as regression and reserve a new holdout.
- Release report separates automatic scope, review scope, rejected inputs, critical final defects, review rate, cost/latency, tenant isolation, upload/storage/delete/restore, HWP workers.
- Follow existing release corpus target only after source rights/privacy and independent review. One Gyenam vertical slice is Alpha evidence, never universal launch proof.

## 9. Devin에게 그대로 보낼 시작 지시

```text
ExamDNA의 복원 기술을 제품 수준으로 구현해 주세요. 먼저 저장소의 최신 HEAD, 기준 감사 commit, 전체 working tree와 기존 WP 명세를 확인하고 RESTORE-00부터 진행하세요. 기존 사용자/Devin 미커밋 변경, source fixtures, HWP 보안/변환 동작을 보존하고, 기존 변경을 덮어쓰지 마세요.

설계 원칙: 원본 PDF/JPG는 불변 증거다. image-only PDF를 OCR로 Word/HWP에 먼저 변환해 그 변환물을 source로 삼지 않는다. PDF native text/vector 추출과 원본 이미지 OCR 후보는 병렬 증거로 보존한다. OCR/비전/LLM은 Candidate일 뿐이며 source bbox, source/variant hash, model/config/version을 남긴다. 개별 provider confidence 0.9나 같은 cache를 두 번 읽었다는 사실만으로 ATU를 확정하지 않는다. 원문/보기/점수/부호/도형/서술 공간을 임의 교정·삭제·생성하지 말고, 겹치거나 증거가 불충분하면 NEEDS_REVIEW로 중단한다.

필기 제거는 source와 mask가 별도인 candidate operation이어야 합니다. 인쇄 픽셀/도형과 겹치는 부분을 추측으로 지우거나 generative inpaint하지 않습니다. 대응 HWP/HWPX가 있으면 파일 hash/신뢰 상태를 기록하고 해당 문항 안에서만 local alignment를 해 사용합니다. PDF 전체 페이지 copy, color-only erase, OCR majority vote 금지. 도형은 vertex/edge/label/measure/relation/tick 등을 구조로 보존합니다. 최종 HWP/HWPX는 VERIFIED Canonical JSON에서만 만들고 실제 한글에서 reopen/render 후 같은 output hash의 구조·텍스트·수식·도형·미주·레이아웃 proof를 저장합니다.

먼저 이 설계 파일의 RESTORE-00~09를 작고 검토 가능한 PR로 수행하세요. 매 WP마다 재현 절차→회귀 테스트→최소 구현→전체 관련 테스트→실물 output overlay/증거→독립 검토를 기록하세요. 테스트/skip/assertion/gate를 약화해 초록불을 만들지 마세요. mock 통과, 한 샘플의 성공, OCR confidence, 구조 parser open 성공을 제품 정확도나 출시 승인으로 부르지 마세요. Devin 작업을 실행하지 않은 상태에서 외부 계정·비용·고객자료 전송·배포·PR을 임의 수행하지 마세요.

첫 작업 RESTORE-00 산출물: current HEAD/dirty files 목록, existing tests/status, source hash check, Gyenam/Simwon failure reproduction report, page/question/score/formula/reference inventory, baseline screenshot/contact sheet, 정확히 확인된 defects와 다음 WP blockers. 그 결과를 먼저 제출하고 이어서 RESTORE-01을 시작하세요.

개발 완료 주장은 다음이 모두 있을 때만 허용됩니다: independent authorized gold, unseen/holdout assessment with leakage control, critical final defect=0, unresolved critical=0, no out-of-mask print change, all expected semantic objects present, exact final byte-hash-bound HWP reopen/render/reverse-proof, tenant isolation, repeatable regression, cost/latency and unresolved limitations report. 어떤 항목이 빠지면 status는 PARTIAL/NOT_RUN/NEEDS_REVIEW이며 작업을 계속하세요.
```

## 10. 문서와 라이선스 참고

- 기존 Devin 제품/API/UX 계약은 `D:\플랫폼\exam_ai_spec\project\docs\handoff\01–09`와 `MASTER_SPEC.md`가 source다. 본 문서는 restoration implementation supplement이며 이 계약을 재정의하지 않는다.
- PaddleOCR PP-StructureV3: https://github.com/PaddlePaddle/PaddleOCR (코드 라이선스/개별 model weights license를 각각 확인). 한국어 model을 명시해 평가한다.
- Docling: https://github.com/docling-project/docling (OCR/layout parse 비교 후보, 다른 recognition layer와 라이선스 포함 평가 후 선택).
- python-hwpx/HWPX agent plugin: https://github.com/airmang/python-hwpx · https://github.com/airmang/hwpx-plugins (repo는 Alpha 및 HWP v5 직접 지원 밖이라고 명시; product dependency로 채택 전에 frozen-version/Hancom render evaluation과 라이선스 검토).
- Hancom HWP SDK: https://download.hancom.com/product/sdk/hwpSdk (상용 계약·운영 배포 범위·수식/도형/미주 및 서버/worker architecture 지원을 vendor와 확정).

외부 후보의 제품 로드맵/README claim은 ExamAI의 정확도 증거가 아니다. 사용 모델/데이터 license, 개인정보 전송, redaction, storage, deployment region은 운영자 검토와 비용 승인 전 production 기본값으로 켜지 않는다.
