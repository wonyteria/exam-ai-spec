# ARCHITECTURE

## 1. Source of Truth
```text
Raw Source
→ ExamDNA
→ Verified Document JSON
→ Renderer
   ├ Web
   ├ HWPX
   ├ HWP
   └ PDF
```
HWP 자체를 Source of Truth로 사용하지 않는다.

## 2. 권장 구조
```text
/core/examdna/
  student-trace/
  print-layer/
  source-truth/
  recognition/
  exam-diff/
  layout/
  verification/
  zero-typo-gate/
/guides/mathematics/
/document/
/providers/{ocr,vision,math-ocr,llm,solver}/
/renderers/{web,hwpx,hwp,pdf}/
/jobs/
/qa/
/tests/golden/
```

## 3. Document 예시
```json
{
  "id":"doc_xxx",
  "metadata":{"school":"","year":2025,"grade":"middle_2","semester":2,"exam_type":"midterm","subject":"mathematics"},
  "pages":[],
  "questions":[],
  "brand_id":null,
  "template_id":null,
  "verification":{},
  "version":1
}
```

## 4. Question 예시
```json
{
  "id":"q_006","number":6,"type":"multiple_choice","points":4,
  "body":[],"choices":[],"equations":[],"figures":[],
  "answer":null,"solution":null,
  "curriculum":{"grade":"middle_2","unit":"","concepts":[]},
  "source":{"page":1},
  "verification":{"status":"UNVERIFIED"},
  "logic_validation":{}
}
```

## 5. Provider Interface
```ts
interface OCRProvider {}
interface VisionProvider {}
interface MathOCRProvider {}
interface ReasoningProvider {}
interface MathSolverProvider {}
```
Provider 결과는 Candidate일 뿐이며 바로 문서에 확정하지 않는다.

## 6. Verification State
`UNVERIFIED / AUTO_VERIFIED / HUMAN_VERIFIED / CONFLICT / UNREADABLE`

## 7. Job State
`UPLOADED / PREPROCESSING / SEPARATING_TRACES / RESTORING_PRINT / RECOGNIZING / VERIFYING_SOURCE / VERIFYING_LOGIC / SOLVING / RENDERING / VERIFYING_EXPORT / COMPLETED / NEEDS_REVIEW / FAILED`

## 8. HWP
```text
Verified Document JSON
→ HWPX Renderer
→ HWPX
→ Windows HWP Worker
→ HWP
→ PDF/Image Render
→ Reverse Verification
```

## 9. 콘텐츠/스타일 분리
`CONTENT LAYER`와 `STYLE LAYER`를 분리한다. 브랜드 변경이 문제 내용을 바꾸면 P0 오류.
