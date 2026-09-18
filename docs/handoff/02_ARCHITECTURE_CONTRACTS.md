# 02. 아키텍처·데이터·실행 계약

작성 기준: 2026-09-19, 저장소 `D:\플랫폼\exam_ai_spec\project`, main `0c1fb5dc8223d52889ca676bed13ad2e7d93fa4a`. 아래 **목표 구조는 신규 제안**이며 현재 구현 완료를 뜻하지 않는다. 사용자가 확정한 운영 대상은 **여러 학원이 사용하는 서비스**다. 기존 Next.js/FastAPI를 유지하고 데이터 무결성과 tenant 경계부터 구축한다. 실제 Codex 신규 원본 추론·운영 배포·유료 API 연결은 이번 문서 작업에서 실행하지 않았다.

관련 문서: [제품 요구사항](01_PRODUCT_REQUIREMENTS.md), [페이지 UX](03_PAGE_UX_SPEC.md), [인수 테스트](04_ACCEPTANCE_TEST_PLAN.md), [개발 순서](05_DELIVERY_PLAN.md). 정량값은 별도 명시가 없으면 측정 결과가 아닌 초기 운영 제안이다. 계약의 INV-*는 테스트에서 참조할 불변조건 ID다.

요구사항 연결: §2–3 REQ-01/21/24/28, §4 REQ-03–10/19/25, §5–6 REQ-11–14/16, §7 REQ-11/17/19, §8 REQ-08/09/15/18, §9 REQ-20/26, §10 REQ-21/27, §11 REQ-02/12–14/17/20/22/23, §12 REQ-01/03/24–28. 실제 인수 테스트 ID의 기준은 04 문서다.

## 1. 현재 구현에서 출발할 지점

| 확인된 현재 구조·결함 | 소스 근거(저장소 상대 경로:행) | 목표 변화 |
|---|---|---|
| 원본·문항·ATU·정답·풀이를 Document가 보유하지만 tenant·불변 revision·artifact proof 키가 없음 | `backend/document/models.py:187`, `:54`, `:138` | tenant 소유권 및 immutable revision/proof 추가 |
| 검토 확정이 ATU.value만 수정하고 실제 본문에는 반영되지 않음 | `backend/app/api/documents.py:120` | 단일 mutation 서비스로 canonical field와 provenance 동시 갱신 |
| 편집 라우트가 Gemini에 결합됨 | `backend/app/api/documents.py:138`, `backend/jobs/runner.py:26` | 명시적 provider profile과 구조화 제안/승인 분리 |
| JSON 파일을 직접 덮어쓰며 process-local job cache 사용 | `backend/jobs/store.py:21`, `:33`, `:79` | DB 트랜잭션·CAS·durable queue |
| 작업이 문서를 덮어쓰고 마지막 검증 문자열로 완료 판정 | `backend/jobs/runner.py:61` | lease를 가진 단계 실행과 검증된 snapshot 기반 commit |
| export에 상태 검사 없고 이전 HWPX가 있으면 재사용 | `backend/app/api/documents.py:168`, `:181` | 정확한 revision/hash의 artifact만 생성·승격 |
| proof 미실행이 0 mismatch로 취급됨 | `backend/core/examdna/zero_typo_gate/gate.py:9`, `backend/qa/hwp_proof.py:16` | 미실행/불가/실패/통과 구분, 형식별 증거 필수 |
| SSE에 durable event cursor가 없음 | `backend/app/api/jobs.py:27` | tenant 인가 + Last-Event-ID 기반 재개 |

세부 재현 근거는 `evidence/`에 포함된 기존 감사 및 실물 보고서를 우선한다. 과거 캐시의 `VERIFIED_FINAL`은 신뢰 가능한 신규 검증으로 이관하지 않는다.

## 2. 배포와 실행 경계

### 2.1 공통 SaaS 구조

```text
학원 사용자 브라우저
  → Next.js UI / 동일 출처의 인증된 API
  → FastAPI: tenant 인가 / canonical mutation / 작업·artifact 계약
  → PostgreSQL: revision·issue·proof·job·event·권한·감사
  → private object storage: 원본·변환자산·불변 산출물
  → DB durable queue / 공정 scheduler
       ├─ 추출·독립 검증 executor (선택한 inference profile)
       ├─ 결정적 HWPX·레이아웃·PDF executor
       └─ 격리 Windows 한글 executor (HWP·실 렌더 검증)
```

요청 프로세스가 백그라운드 daemon thread를 작업의 유일한 소유자로 삼지 않는다. 각 executor는 DB 작업 lease와 해당 tenant의 최소한의 blob 접근 권한만 받는다. 모델은 DB·스토리지·OS 명령을 직접 변경하지 않고 typed candidate/proposal만 반환한다.

### 2.2 확정된 중앙 실행과 개발용 구독 분리

| 프로필 | inference·한글 실행 위치 | 인증/비용 소유자 | 결정 상태 |
|---|---|---|---|
| CENTRAL_MANAGED | 운영자가 관리하는 inference executor와 Windows 한글 pool | 운영 조직의 별도 승인된 공급자 계약·자격증명 | **사용자 확정 V1**. 학원은 웹만 사용. 운영 공급자/계정·비용은 WP00에서 확정 |
| DEV_QA_LOCAL | 소유자 PC, 승인된 자료만 로컬 CLI 추론 | 소유자 본인의 Codex 구독 | 개발·품질 비교용. 다학원 production capacity로 간주 금지 |

개인 Codex `auth.json`을 Devin·중앙 서버·다른 학원에 복사하거나 하나의 개인 구독을 tenant 공용 인증으로 사용하는 구현은 채택하지 않는다. 이 문장은 제품의 자격증명 분리 결정이며 서비스 약관에 대한 법률 판단이 아니다. Gemini는 기본·fallback 모두 비활성화한다. 중앙형의 운영 후보는 OpenAI Responses API이며 계정/model access·현재 가격·비용 정책·실제 과금 승인은 WP00에서 확정한다. 계정 준비 전에는 mock/cache-only 통합까지 진행하고 production inference는 `CONFIGURATION_REQUIRED`로 둔다. 구독 사용권을 API 크레딧/자격증명으로 간주하지 않는다.

프로필 공통 interface: `capabilities()`, `submit(TaskEnvelope)`, `cancel(attempt_id)`, `health()`. TaskEnvelope에는 `tenant_id, job_id, attempt_id, lease_token, input_digest, stage, schema_version, artifact_refs, expires_at, authorized_provider_profile_id`를 넣는다. 실행 프로필은 job 시작 시 snapshot으로 고정한다. 장애 시 다른 profile/provider로 몰래 넘기지 않는다.

검토 후 제외한 대안: 학원마다 Codex CLI+Windows connector를 설치하는 방식. 학원 PC 가동·설치·구독 한도·한글 환경 관리 부담이 커 사용자가 선택한 웹 전용 중앙 서비스와 맞지 않으므로 V1에서 구현하지 않는다. 학원 화면에 CLI 로그인·한글 설치·API 키 입력을 요구하지 않는다. 중앙 worker 등록은 운영자만 가능하고 service identity는 user session과 분리한다.

## 3. tenant·권한·접근 제어

`Tenant` = 학원, `User` = 로그인 주체, `Membership(tenant_id,user_id,role,state)` = 권한. 한 사람이 여러 학원 소속이면 화면에서 선택하되 **클라이언트 tenant_id만 믿지 않고** 서버가 매 요청마다 활성 membership과 object의 tenant를 검증한다. UUID의 추측 난이도는 보안 경계가 아니다.

| 작업 | owner | admin | teacher | reviewer |
|---|---:|---:|---:|---:|
| 학원 가입·멤버·보관 정책·quota 신청 | O | 멤버/템플릿만 | — | — |
| 업로드·복원·조건 편집 | O | O | EDIT 문서 | — |
| 출력 artifact 생성·final 출고 | EXPORT 문서 | EXPORT 문서 | EXPORT 문서 | — |
| 원본 대조·풀이 검토·검토 issue 확정 | O | O | 접근권 문서 | 배정 문서 |
| 문서·검토·이력 읽기 | O | O | 접근권 문서 | 배정 문서 |
| 배정/접근권 문서의 미리보기·proof·이력 읽기 | O | O | 접근권 문서 | 배정 문서 |
| 이미 출고된 final artifact 다운로드 | EXPORT 문서 | EXPORT 문서 | EXPORT 문서 | — |
| 초안 artifact 다운로드 | EXPORT 문서 | EXPORT 문서 | EXPORT 문서 | — |
| 문서 삭제/복구·감사 내보내기 | O | O | — | — |
| 문서 보관(archive)/보관 해제(unarchive) | O | O | — | — |
| 학원 삭제·소유자 이전 | O | — | — | — |

`DocumentAccess(tenant_id,document_id,user_id,permissions={READ,REVIEW,EDIT,EXPORT},granted_by,grant_policy_version?,expires_at?)`를 추가한다. permissions는 집합이며 **EDIT는 EXPORT를 포함하지 않는다**. owner/admin은 학원 전체 관리권, teacher는 작성 문서 또는 명시적으로 공유받은 문서만 접근한다. 출력 artifact 생성·초안/final artifact 다운로드·final 출고에는 owner/admin/teacher 모두 문서의 명시적 EXPORT grant와 접근권이 필요하다. 초기 tenant 정책에 따라 owner/admin과 문서 작성 teacher에게 EXPORT를 부여할 수 있지만 실제 grant와 정책 버전을 기록하고, 공유 문서의 EDIT만 받았다고 EXPORT를 자동 부여하지 않는다. 별도의 두 번째 사람 출고 승인을 의무화하는 설계는 아니다.

reviewer는 배정 문서의 원문 복원·풀이 검토와 문서/미리보기/proof/이력 읽기만 가능하다. reviewer에게 EXPORT grant를 발급할 수 없고, 작성 의도를 바꾸는 EDIT·산출물 생성·초안/final artifact 다운로드·final 출고는 모두 금지한다. 원문 판독 정정은 RESTORE typed resolve로만 허용하고 권한이 필요한 조건 변경으로 전환하면 teacher에게 넘긴다. 검토 확정 후 시스템이 내부 proof 검증용 artifact를 만드는 것은 제한된 service identity의 작업이며 reviewer가 임의 artifact 생성 API를 호출하는 권한과 다르다. 공유 해제/탈퇴는 SSE·다운로드·진행 중 UI에도 재검증한다. final 다운로드는 EXPORT가 있어도 해당 artifact proof와 revision 조건을 통과해야 한다. 플랫폼 운영자 `platformoperator`는 health/quota/provider/worker 관리용 별도 역할이고 학원 원본 읽기·수정 권한을 자동으로 얻지 않는다.

**INV-01 tenant 격리:** documents/assets/revisions/fields/issues/candidates/proposals/proofs/jobs/events/artifacts/templates/exports/audit 전부 tenant_id가 있다. parent 참조는 `(tenant_id, id)` 복합 FK 또는 동등한 DB 강제 장치로 tenant를 넘지 못한다. 목록 필터만으로 대체하지 않는다. API 인가 후 transaction-local tenant context를 주입하고 PostgreSQL RLS를 추가 방어로 사용한다. 운영 서비스 role은 RLS bypass 권한을 갖지 않는다. 소유하지 않은 ID는 존재 유출을 줄이기 위해 404, 같은 tenant에서 role 부족은 403이다.

**INV-02 읽기도 보호:** SSE·crop·thumbnail·원본·미리보기·download·실패 로그·cache 조회에도 같은 인가가 필요하다. 서버 내부 blob URI를 프런트엔드에 내리지 않는다. signed URL이 필요하면 단일 artifact·짧은 TTL(제안 60초)·private 응답이며 이미 발급한 URL이 즉시 철회되지 않을 수 있음을 설계에 반영한다. 민감한 원본은 초기 V1에 API proxy download를 우선한다. 공개 bucket·디렉터리 listing 금지.

## 4. canonical 문서 스키마

Pydantic의 discriminated union으로 schema를 정의하고 생성된 JSON Schema를 frontend·provider·API 검증에 공유한다. 임의 `dict[str,Any]`를 최종 canonical 객체로 저장하지 않는다. 필드 이름과 아래 관계는 구현 계약이며 SQL 컬럼/JSON 분리는 저장 전략에 따라 정할 수 있다.

| 엔터티 | 필수 키·필드 및 관계 |
|---|---|
| Document | `id,tenant_id,head_revision_id,created_by,metadata_index,lifecycle_state,lifecycle_version,archived_at,deleted_at,retention_deadline`; metadata_index는 검색용 파생 인덱스이며 판본의 metadata는 Revision snapshot이 진실 |
| SourceAsset | `id,tenant_id,sha256,mime,byte_size,original_name,blob_key,created_at`; 원본 bytes immutable |
| SourcePage | `id,asset_id,pdf_page_index?,width_px,height_px,original_sha256`; 업로드 순서와 시험 순서는 별개 |
| SourceManifest | `id,document_id,page_ids_ordered,missing_page_expectation,confirmed_by?,digest`; 번호/개수는 이 시험별 값 |
| Revision | `id,document_id,revision_no,parent_revision_id,mode,restore_baseline_revision_id?,manifest_id,metadata_snapshot,curriculum_policy_snapshot,template_snapshot,content_json,content_hash,style_hash,solution_hash,policy_version,created_by,created_at,change_set_id,clone_lineage?` |
| QuestionNode | immutable `id`, `kind=MCQ/ESSAY_GROUP/ESSAY_LEAF`, `parent_id?`, `position`, `printed_label`, `points?`, `blocks[]`, `choice_ids[]`, `answer_space`, `source_anchors[]`; scored 여부는 kind/정책으로 명시 |
| SharedBlock | `id,blocks[],source_anchors[]`, 사용하는 question ID 목록. 공통 지문·도형 수정 시 해당 자식 전부 영향 |
| Block | `Paragraph / ChoiceGroup / StatementBox / Table / Figure / SharedBlockRef / AnswerSpace`; 각 객체 고유 id |
| Inline | `Text{text} / Math{equation_id}`; 별도 수식 목록을 본문 뒤에 다시 붙이지 않음 |
| Choice | `id,printed_label,blocks[]`; 정답 참조는 choice_id이며 숫자 index만 저장하지 않음 |
| Equation | `id,ast,source_literal?,display_mode,source_anchors[],token_styles`; LaTeX/HWP formula는 compiler의 derived 값 |
| Figure | `id,primitives[],relations[],labels[],source_anchors[],representation=NATIVE_VECTOR/DRAFT_CROP,geometry_digest`; labels는 Text/Math 지원 |
| AnswerSpace | `kind=BLANK_LINES/BLANK_AREA/GRID`, `min_height_pt,line_count?,line_spacing_pt?,source_anchors[]`; 지우거나 줄일 때 EDIT 이력 |
| AnswerSolution | `question_id,answer{choice_id?,value_ast?,accepted_variants[]},steps[],concept_ids[],grade_policy_id,verification_evidence_ids[]`; scored leaf마다 필요 |
| EndnotePlan | `policy=MAJOR_GROUPED/LEAF`, `links[{anchor_question_id,covered_leaf_ids,note_id}]`; 동일 leaf 중복·누락 금지 |
| FieldEvidence | `id,revision_id,target_object_id,field_path,source_anchor_ids[],selected_candidate_id?,review_decision_id?,state`; 렌더링 값과 1대1 또는 명시적 다대1 연결 |
| Candidate | `id,field_evidence_id,typed_value,run_id,input_digest,model,prompt_version,schema_version,provider_confidence?`; confidence 단독 final 통과 금지 |
| SourceAnchor | `page_id,bbox_px{x,y,w,h},transform_id?`; 원본 pixel 좌표, finite·범위 검증. clean/crop 좌표는 역변환 보존 |

부모·자식 관계는 DAG가 아니라 **트리**로 제한하고 순환·다중 부모·dangling 참조를 422로 거절한다. 인쇄 라벨은 부모 범위까지 포함해 해석하며 ID를 라벨에서 생성하지 않는다. 심원중 benchmark의 23 대문항/28 scored leaf/31 node/100점은 fixture assertion이다. 모든 시험에 하드코딩하지 않는다. 배점은 leaf 합계를 사용하고 부모 표시 배점을 다시 더하지 않는다.

기본 템플릿 endnote 정책은 `MAJOR_GROUPED`로 제안한다. 심원중에서는 23개 미주에 28 scored leaf 정답·풀이를 담는다. LEAF로 선택한 템플릿은 28개 미주이며 둘 사이를 자동 변경하지 않는다. 어느 방식이든 28개 모두 coverage를 검사한다. 출력 모드는 `STUDENT_WITH_ENDNOTES / STUDENT_ONLY / ANSWER_ONLY / TEACHER`의 enum이며 기본 요구 산출물은 STUDENT_WITH_ENDNOTES다. STUDENT_ONLY는 본문·부록·숨은 영역·메타데이터를 통한 답안 노출을 검사한다.

`metadata_snapshot`에는 school/year/grade/semester/exam_type/subject, 교과 범위(scope/unit/concept IDs), 제목·머리말 등 인쇄 header metadata를 포함한다. `curriculum_policy_snapshot`은 교육과정 버전·허용 개념/공식과 grade/scope를, `template_snapshot`은 학원 브랜드/서식/출력 정책과 버전을 고정한다. 과거 revision을 현재 Document metadata나 최신 curriculum/template로 렌더링하지 않는다. content_hash는 문항 의미·인쇄 라벨/배점·source manifest·subject/grade/scope 및 curriculum snapshot digest를 포함한다. school/year/semester/exam_type/title/header의 표시 변화는 style_hash(인쇄 presentation hash)에 포함하며, 그런 변경이 scope/curriculum을 바꾸면 content_hash도 변경한다. solution_hash는 정답/풀이/개념 연결을 포함한다. metadata PATCH도 mutation/CAS를 통과하고 grade/scope 변경은 curriculum·정답/풀이·논리 check 및 산출물을 무효화한다. 단순 검색 태그는 검증 대상 content에 포함하지 않되 감사 기록을 남긴다.

필수 provenance 대상은 본문, 보기 내용과 기호, 배점, 조건 수식, 도형 및 도형 라벨·관계, 서술 공간, 원본 인쇄 라벨이다. 추출 결과에 없는 객체는 evidence가 생기지 않을 수 있으므로 페이지별 coverage manifest에 `printed_regions[]`, region 유형/처리 상태/연결 object를 별도로 저장한다. 필기·안내문 등 제외 region도 이유와 원본 anchor를 남긴다. 사각형 면적 전체가 일치한다는 수치만으로 completeness를 입증하지 않는다.

**INV-03 단일 진실:** render/solver/editor는 같은 Revision snapshot을 읽는다. ATU/Candidate 값과 canonical 본문을 따로 저장해 서로 다른 값을 보여 주는 경로는 금지한다. 후보 채택은 해당 typed field를 교체하는 mutation이다. 재materialize를 append로 수행하지 않는다.

**INV-04 번호 보존:** immutable ID는 처리·편집 식별자, position은 정렬, printed_label은 화면·출력 표시다. 자연어 “2번”이 객관식/논술형 양쪽에 매칭되면 `AMBIGUOUS_TARGET` 제안 상태로 멈추고 적용하지 않는다.

### 4.1 수식·도형 제한

Math AST 지원 노드는 우선 `number,variable,unit,operator,relation,fraction,power,root,group,segment,angle,triangle,quadrilateral,degree`로 명시한다. 표준 의미로 변환할 수 없는 인쇄식은 source_literal과 issue를 보존하고 `UNSUPPORTED_MATH`로 final을 차단한다. 숫자/변수의 italic(it), 단위 roman 및 11pt는 compiled native equation 객체 속성과 실제 렌더 결과 양쪽에서 검증한다. 일반 텍스트로 붙인 숫자나 단순 LaTeX 문자열은 수식편집기 조건을 통과하지 않는다.

Figure primitive는 point/segment/polyline/circle/arc/bezier/text/math-label/right-angle/tick/arrow/fill-pattern으로 제한한다. 좌표·stroke·dash·관계는 원본과 비교 가능해야 한다. 모델이 반환한 SVG/HTML/script를 실행하지 않고 JSON primitive를 검증된 renderer로 변환한다. 외부 이미지 URL·font URL·foreignObject·script·event handler 금지. 원본 그래프의 축/눈금/함수선도 typed primitive와 관계로 표현한다. 실제 지원하지 않는 도형은 명시적인 issue이며 draft crop을 final 재작도 성공으로 세지 않는다.

## 5. revision·편집·무효화

모든 변경은 `MutationService.apply(tenant,actor,document,expected_revision,change_set)` 하나를 통과한다. change_set은 `SetField/ReplaceBlock/AddQuestion/DeleteQuestion/ReorderQuestions/SetPageOrder/SetStyle/SetAnswerSolution/SetEndnotePolicy`의 typed union이며 각 연산은 target ID·expected_old_digest·new_value·reason을 갖는다. 임의 JSON Patch로 모든 내부 필드를 쓰게 하지 않는다.

트랜잭션 순서: 인가 → expected head 검사 → 전체 op schema/target 검사 → 새 immutable snapshot 작성 → content/style/solution hash 계산 → 영향 그래프 갱신 → issue·proof stale 처리 → revision·change set·audit·outbox event 저장 → head CAS 갱신 → commit. 한 연산이라도 실패하면 전부 rollback한다. AI 제안 생성 자체는 revision을 바꾸지 않는다.

**INV-05 optimistic concurrency:** mutation에는 `If-Match: "rev:<revision_id>"` 필수. 현재 head와 다르면 409 `REVISION_CONFLICT`, 누락하면 428. 응답은 current revision와 충돌 object ID를 제공한다. 자동 last-write-wins·서버의 숨은 재적용은 금지한다. 여러 사용자가 서로 다른 문항을 편집해도 V1은 문서 단위 CAS로 안전하게 시작하고 명시적 재기반 UI를 제공한다.

**INV-06 undo:** 이전 snapshot을 head로 되돌려 덮어쓰지 않고 그 내용을 복원한 **새 revision**을 만든다. `restores_revision_id`와 actor/reason을 남기며 기존 artifact·proof·감사 기록은 불변이다. 새 revision이 이전과 같은 hash면 proof 재사용 정책에 따라 연결할 수 있지만 새 proof binding과 gate 계산이 필요하다.

| 변경 | 재검증 대상 |
|---|---|
| 본문 숫자·조건·수식·보기 내용·도형 의미·공통 지문 | 영향 문항 전사 대조, 논리, 정답·풀이, 교육과정, 관련 artifact 전부 |
| 정답·풀이·교육과정 정책 | 영향 문항 정답·풀이/개념 검증, notes 포함 artifact |
| 보기 순서/기호 | choice_id 연결·정답 기호·인쇄 의미·해설 참조, artifact 전부 |
| 문항/페이지 순서·인쇄 라벨·배점 | completeness·번호·참조·합계·artifact, 관계가 바뀌면 solve 포함 |
| 글꼴·여백·브랜드·문항 높이 | layout·native object 스타일·overflow·누출·artifact, 의미 hash 불변일 때 solve 재사용 가능 |
| 소스 추가·교체·crop/clean 처리 변화 | 영향 source evidence와 restore 비교, 변경 의미에 따라 solve, artifact |
| 학년·과목·교과 범위·curriculum policy 변경 | 해당 revision 전 문항 curriculum·정답/풀이/논리 check와 artifact. 과거 metadata를 덮어쓰지 않음 |

검증 재사용 키는 `check_kind + input dependency digests + validator/policy version`이다. 단순 document.version 일치 또는 “전에 통과”로 재사용하지 않는다.

문서 복제는 동일 tenant에서만 가능하다. source READ와 tenant CREATE 권한을 검사하고 요청의 고정 source revision을 읽어 새 document ID·revision 1을 만든다. question/block/equation/figure/choice 등 canonical object ID를 새로 발급하고 부모/참조를 전체 remap한다. `clone_lineage={source_document_id,source_revision_id,object_id_map_digest,cloned_by,cloned_at}`를 보존한다. 원본 bytes는 immutable SourceAsset ref를 같은 tenant 안에서 재사용할 수 있으며 refcount/retention으로 원본 문서 삭제가 복제본 자산을 지우지 못하게 한다. source ACL·artifact·다운로드 링크·proof·verification 성공은 복사하지 않는다. 새 문서는 작성자 초기 grant 정책만 적용하고 검증 상태는 NOT_RUN으로 시작한다. 기존 candidate/source provenance는 `inherited_non_authoritative=true`로 출처만 보존하고 새 검증 성공으로 세지 않는다. 동일 tenant 복제라도 원본 content 접근권이 없으면 불가하다.

문서 lifecycle은 `ACTIVE/ARCHIVED/DELETED/PURGED`이며 content revision과 별도의 `lifecycle_version`을 둔다. archive/unarchive/delete/restore는 owner/admin만 가능하고 요청한 content revision 및 lifecycle_version이 현재 값과 일치해야 한다. 보관은 기본 active 목록에서 제외하되 권한 있는 사용자가 보관함·검색에서 명시적으로 포함할 수 있고 읽기 전용이다. 보관 transaction은 신규 mutation/job/출고를 차단하고 진행 job에 cancel_requested를 남긴다. stale worker commit은 archived 상태도 검사한다. 기존 artifact의 과거 판본 다운로드는 EXPORT와 기존 유효 proof가 있는 경우에만 가능하다. 보관 해제는 ACTIVE로 바꾸지만 작업을 자동 재개하지 않는다.

soft-delete는 tombstone·삭제자/시각·retention deadline·job 취소를 함께 저장하고 일반 목록/읽기/미리보기/다운로드에서 즉시 제외한다. 해당 owner/admin의 휴지통 metadata·restore API만 허용하며 일반 object route는 404, 동일 tenant 권한 부족은 403이다. 이미 만든 export/download link도 tombstone을 검사해 사용할 수 없다. 복구는 원본/manifest/blob 존재와 현재 tenant·membership·grant 정책을 재검사하고 ACTIVE로 전환한다. 삭제 중 철회된 권한을 되살리거나 취소 job을 자동 재개하지 않는다. 이전 proof는 역사적 evidence로 보존하되 복구 즉시 final eligibility를 되살리지 않는다. 현재 원본 manifest·artifact hash·policy 적용성과 권한을 확인하고 필요한 검증을 다시 수행한 뒤에만 현재 판본의 final을 허용한다. retention 만료로 purge된 문서는 권한 있는 owner/admin의 restore 요청에 410 `RESTORE_EXPIRED`를 반환하며 빈 문서를 재생성하지 않는다. 문서 lifecycle 변경은 감사와 event를 남기고 멱등 요청으로 중복 처리하지 않는다.

## 6. RESTORE와 EDIT의 검증 의미

RESTORE는 인쇄 원문 재현이다. 잘못 인쇄된 문제라도 몰래 교정하지 않고 `SOURCE_INCONSISTENCY` issue를 남긴다. 수학적으로 풀리지 않으면 최종 적격 상태가 되지 않는다. 사용자에게 명시적인 EDIT 변경안과 이유를 제시할 수 있다.

EDIT revision은 `restore_baseline_revision_id`와 승인된 ChangeSet을 참조한다. source fidelity 검사는 **바꾸지 않은 원문 영역**, edit conformance 검사는 **승인된 변경 집합**, solver/curriculum 검사는 **수정 후 전체 영향 문항**을 대상으로 한다. EDIT 내용을 원본과 글자 그대로 같지 않다는 이유로 실패시키지 않으며, 그 차이를 숨겨 RESTORE 완전복원으로 표시하지도 않는다.

**INV-07 검토와 풀이 분리:** 사용자가 제안 적용을 누른 것은 변경 수락이다. 원본을 보고 해당 필드를 확인하는 `SOURCE_HUMAN_CONFIRMED`, 풀이를 검토하는 `SOLUTION_HUMAN_CONFIRMED`, AI 검증 결과는 별도 evidence다. 일반 “적용” 클릭이나 모델 confidence로 `HUMAN_VERIFIED`를 생성하지 않는다.

독립 solve run에는 원본의 학생 답·필기·기존 Golden 정답·다른 solve 답을 입력하지 않는다. 기본 자동 판정 정책은 **동일 canonical input digest에 대한 유효한 독립 solve attempt 최소 2개**다. 두 attempt는 서로 다른 run_id·independence_slot과 독립 결과를 갖고 서로의 답을 입력받지 않는다. `run_id`가 다르더라도 동일 cache 응답은 독립 결과로 세지 않는다. 두 답의 의미적 일치, 선택지 ID/인쇄 기호 일치, 조건 대입·논리 일관성까지 모두 성립해야 machine agreement가 PASSED다. 두 번의 일치만으로 옳음을 보장할 수 없으므로 별도의 원본 대조·교육과정 검사를 결합한다. 문항이 한 회차에 누락되거나 `solved=false`이면 합의 PASSED가 아니며 quota/오류 때문에 최소 회차를 1로 낮추지 않는다. 해결 불가/다중정답/원본 오류를 표현하는 결과 enum이 있어야 한다.

## 7. proof·issue·최종 출력

`CheckRun`: `id,tenant_id,revision_id,check_kind,input_digest,validator_version,policy_version,state,result_summary,evidence_blob_ids,started_at,finished_at,run_id`. state는 `NOT_RUN/RUNNING/PASSED/FAILED/UNAVAILABLE`. 오래된 check는 값 자체를 지우지 않고 현재 revision에 대해 `applicable=false,stale_reason`으로 표시한다.

`Issue`: `id,revision_id,question_ids,object_ids,source_anchors,kind,severity,blocking,state=OPEN/RESOLVED/WAIVED,resolution_change_set_id?,resolution_check_id?,reason,actor`. 단순 숨김은 해결이 아니다. critical/blocking issue의 WAIVED는 기록은 가능하되 final을 허용하지 않는다. 한계를 수락한 결과는 초안으로만 제공한다.

`Artifact`: `id,tenant_id,document_id,revision_id,format,output_mode,content_hash,style_hash,solution_hash,template_version,renderer_version,artifact_sha256,blob_key,byte_size,state,created_at`. `ArtifactProof`는 artifact_id/hash, manifest, object integrity, rendered pages, visual diff evidence, format-specific checks를 묶는다. blob bytes가 변하면 동일 artifact ID나 proof를 재사용하지 않는다.

**INV-08 순환 없는 단계:**

1. revision structure·source completeness·RESTORE/EDIT conformity·answers/solutions·curriculum을 검사해 `CONTENT_READY` 판정.
2. 렌더용 immutable snapshot과 layout plan으로 **내부 검증용 artifact** 생성. final eligibility가 아직 없어도 가능.
3. 해당 artifact의 구조/내용/수식·도형·미주/실제 렌더·레이아웃/정답 누출 검증 실행.
4. 형식별 required check가 전부 applicable PASSED이고 blocking issue=0이면 `FINAL_ELIGIBLE(format,output_mode,revision)`.
5. 사용자의 final export 요청은 문서 EXPORT grant와 정확한 proof binding을 확인하고 **검증된 동일 bytes를 승격**한다. 승격 시 재렌더한다면 hash가 달라지므로 proof부터 다시 실행한다.

외부 초안 다운로드는 내부 artifact와 구분한다. 초안 파일명·cover 또는 각 페이지 워터마크·메타데이터에 `검토 전 초안`과 revision을 표시한다. 워터마크가 들어간 초안 bytes를 무워터마크 final proof로 재사용하지 않는다. 최종 다운로드 route는 서버에서 eligibility를 다시 검사하고 draft·stale artifact URL로 우회할 수 없게 한다.

**INV-09 형식별 증거:** HWP unavailable이면 HWP final은 막힌다. 독립적으로 proof를 완료한 HWPX/PDF는 해당 형식만 final 가능하다. HWPX가 zip으로 열림, HWP SaveAs 성공, PDF 파일 크기>0은 각각 형식 유효성 일부일 뿐 content/visual proof가 아니다. UI는 “HWPX 통과 / HWP 실행 환경 필요”처럼 표시하며 전체 `VERIFIED_FINAL` 한 단어로 숨기지 않는다.

HWPX proof는 zip 경로 안전성/XML 스키마·native equation/figure/endnote 객체·reference 연결·정확한 문항/보기/풀이·스타일 속성 및 실제 rendering 확인을 포함한다. PDF proof는 font 포함/한글 glyph·페이지 수·본문·도형·수식·미주 내용·bounds를 확인한다. PDF 자체의 편집 가능한 한글 equation 객체는 요구하지 않되 의미/시각 동일성을 검사한다. HWP는 해당 HWPX snapshot에서 변환 후 한글에서 재열기·객체 조사·실제 페이지 렌더·canonical 대조를 수행한다. 역OCR만으로 그림/수식 객체 무결성을 대신하지 않는다.

### 7.1 버전이 고정된 필수 check 정책

`VerificationPolicySnapshot`은 `policy_id,version,mode,output_mode,requested_formats,required_content_checks[],required_artifact_checks_by_format{},validator_versions,minimum_solver_attempts=2,allow_explicit_human_adjudication,created_at,digest`를 가진 불변 객체다. revision·CheckRun·ArtifactProof는 같은 policy digest를 참조한다. 필수 check 목록은 처리 도중 줄이지 못하며 정책 변경은 새 snapshot과 재평가를 만든다. capability에 검사기가 없으면 UNAVAILABLE로 final을 차단하고 목록에서 삭제하지 않는다.

초기 정책 이름은 `EXAM_CONTENT_RESTORE_V1`, `EXAM_CONTENT_EDIT_V1`, `EXAM_ARTIFACT_HWPX_V1`, `EXAM_ARTIFACT_HWP_V1`, `EXAM_ARTIFACT_PDF_V1`, `EXAM_OUTPUT_MODE_V1`로 고정한다. 아래 이름은 `check_kind`의 명시적인 enum이다.

| 필수 content check | RESTORE | EDIT | PASSED에 필요한 증거 |
|---|---:|---:|---|
| `SCHEMA_REFERENTIAL_INTEGRITY` | O | O | typed schema, IDs/FK/트리/choice·equation·figure 참조와 hash 일관성 |
| `SOURCE_REGION_COVERAGE` | O | O | 원본 manifest의 인쇄 region마다 재현/정당한 제외가 연결되고 필수 필드의 provenance가 존재. ATU/FieldEvidence가 0인 대상은 검증 없음이므로 실패 |
| `ORIGINAL_SOURCE_FIDELITY` | O | 변경 안 된 영역 | 추출 실행과 **별도의 원본 대조 audit** run/evidence. original image의 인쇄 텍스트·숫자·보기·라벨·도형/관계·필기 제외를 canonical과 대조. clean image나 extraction 응답 재읽기만으로 통과 불가 |
| `APPROVED_EDIT_CONFORMANCE` | 해당 없음, 정책 제외 이유 기록 | O | restore baseline, 승인 ChangeSet, 변경 영역 diff 일치·승인 밖 변화 0·영향 범위 검증 |
| `QUESTION_CHOICE_SCORE_COMPLETENESS` | O | O | 문항/계층/보기/배점/공통 지문/원본 coverage 일치, 첫·끝 및 소문항 누락 없음 |
| `MATH_FIGURE_SEMANTIC_CONSISTENCY` | O | O | 수식 AST·도형 관계·인쇄 조건·라벨 사이 모순/누락 검사 |
| `SOLVE_TWO_INDEPENDENT_AGREEMENT` | O | O | scored leaf마다 동일 input digest의 유효 독립 2회 이상, 답 의미/choice mapping 일치. 누락·실패 회차를 성공으로 세지 않음 |
| `ANSWER_SOLUTION_LOGIC` | O | O | 최종 정답·풀이 단계·조건 대입/증명·정답 기호가 서로 일치, 풀리지 않음/모호함 해결 |
| `CURRICULUM_COMPLIANCE` | O | O | metadata의 학년/개념 policy와 모든 풀이 단계의 concept_ids·실제 사용 개념 대조 |
| `REQUIRED_CONTENT_COVERAGE` | O | O | 전 scored leaf 정답+풀이와 수식·도형·서술 공간 evidence 완전성. 출력에서 숨기는 답도 내용 검증은 생략 불가 |
| `BLOCKING_ISSUES_CLOSED` | O | O | 이 집계 check를 제외한 다른 필수 content check가 적용 가능·PASSED이며 미해결 blocking issue/critical waiver 0. 아직 생성하지 않은 artifact proof를 content-ready 조건으로 요구하지 않음 |

ORIGINAL_SOURCE_FIDELITY는 수학 solver와 다른 검사다. solver가 정답을 맞혔어도 오전사한 조건·선택지·그림이 원본과 같은지 증명하지 못한다. 원문 오류를 EDIT로 바꾼 경우 원본과 다르게 만든 부분은 APPROVED_EDIT_CONFORMANCE로 검증하고, 수정 자체를 source restoration으로 기록하지 않는다.

| 필수 artifact check | HWPX | HWP | PDF | 최소 evidence |
|---|---:|---:|---:|---|
| `FORMAT_OPEN_VALIDITY` | O | O | O | 실제 포맷 parser/앱 열기, 손상·누락 참조 없음 |
| `NATIVE_OBJECT_INTEGRITY` | O | O | PDF 표현 검사 | HWP(X)의 편집 가능한 수식·도형·미주 객체/연결·속성. PDF는 glyph/font/vector/출력 객체 존재와 의미 보존을 검사하며 native 한글 객체 조건을 적용하지 않음 |
| `ARTIFACT_SEMANTIC_COVERAGE` | O | O | O | revision/출력 모드에서 기대한 문항·보기·수식·도형·배점·풀이·미주 manifest와 실제 text/object 수·값·연결을 대조. 수만 같아도 내용이 다르면 실패 |
| `RENDERED_TEXT_VISUAL_MATCH` | O | O | O | 실제 rendered page와 canonical/layout plan의 텍스트·수식·도형 시각 대조, 검사기/evidence 버전·페이지 이미지 기록 |
| `LAYOUT_STYLE_BOUNDS` | O | O | O | 11pt/it/roman·row 정렬·서술 공간·페이지 bounds·잘림/겹침/누락 없음 |
| `FORMAT_CONVERSION_PROVENANCE` | 생성 manifest | O | 생성/변환 manifest | exact source revision/artifact hash→output hash, renderer/변환기 버전. HWP는 exact verified-snapshot HWPX 입력 필수 |
| `HWP_ACTUAL_REOPEN` | HWPX 실제 rendering evidence는 위 검사에서 필요 | **O** | 해당 없음 | 중앙 Windows 한글의 실제 HWP 재열기·객체 추출·render 결과·worker identity/version/action 결과. mock·파일 존재·SaveAs 성공만으로 대체 불가 |
| `OUTPUT_MODE_CONTENT_POLICY` | O | O | O | 아래 모드별 본문/미주/정답 노출 규칙 |
| `ARTIFACT_HASH_BINDING` | O | O | O | proof 대상 bytes와 내려받을 bytes hash·revision·policy snapshot 일치 |

출력 모드별 `OUTPUT_MODE_CONTENT_POLICY`:

- `STUDENT_WITH_ENDNOTES`: 시험 본문에 정답·풀이가 새지 않고 미주가 모든 scored leaf를 정확히 한 번 cover한다. HWP(X)는 실제 미주 객체/anchor를 검증하고 PDF는 해당 미주 내용·인쇄 연결/번호를 검증한다.
- `STUDENT_ONLY`: 동일한 전 content check를 통과해야 하며 답·풀이 content 자체를 검증에서 빼지 않는다. 산출물에는 정답·풀이·미주를 의도적으로 넣지 않고 hidden text/메타데이터/부록까지 누출 검사한다. 이 모드의 endnote count=0은 정책상 기대값으로 저장하며 누락 결함과 구별한다.
- `ANSWER_ONLY`: 모든 scored leaf 정답+풀이와 원래 문항 라벨/참조를 포함하고 시험 본문은 선택된 템플릿 정책에 맞게 생략한다. 본문 생략과 미주 객체 비사용이 의도된 경우 expected artifact manifest에 기록한다.
- `TEACHER`: 문항/정답/풀이·검토용 표기는 고정 템플릿 규칙을 따라 모두 검증한다. 학생용으로 잘못 분류·다운로드되지 않게 모드 표식과 metadata를 확인한다.

`HUMAN_ADJUDICATION`은 check의 새 증거 method이며 issue waiver나 포괄 확인 버튼이 아니다. unresolved source field/solution 검사에 한해 policy가 허용하고 해당 문서 REVIEW 권한을 가진 actor가 대상 field/leaf ID, source anchors, 수정/확인 값, 판단 이유, 확인한 원본/풀이 evidence, actor/time, input digest를 명시한 adjudication record를 만들면 해당 check의 사람 검증 경로로 재평가할 수 있다. 해결하지 않은 다른 필드/문항은 계속 막힌다. 자동 풀이 2회 기준은 그대로 유지하고, 사람 경로로 대체된 check는 `method=HUMAN_ADJUDICATED`로 표시하며 기계 2회 합의 성공이라고 기록하지 않는다. quota 발생만으로 자동 전환/자동 통과할 수 없다. 타입/참조/해시/실제 포맷 열기·객체 무결성·레이아웃·HWP 실제 재열기 등 기계적 필수 증거와 critical issue는 사람 확인으로 면제할 수 없다.

**INV-10 산출물 일치:** HWPX/HWP/PDF에 revision·content/style/solution digest·출력 모드가 동일해야 “같은 판본 묶음”이다. 현재 head가 바뀌면 기존 final artifact는 과거 판본으로 열람 가능하되 현재 문서 다운로드 버튼에서 새 판본처럼 제공하지 않는다.

## 8. 공통 layout plan과 한글 worker

각 renderer가 자기 규칙으로 문항을 재배열하지 않게 `LayoutPlan(revision_id,template_version,pages,blocks,placements,reading_order,overflow_issues,measured_font_metrics)`을 공유한다. 단위는 pt이고 page size/margin/column gap/brand 영역을 명시한다. 기본 A4, 2단에 열당 MCQ 2개: reading order는 좌상→좌하→우상→우하, 정렬 쌍은 (1,3), (2,4)다. row 높이는 쌍의 큰 높이이며 작은 쪽에 padding을 더한다. 다음 row의 두 시작 위치 오차 목표는 0.5pt 이하, 수식 목표 11pt±0.1pt다. 이는 인수 기준 제안이지 현재 달성 성능이 아니다.

문항 height를 content+선택지+도형+answer space까지 측정한다. 해당 page capacity를 초과하면 11pt와 답안 공간을 줄여 억지로 넣지 않는다. 우선 block 단위 다음 페이지 배치, 긴 MCQ는 해당 행의 단독 block/명시적인 별도 페이지로 배치한다. essay group은 가능한 한 함께 두고 한 페이지보다 크면 소문항 경계에서 나누되 공통 지문/도형 참조를 유지한다. 한 소문항도 한 페이지보다 크면 표·문단 경계의 허용 split만 사용하고 continued label과 참조를 넣는다. 지원할 수 없는 overflow는 final 차단 및 사용자에게 표시한다. 임의 clip/hidden overflow 금지. 구체적인 템플릿 선택과 페이지 UX는 03 문서와 함께 인수한다.

Windows worker는 전용 OS 계정·tenant/job별 일회성 임시 디렉터리·한 프로세스당 한 작업을 사용한다. 중앙에서 관리하는 Windows pool만 운영 V1에 포함한다. 작업 간 메모리/임시파일/COM 문서 잔류를 정리하고 failure 후 quarantine된 worker는 health 재통과 전 새 tenant 작업을 받지 않는다. `health`는 Windows/COM 등록/한글 버전/라이선스 준비 상태/작은 안전 fixture 열기·저장·render capability를 확인한다. 실제 사용할 수 있는 action을 capability로 반환하며 pywin32 import 성공만으로 ready 처리하지 않는다. 적합한 서버 실행 환경·설치 및 라이선스 확인과 실제 변환 인수는 HWP 출시 차단 조건이다.

`Open/SaveAs/Print` 반환값, 출력 존재/크기/parseability/hash를 검사한다. finally에서 문서 닫기·Quit·COM 정리를 수행하고 timeout 때 해당 worker가 시작해 소유한 프로세스만 종료한다. 사용자가 열어 둔 한글 프로세스를 이름으로 일괄 종료하지 않는다. 보안 경고를 OS 전체에서 끄지 않고 신뢰하는 앱 생성 artifact만 여는 경로를 구현한다. 외부 링크/OLE/macro 실행은 허용하지 않는다. 모델/사용자가 경로·COM action·임의 명령을 지정할 수 없다. HWP 참고파일 읽기는 개발 인수 자료용이며 임의 HWP 업로드 실행을 SaaS 기본 기능으로 확대하지 않는다.

## 9. durable job·재시도·공정성

Job은 `tenant_id,document_id,input_revision_id,profile_id,kind,state,current_stage,priority,created_by,idempotency_key,attempt_count,not_before,lease_owner,lease_token,lease_expires_at,heartbeat_at,cancel_requested_at,last_error,output_revision_id`를 저장한다. stage output은 content-addressed checkpoint다.

상태: `QUEUED → RUNNING → SUCCEEDED`, 분기 `WAITING_QUOTA / WAITING_AUTH / WAITING_WORKER / RETRY_SCHEDULED / CANCEL_REQUESTED → CANCELLED / FAILED`. 검토 이관은 stage event `WAITING_REVIEW`를 기록하고 checkpoint·issue·review handoff를 한 transaction에 저장한 후 job을 **terminal `COMPLETED_REVIEW_HANDOFF`**로 닫는다. UI 문서는 “검토 필요”를 유지하지만 job은 진행 중으로 남기지 않으며 모든 concurrency slot·lease를 반납한다. 기타 WAITING_*도 worker/tenant 동시 실행 slot을 점유하지 않고 eligibility가 회복될 때 scheduler가 다시 claim한다. 성공은 output·checkpoint·event가 durable commit된 후에만 기록한다. 중앙 인증/worker 장애는 운영자가 복구하며 학원 사용자에게 API 키/한글 설치 조치를 요구하지 않는다.

`ReviewHandoff(id,parent_job_id,checkpoint_id,revision_id,issue_ids,status=OPEN/RESUMED/SUPERSEDED/CANCELLED,successor_job_id?,terminal_outcome?)`를 저장한다. 관련 검토가 완료되면 현재 revision을 입력으로 새 successor verification job을 만들고 handoff를 RESUMED로 바꾼다. 동일 handoff/revision의 중복 resume은 같은 job을 반환한다. 부모 job은 terminal 이관 상태로 유지하고 다시 RUNNING으로 되살리지 않는다. successor 성공·실패·취소는 handoff의 terminal_outcome과 체인 summary event에 전파되어 문서 화면이 최신 결과를 표시한다. successor가 다시 검토 이관이면 새 handoff를 연결하고 최신 OPEN handoff가 다음 동선이다. 과거 input revision을 대상으로 한 미시작 successor는 새로운 revision으로 대체될 때 `CANCELLED`+`OBSOLETE_INPUT` 사유로 닫고 handoff는 SUPERSEDED로 바꾼다. 이미 실행 중인 결과는 stale-write 계약에 따라 입력 revision에만 격리하며 현재 문서가 검증 성공으로 바뀌지 않는다. 사용자가 문서/검토를 취소하면 OPEN handoff를 CANCELLED로 닫는다. 따라서 검토를 기다리는 오래된 부모 job이나 동시 실행 slot이 영구 누수되지 않는다.

**INV-11 stale write 방지:** lease claim은 DB 원자 연산이며 매 attempt의 fencing token을 증가시킨다. heartbeat/결과 저장은 `(job_id,attempt_id,lease_token,expected_state)` 일치를 검사한다. 오래된 worker는 raw evidence를 격리 보관할 수 있지만 canonical head·artifact final·job success를 commit할 수 없다. source revision이 현재 head와 달라지면 결과를 그 입력 revision에만 연결하거나 `STALE_INPUT`으로 재기반을 요청하고 최신 head를 덮어쓰지 않는다.

초기 제안: tenant별 동시 inference 1, tenant queue 20, global 동시수는 운영 설정·측정 뒤 확정. 중앙 scheduler는 tenant round-robin + tenant별 FIFO, 관리자 우선순위가 있어도 낮은 우선순위를 영구 굶기지 않는다. tenant별 byte/page/job 한도와 일일 provider 사용 예산은 설정하고 거절/대기 이유를 노출한다. 한 학원이 quota에 걸려도 다른 tenant의 queue를 막지 않는다. 구독 한도 소유자가 같은 DEV_QA 작업은 공용 allowance라는 사실을 별도 계측한다.

초기 lease 90초/heartbeat 20초, 실행 timeout 10분/한글 action timeout 120초를 **튜닝 시작값**으로 제안한다. 실제 배포 성능을 보장하는 수치가 아니다. 장기 단계는 heartbeat를 별도 thread/process에서 유지하고 hard timeout과 UI 상태를 분리한다. 재시작 시 만료 lease를 찾고 저장 checkpoint부터 이어간다. provider 호출은 네트워크 특성상 exactly-once를 보장하지 못하므로 attempt ledger로 결과 불명확 상태를 기록하고 무제한 재호출하지 않는다.

retry: transient/network/provider 일시 오류는 최대 2회, jitter backoff(초기 5초, 다음 30초). quota는 reset 시각이 있으면 그 이후, 없으면 사용자 재시도 전 `WAITING_QUOTA`. auth는 `WAITING_AUTH`; 잘못된 schema는 실패 output을 저장하고 제한된 1회 수정 요청 후 review. unsupported math/미판독/내용 충돌은 retry 루프 대신 review. 모든 재시도는 같은 job 내 새 attempt와 명확한 누적 사용량을 가진다.

취소: API가 cancel_requested를 durable 저장하고 worker에 알린다. 완료 commit과 취소 요청은 같은 row lock에서 직렬화한다. 성공 commit이 먼저면 취소는 409 `ALREADY_COMPLETED`, 취소 요청이 먼저면 late output을 final로 만들지 않는다. source/document는 보존하고 부분 artifact는 internal 상태로 남긴다. 취소 후 재실행은 새 job이며 중복 업로드/문항을 만들지 않는다.

문서 삭제는 tombstone와 관련 job 취소 요청을 같은 transaction에서 처리한다. worker commit은 tombstone도 검사하고 삭제 문서를 부활시키지 못한다. tenant 비활성화는 신규 호출·lease·다운로드를 차단하고 이미 실행 중인 외부 호출의 취소 가능 여부/발생 사용량을 기록한다. 개별 회원 탈퇴는 그 사용자의 세션/SSE/access를 철회하되 tenant가 소유한 결과·감사 기록을 제거하지 않는다.

## 10. 운영 OpenAI API 및 개발 Codex CLI adapter

### 10.1 운영 중앙 API

제안 adapter는 OpenAI Responses API의 image input + structured output을 사용한다. 추출은 `gpt-5.6-luna`, 선택적 검증은 `gpt-5.6-terra`를 비교 후보로 삼는다. 후보 기능은 공식 [Luna 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.6-luna)와 [Terra 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.6-terra)에 근거하며, 계정별 실제 가용성과 배포 시점 가격은 WP00에서 다시 확인한다. 구독 CLI의 모델 선택 성공을 API 접근 가능성 증거로 쓰지 않는다. 아직 실제 유료 API 호출 또는 이 시험의 정확도 측정이 실행된 것은 아니다.

`InferenceRequest`는 `operation=EXTRACT_PAGE/SOLVE/VERIFY_SOURCE/PROPOSE_EDIT`, `tenant_id,job_id,attempt_id,logical_operation_id,provider_call_id,input_refs,canonical_input?,response_schema_version,prompt_version,model_profile,max_output_tokens,timeout_ms,independence_slot`이다. `provider_call_id`는 **각 외부 요청 전에 서버가 생성하고 DB에 영속 저장하는 UUID**다. 하나의 attempt에 여러 call이 있을 수 있으며 모든 call을 구분한다. 응답은 `run_id,provider_call_id,provider_response_id?,effective_model,typed_result,usage{input_tokens?,output_tokens?,cached_tokens?},finish_reason,cost_estimate?,rate_limit_reset_at?`이며 schema/coverage 검증을 통과해야 commit한다. 공급자가 반환하는 provider_response_id는 선택적 보조 metadata이며 내부 요청 식별자/정산 PK를 대체하지 않는다. API 자격증명은 중앙 secret store에서 executor만 읽고 사용자/Devin 프롬프트/로그에는 포함하지 않는다. SDK 추가가 필요하면 12절 dependency 결정에 따른다.

API 전송 입력은 해당 작업의 page/crop·schema·필요 문항만이다. 다른 tenant의 문서/긴 저장소 지침/학생 답/기존 오답 Golden을 넣지 않는다. 외부 URL을 모델이 임의 fetch하게 하지 않으며 파일 업로드 방식의 보관/삭제 정책을 공급자 설정과 함께 기록한다. 공급자 rate-limit은 tenant와 global 예산을 분리해 관리한다. model 응답의 원문 지침은 데이터로 취급하고 tool use·임의 코드 실행을 켜지 않는다.

비용 ledger의 reservation/usage settlement/idempotency key는 `(tenant_id,provider_call_id)`다. 요청 전 call row와 예산 reservation을 한 transaction에서 저장한 뒤 외부 요청을 보낸다. token 사용량·가격표 버전·estimate/actual 상태를 기록하고 같은 응답 재처리는 동일 call에 한 번만 settle한다. 결과 불명확 timeout은 임의 0원으로 처리하지 않고 `USAGE_PENDING`으로 두어 조정하며 원 call을 지우지 않는다. 실제 재시도 호출은 새 provider_call_id를 생성하고 같은 logical_operation_id·관련 attempt·retry_of_call_id로 연결하여 비용을 별도로 합산한다. 공급자 API가 지원하는 경우 요청 idempotency 헤더에 이 call ID를 전달하지만 외부 exactly-once 실행을 보장한다고 간주하지 않는다. soft limit은 안내·확인, hard limit은 `WAITING_QUOTA`와 운영자 조정 동선을 제공한다. 구독 “무료 잔여분”으로 운영 API 예산을 계산하지 않는다. 유료 모델 승격·추가 provider 전환은 사전 승인된 profile에서만 가능하고 기본 fallback은 disabled다.

API key의 권한·프로젝트·환경(dev/staging/prod)을 분리한다. provider unavailable·quota·네트워크 재시도 정책은 9절을 공유한다. 중앙 worker 서비스 계정에 tenant 전체 DB 권한 대신 job lease에 연결된 필요한 scope만 주고, 결과의 tenant_id는 모델 응답이 아니라 서버 TaskEnvelope에서 결정한다.

### 10.2 개발·검증용 Codex CLI

이 절은 DEV_QA_LOCAL에만 적용한다. 중앙 production runtime에 CLI를 두거나 학원에 설치를 요구하지 않는다. 설치된 CLI의 실제 `version/help/login status`와 model availability를 먼저 확인한다. 기존 조사에서 CLI 0.118.0과 `service_tier` 설정 호환 문제가 있었으므로 동일 값을 무조건 하드코딩하지 않는다. 사용자 전체 설정을 몰래 변경하지 않는다. CLI가 지원하는 인자와 structured-output 형식을 capability test로 검증한 후 adapter version을 고정한다.

adapter는 shell 문자열 연결 대신 argv 배열로 process를 생성하고 job workdir에 필요한 이미지·schema·명시적 지침만 staging한다. 기본 셸·시작 폴더·사용자 repository AGENTS·MCP/plugin·임의 tool execution이 영향을 주지 않게 실행 환경을 최소화한다. CLI에서 도구 접근을 충분히 제한할 수 없으면 격리 OS identity/VM 등 실행 격리를 추가한다. 인증 파일은 CLI 공식 경로/OS 보호 아래 둔다. 앱이 token을 읽거나 DB·frontend·Devin bundle에 넣지 않는다. inference 프로세스가 읽는 raw source에는 불필요한 학생 이름·학번을 마스킹할 수 있으나 문제 영역 훼손 검사를 통과한 파생본만 사용하고 원본은 보존한다.

모델 profile: extraction Luna 후보, verification Luna/Terra 후보. exact model ID·reasoning effort는 설치/계정 availability와 held-out 품질 비교로 결정한다. 자동 고급 모델/유료 API fallback은 없다. 지원 모델이 없으면 CONFIGURATION_REQUIRED, 한도면 WAITING_QUOTA. CLI exit code만으로 성공을 판정하지 않고 마지막 구조화 출력의 JSON Schema·문항 coverage·source digest·unknown field 정책을 검증한다. 스트림 JSON event는 로그이고 canonical output은 schema를 통과한 result만이다.

에러 enum: `AUTH_REQUIRED, QUOTA_EXHAUSTED, MODEL_UNAVAILABLE, CONFIG_INCOMPATIBLE, NETWORK_TRANSIENT, TIMEOUT, CANCELLED, INVALID_SCHEMA, CONTENT_INCOMPLETE, UNSUPPORTED_INPUT, TOOL_ACCESS_VIOLATION`. raw stderr는 제한된 관리자 evidence로 저장하며 사용자 오류에는 token/path·원본 본문을 유출하지 않는 code·요약·재시도 가능 여부·correlation ID만 보낸다.

캐시 키는 tenant scope, input asset/crop digest, preprocessing version, stage, canonical input digest, provider/model/effective configuration, prompt version, schema version, policy version, independence slot으로 구성한다. 캐시 hit에는 original run_id를 유지하며 단순 재읽기를 새 독립 검증으로 꾸미지 않는다. **INV-12 캐시 신뢰:** cache는 model response 재사용일 뿐 proof가 아니다. offline replay mode의 miss는 로컬 CACHE_MISS로 즉시 실패하고 어떤 키가 있어도 네트워크로 전환하지 않는다. 기존 잘못된 Golden은 수정 기준과 분리하며 모델 답 생성에 주입하지 않는다. tenant 간 내용 캐시 공유는 V1에서 금지한다.

## 11. HTTP·event 계약

전부 `/api/v1`, 인증 필수, workspace/tenant route scope. envelope는 성공 `{data,request_id}` / 오류 `{error:{code,message,details,retryable},request_id}`. 예상 가능한 검증 실패를 200 `{ok:false}`나 raw traceback으로 보내지 않는다. 응답 데이터에는 revision/proof identity를 포함한다.

| Method·route (tenant prefix `/tenants/{tenant_id}` 이하) | 요청·성공 결과 | 주요 실패 |
|---|---|---|
| POST `/documents` | metadata·출력 profile; 201 doc/head + Location | 403/422 |
| POST `/documents/{d}/clone` | source READ+tenant CREATE, If-Match source revision, Idempotency-Key; 201 새 doc/revision 1 | 403 권한, 404 다른 tenant, 409 source revision 변경 |
| POST `/documents/{d}/archive` | owner/admin, If-Match revision, expected_lifecycle_version·Idempotency-Key; 200 ARCHIVED/새 lifecycle version | 403/404/409 revision 또는 lifecycle 충돌 |
| POST `/documents/{d}/unarchive` | owner/admin, If-Match revision, expected_lifecycle_version·Idempotency-Key; 200 ACTIVE, job 자동 재개 없음 | 403/404/409 잘못된 상태/충돌 |
| DELETE `/documents/{d}` | owner/admin, If-Match revision, expected_lifecycle_version·Idempotency-Key; 200 tombstone/retention deadline | 403/404/409 충돌 |
| POST `/documents/{d}/restore` | owner/admin, If-Match tombstone의 revision, expected_lifecycle_version·Idempotency-Key; 200 ACTIVE/재검증 필요 | 403/404/409 충돌, 410 RESTORE_EXPIRED, 422 manifest/blob 불완전 |
| POST `/documents/{d}/assets` | multipart, user filename은 표시용; 201 asset/page manifest | 413 크기, 415 유형, 422 손상/암호 PDF |
| PUT `/documents/{d}/source-manifest` | If-Match, page ID 순서/expected coverage; 200 새 revision | 409/422 |
| POST `/documents/{d}/jobs` | kind·revision_id·profile_id·scope; Idempotency-Key; 202 job | 409 stale, 422 missing configuration, 429 queue full |
| GET `/documents`, `/documents/{d}` | tenant 목록/현재 snapshot, ETag·gate summary | 404 |
| GET `/documents/{d}/revisions/{r}` | 불변 snapshot/이력/변경 비교 | 404 |
| GET `/documents/{d}/issues` | revision·유형·상태·문항 필터와 cursor | 422 invalid cursor |
| POST `/documents/{d}/issues/{i}/resolve` | If-Match, typed value/결정·source 확인 evidence; 200 새 revision + dirty checks | 409/422 |
| POST `/documents/{d}/edit-proposals` | instruction·target IDs·base revision; 202 proposal job | 409/422 ambiguous input |
| GET `/documents/{d}/edit-proposals/{p}` | typed diff·영향·경고·적용 가능 상태 | 404 |
| POST `/documents/{d}/edit-proposals/{p}/apply` | If-Match, accepted op IDs·reason; 200 새 revision | 409 stale proposal, 422 invalid op |
| POST `/documents/{d}/changes` | If-Match, typed manual operations; 200 새 revision | 409/422 atomic reject |
| POST `/documents/{d}/undo` | If-Match, restore revision·reason; 200 새 revision | 409/422 |
| POST `/documents/{d}/redo` | If-Match, 재적용 change set·reason; 200 새 revision | 409/422, 대상 바뀜 시 자동 적용 금지 |
| GET `/documents/{d}/pages/{p}/crop` | finite bbox·variant·transform; authenticated image response | 404/422 |
| POST `/documents/{d}/artifacts` | EXPORT 필수, revision·format·mode·purpose=DRAFT/PROOF; 202 render job | 403 권한, 422 unsupported capability |
| GET `/documents/{d}/eligibility` | revision·requested formats/mode; per-format checks·blockers | 404/422 |
| POST `/documents/{d}/exports` | EXPORT 필수, If-Match, artifact IDs·purpose=FINAL; 201 export bundle | 403 권한, 409 revision mismatch, 422 proof/issue gate |
| GET `/artifacts/{a}/download` | EXPORT 필수, explicit draft/final purpose·artifact digest, exact bytes | 403/404/409 stale requested as current/422 blocked |
| GET `/jobs/{j}` and `/jobs/{j}/events` | durable state and authorized SSE | 404/410 expired cursor |
| POST `/jobs/{j}/cancel`, `/jobs/{j}/retry` | 202 or same idempotent result | 409 illegal transition/429 |

멤버/공유 API도 같은 tenant prefix를 쓴다. `/memberships`, `/invitations`, `/documents/{d}/access-grants`의 생성·갱신·철회는 owner/admin만 허용한다. invite는 일회성·만료·대상 이메일 확인 및 tenant role 제한을 검사한다. teacher가 arbitrary user에게 문서를 공유해 권한을 확장하는 API를 열지 않는다. 문서 목록·검색은 role+DocumentAccess를 반영하고 guessed grant/document/job ID로 우회할 수 없어야 한다. 플랫폼 운영 `/ops/*`는 별도 platformoperator service policy와 감사 대상으로 분리한다.

목록은 `GET /documents?lifecycle=ACTIVE|ARCHIVED|DELETED`로 범위를 명시하고 DELETED 휴지통 조회는 owner/admin만 허용한다. 응답은 content revision과 lifecycle_version을 함께 제공한다. archive/unarchive/delete/restore의 Idempotency-Key는 다른 mutation과 동일한 요청 hash 규칙을 사용하며, 현재 lifecycle_version이 바뀐 후의 새 요청은 409로 재조회하게 한다. 실제 purge는 retention 정책의 내부 작업이며 사용자 DELETE가 즉시 영구삭제로 바뀌지 않는다. purge 후 복구 가능성을 판별할 최소 tombstone은 개인정보 보관 정책 범위 안에서 유지하고 다른 tenant에는 존재를 노출하지 않는다.

job submit/retry는 kind별 권한을 재검사한다. RENDER/EXPORT job을 `/jobs`로 직접 제출하거나 과거 job을 retry하는 방식으로 EXPORT 검사를 우회할 수 없다. reviewer의 검토용 페이지/crop/proof preview는 READ/REVIEW 범위에서 제공하되 원본 artifact binary 다운로드 route나 signed artifact URL을 포함하지 않는다. 이미 발급한 export link와 job result에도 매 요청마다 현재 역할/EXPORT grant를 적용한다.

POST mutations/job submit/exports는 `Idempotency-Key`를 지원한다. scope는 `(tenant,actor,route,key)`, 저장 값은 request hash + 원래 response + resource ID다. 같은 key·같은 payload는 기존 결과, 같은 key·다른 payload는 409 `IDEMPOTENCY_CONFLICT`. 처리 중에는 기존 job/operation을 반환한다. 최소 7일 보관을 제안하며 영구 artifact identity를 대신하지 않는다.

crop의 source ID/page ID는 DB에 있는 해당 tenant 자산만 허용하고 filesystem path·URL 입력을 받지 않는다. 음수 index/bbox, NaN/Infinity, 역전된 box, 페이지 밖 전체 box는 422다. 지원하지 않는 media는 암묵 변환 실패 대신 정확한 오류를 준다.

SSE event: `id=<job_id>:<seq>`, `event=job.state|stage.started|stage.progress|issue.created|revision.created|artifact.proved|job.completed`, data `{job_id,seq,timestamp,state,stage,revision_id?,completed_units?,total_units?,error?}`. progress 분모가 모르면 null이며 99%에 무한 대기시키지 않는다. event sequence는 DB에서 유일하게 증가, state/output transaction과 함께 outbox에 저장한다. 재접속은 Last-Event-ID 이후를 재생하고 UI는 seq 중복을 제거한다. 과거 cursor 만료는 410과 최신 상태 조회 안내, event 완료가 없더라도 GET job으로 복구한다. API gateway buffering/heartbeat를 인수 테스트한다.

## 12. 저장·마이그레이션·보안·운영

**목표 저장 결정(제안):** 다학원 production은 PostgreSQL + private object storage, DB queue부터 시작한다. Redis/Celery를 반드시 추가하지 않는다. DB driver·migration tool·object client가 현 의존성에 없으면 Devin은 dependency decision 기록(필요성/버전/라이선스/운영·보안 영향/대안)과 사용자 승인 절차를 거쳐 설치한다. 이 문서는 의존성을 이미 추가하거나 승인받았다는 의미가 아니다. local unit test의 stdlib SQLite는 일부 저장 테스트에 쓸 수 있으나 production locking/RLS/transaction 인수는 PostgreSQL에서 수행한다.

blob 저장은 content-addressed immutable key, 임시 업로드 → 길이/hash 검사 → private final blob 확정 → DB reference commit 순서다. 실패하면 orphan cleanup 대상으로 두고 DB가 존재하지 않는 blob을 final artifact로 가리키지 않게 한다. blob과 DB는 하나의 ACID transaction이 아니므로 outbox·reconciliation·reference count/retention으로 보정한다. 원본을 같은 이름으로 덮어쓰지 않는다. backup은 DB 시점과 blob manifest를 함께 snapshot하고 별도 격리 환경에서 tenant 단위 restore를 검증한다.

현재 JSON 데이터 이관: 원본·JSON·artifact 전체 읽기 전용 백업 및 checksum → legacy import dry-run/report → 명시적으로 지정한 tenant 소유권 매핑 → stable ID 보존·누락 ID 생성 기록 → immutable 첫 revision → 모든 기존 final/proof를 `LEGACY_UNVERIFIED`로 격리 → 개수/hash/FK 대조 → 전환. 잘못된 JSON은 무시하지 말고 quarantine/report. 재실행 importer는 import batch+source hash로 멱등적이어야 한다. 데이터와 schema rollback 절차 없이 운영 upgrade하지 않는다.

업로드 안전: filename은 표시 metadata, 서버가 generated ID로 저장. path traversal·Windows ADS·절대경로·symlink/reparse point·zip slip·압축 bomb·이미지 decompression bomb·PDF page bomb을 제한한다. PRD와 동일한 초기 제안은 **파일당 50MiB, 문서당 50페이지·총 200MiB, 이미지당 40MP**이며 service capability/configuration으로 노출한다. MiB는 1,048,576 bytes, MP는 1,000,000 pixels로 계산한다. PDF는 rasterize하기 전 원본 byte/page 한도를 검사하고 렌더 해상도·최대 pixels도 제한한다. 실제 지원 범위/성능을 측정하기 전 무제한이라고 표시하지 않는다. PDF rasterizer/font/render 도구 선택은 별도 dependency decision 후 고정하고 executable path·인자를 allowlist한다.

웹 보안: same-site secure session cookie·CSRF·origin 검증·CSP·출력 escape, raw OCR/수식/AI 텍스트의 HTML 삽입 금지. DEV_QA_LOCAL이 loopback endpoint를 제공한다면 loopback bind+Origin allowlist+session token+replay 방지로 악성 웹페이지가 local worker를 구동하지 못하게 한다. production secret은 OS/배포 secret manager, 로그·DB 본문·브라우저에 넣지 않는다. prompt injection은 이미지·문서 내의 “지침”도 데이터라는 provider 지침과 tool 차단, typed output validation으로 방어한다.

privacy: 원본·학생 식별 정보·추론 결과는 해당 tenant 범위의 민감 데이터로 취급한다. 외부 처리 공급자·보관·삭제·허용 region/환경을 운영 정책으로 명시하고 실제 전송 실행 전에 자료 소유자의 사용 권한과 provider 전송 범위를 확정한다. 로그인 구독이 있다는 사실만으로 모든 학생 자료 전송 승인이 있었다고 해석하지 않는다. 학원별 보관 기간, 휴지통(제안 30일), 만료 blob 제거, 백업 만료를 문서화한다. 앱에서 삭제한 즉시 모든 백업까지 사라졌다고 주장하지 않는다.

감사 event는 actor/tenant/request/job/revision·행위·결과·digest·시각을 기록하고 일반 로그에 본문/학생 이름/토큰을 넣지 않는다. 지원 담당자는 기본적으로 원본 열람 권한이 없고 필요 시 tenant가 허용한 한시 접근과 감사 기록을 남긴다. metrics는 단계 성공/실패/재시도/queue age/quota wait/cache hit/누락/수정 빈도/작업별 사용량(제공되는 범위)을 집계한다. 확인되지 않은 추론 token 사용량을 추정치 없이 확정값으로 표기하지 않는다.

## 13. 구현 순서와 계약 완료 판정

1. tenant/RBAC·DB/schema·blob 경계·source manifest·immutable revision·CAS를 먼저 만든다.
2. mutation/proposal/issue/undo와 dependency invalidation을 연결한다.
3. durable queue·lease·idempotency·SSE recovery·profile interface를 만든 뒤 cache-only provider를 붙인다.
4. field coverage·RESTORE/EDIT 검증·정답/풀이/curriculum 및 fail-closed gate를 연결한다.
5. common layout·native equation/figure/endnote·형식별 artifact/proof를 연결한다.
6. 운영 프로필의 실제 인증·전송 정책·비용 및 Windows capability가 확정되면 환경별 실제 인수를 진행한다.

멀티 tenant 음성 테스트, stale worker/동시 편집, 실패·취소·복구, 같은 revision의 실제 HWP/HWPX/PDF 객체·화면 증거, cache-only 네트워크 0, 잘못된 proof의 final 차단이 있어야 계약 완료다. API schema만 작성했거나 zip 생성 테스트만 통과한 상태는 완료가 아니다. 상세 시나리오와 재현 증거는 04 인수 테스트 문서를 따른다.
