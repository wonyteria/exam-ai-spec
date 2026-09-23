# 기존 HWP 안전 리브랜딩 명세

작성일: 2026-09-19  
상태: 신규 REQ-16 세부 계약. 구현·검증 완료를 뜻하지 않는다.

## 1. 사용자 목표

다른 학원에서 제작한 HWP/HWPX 시험지를 업로드해 다음 작업을 안전하게 수행한다.

1. 상단의 기존 학원 제목·로고 블록을 현재 학원명/브랜드로 교체한다.
2. 각 페이지 중앙에 현재 학원 로고 워터마크를 넣는다.
3. 하단의 쪽번호만 제거한다.
4. 문제 본문, 보기, 수식, 표, 도형, 미주, 답안 공간, 구역, 페이지 흐름은 그대로 보존한다.

단순 문자열 찾기/삭제, 전체 머리말·꼬리말 삭제, 전체 바탕쪽 교체, 문단 Backspace/Delete, 전역 조판부호 삭제로 구현하지 않는다.

## 2. 한글 구조상 위험

공식 한컴 문서에 따르면 머리말·꼬리말에는 글자뿐 아니라 그림·표·그리기 개체와 쪽번호를 넣을 수 있고 한 문서에 여러 개가 존재할 수 있다. 마지막 control이 실제 출력에 적용될 수 있으며 시작 페이지, 홀수/짝수/양쪽 범위도 다르다.

쪽번호는 최소 다음 경로에 존재할 수 있다.

- 전용 `쪽번호 위치` control
- 머리말·꼬리말 안의 자동 쪽번호 필드
- 바탕쪽 text box 안의 쪽번호 필드
- 인쇄 전용 자동 머리말/꼬리말 설정
- 숫자가 image나 일반 text로 굳어진 비정형 footer

`쪽번호 감추기`는 전용 쪽번호에는 적용되지만 머리말·꼬리말·바탕쪽에 삽입한 번호까지 제거하지 않는다. 한컴 control character 16은 머리말/꼬리말, 18은 자동 번호, 21은 번호 감추기/번호 위치 범주다. 표·그림은 control character 11이므로 인접 control을 잘못 삭제하면 타이틀 표나 본문 개체가 함께 사라질 수 있다.

공식 근거:

- https://help.hancom.com/hoffice100/en-US/Hwp/format/header/header.htm
- https://help.hancom.com/hoffice100/en-US/Hwp/format/pagenumber.htm
- https://help.hancom.com/hoffice/multi/en_us/hwp/format/hide.htm
- https://help.hancom.com/hoffice100/en-US/Hwp/edit/erase_code.htm
- https://developer.hancom.com/en-us/webhwp/devguide/ctrlcode/properties/ctrlch
- https://cdn.hancom.com/link/docs/한글문서파일형식3.0_HWPML_revision1.2.pdf

## 3. 지원 범위와 fail-closed

### 지원 후보

- HWP/HWPX의 header/footer/master-page text, table, picture, text box 조합
- 구역별/홀수/짝수/양쪽/첫 페이지 예외
- 전용 쪽번호 위치와 header/footer/master-page의 동적 쪽번호
- 기존 바탕쪽에 새 watermark object 병합

### 자동 처리 금지/검토 필요

- 비밀번호·암호화·손상 문서
- 기존 학원명이 image에 합쳐져 있고 제거 영역을 확정할 수 없는 경우
- 일반 본문 상단 도형과 타이틀을 구분할 수 없는 경우
- footer의 일반 숫자와 실제 쪽번호를 구분할 수 없는 경우
- 매크로·외부 링크·OLE·연결 그림이 있는 문서
- 여러 master/header가 겹쳐 실제 출력 control을 확정하지 못한 경우

불확실한 파일은 원본을 건드리지 않고 `대상 확인 필요`로 멈춘다. 사용자가 preview에서 정확한 제목·쪽번호 후보를 선택한 뒤에만 진행한다.

## 4. 데이터 계약

### BrandRewriteRequest

- tenant_id, document_id, source_artifact_id, source_sha256
- brand_template_id/version, academy_name, logo_asset_id/hash
- title_policy: `AUTO_CONFIDENT | USER_CONFIRMED`
- watermark: opacity, scale, rotation, pages(`ALL` 기본)
- remove_page_numbers: true/false
- confirmed_candidate_ids
- idempotency_key, requested_by, base_revision

### BrandStructureManifest

- source format/version, section/page count
- control inventory: ID, CtrlCh, section, page range, layer, path, bbox, type
- headers/footers: start page, odd/even/both, nested table/picture/text/fields
- master pages and first-page hide rules
- page-number mechanisms and counts
- title candidates: text, image, table cell, text box, body-top anchor
- candidate confidence/evidence and preview crop
- protected/encrypted/script/external-link flags

### BrandRewritePlan

- operations allowlist: `REPLACE_TEXT_RUNS`, `REPLACE_SELECTED_SHAPE`, `ADD_WATERMARK_SHAPE`, `REMOVE_PAGE_NUM_CONTROL`, `REMOVE_PAGE_NUM_FIELD`, `CLEAR_PRINT_PAGE_TOKEN`
- exact source control path and expected digest per operation
- allowed render-diff masks for header, watermark, footer
- expected before/after inventory and semantic invariants
- plan digest, template digest, scanner/worker version

plan에 없는 control mutation은 실패다.

## 5. 처리 흐름

1. 원본 bytes를 private immutable object로 저장하고 hash를 고정한다.
2. 별도 격리 디렉터리의 복제본만 한컴/HWPX parser로 연다.
3. 모든 구역과 control tree를 census하고 preview page를 만든다.
4. 제목·로고·쪽번호 후보를 학원 관리자에게 보여 준다.
5. confidence가 충분한 자동 계획 또는 사용자가 확정한 계획을 생성한다.
6. 복제본에서 exact control path만 변경한다.
7. 실제 한컴 Open→SaveAs→reopen→PDF render를 수행한다.
8. 구조 diff와 masked page render diff를 통과한 artifact만 final로 승격한다.
9. 원본, 계획, 출력, proof, 변경 전후 preview를 같은 revision lineage에 보존한다.

## 6. 제목 교체 규칙

- 기존 학원명 문자열을 본문 전체에서 replace하지 않는다.
- header/footer/master/body-top 후보를 구역·페이지 범위별로 구분한다.
- 표+그림+텍스트 조합이면 선택한 text run 또는 cell만 바꾸고 표/그림/section control을 유지한다.
- 제목이 image에 합쳐졌으면 사용자가 확정한 image/title group만 새 브랜드 composite로 교체한다.
- 새 제목은 기존 block bbox와 font fallback을 기준으로 overflow를 검사한다.
- 다른 학교명, 시험명, 학년, 과목 등 본문 metadata는 별도 명시가 없으면 바꾸지 않는다.
- first/odd/even/both header variants 모두 preview하고 누락·중복을 검사한다.

## 7. 워터마크 규칙

- 현재 학원 소유의 검증된 PNG/JPEG asset만 사용한다. 임의 SVG/script/외부 URL은 금지한다.
- 기본은 종이 중앙, behind-text, 비율 유지, 회전 0도, opacity 8–12%, 페이지 폭 30–40% 이내다.
- 기존 master page를 삭제하지 않고 watermark object만 병합한다.
- section마다 master/header 상속과 첫 페이지 숨김 정책을 확인해 `ALL` 요청이면 실제 모든 페이지에 1개씩 보이게 한다.
- 문제·수식·도형 가독성 대비가 기준 아래면 opacity/scale을 자동 낮추거나 검토를 요구한다.
- 기존 watermark가 있으면 중복 삽입하지 않고 제거/교체 대상을 명시한다.

## 8. 쪽번호 제거 규칙

- 전용 Page Number Position control을 exact control deletion 또는 `None`으로 처리한다.
- header/footer/master page 내부의 page-number auto field만 제거한다. 주변 text, table, logo, 연락처는 유지한다.
- print-only automatic header/footer의 `^p`, `^P` token을 inventory하고 선택적으로 비운다.
- section별 숨김 control과 번호 시작/새 번호 control을 무작정 삭제하지 않는다. 최종 visible 번호가 없어졌는지 render로 확인한다.
- image 또는 일반 숫자 쪽번호는 자동 삭제하지 않고 page 반복성+bbox 근거와 사용자 확인이 필요하다.

## 9. 불변 조건과 proof

### 구조 불변

- 원본 bytes/hash 불변.
- 본문 text semantic hash 동일.
- 문제/보기/배점/수식 AST/표 cell·merge/도형 관계/미주 내용·anchor count 동일.
- section/page setup/column/page count 동일. 제목 길이 때문에 page count가 바뀌면 실패.
- 허용 plan 밖의 control count/path/digest 변화 0건.
- footer의 쪽번호 이외 text/object 변화 0건.

### 브랜드 결과

- 모든 대상 header variant에 새 학원명이 보이고 old academy title은 대상 영역에서 0건.
- 요청한 페이지에 watermark 1개, 중복 0, 중앙/크기/opacity/z-order 기준 통과.
- 모든 page-number mechanism이 제거되고 실제 PDF/HWP 렌더 하단에 번호가 보이지 않음.

### 실제 파일

- HWP/HWPX Open 성공, HWP SaveAs 성공, 재열기 성공, PDF render 성공.
- title/watermark/footer 허용 mask 밖의 page render diff가 threshold 이내.
- proof는 source/output hash, control manifest, plan digest, worker/HWP/font version, page images를 포함한다.

하나라도 실패하면 최종 다운로드를 차단하고 원본 또는 직전 artifact를 정상 파일처럼 대체 제공하지 않는다.

## 10. 사용자 화면

### Step 1 — 기존 한글 파일 분석

- 파일명, HWP 버전, page/section 수, 보호/암호 상태.
- `머리말·바탕쪽·본문 상단에서 제목 후보를 찾는 중`처럼 구조 분석 단계를 보여 준다.

### Step 2 — 바꿀 요소 확인

- 각 후보의 실제 page crop과 `머리말/바탕쪽/본문`, 적용 페이지, confidence를 표시한다.
- 복잡한 table/image title은 한 block으로 preview하며 사용자가 선택·해제할 수 있다.
- 쪽번호 mechanism별 candidate와 함께 제거 후 유지될 footer preview를 보여 준다.

### Step 3 — 학원 브랜드 적용

- 저장된 academy name/logo template 선택.
- watermark 크기·농도 최소 옵션과 `모든 페이지` 기본값.
- 변경 전/후 overlay와 페이지 navigation.

### Step 4 — 검사와 다운로드

- `본문 변경 없음`, `표/수식/미주 동일`, `쪽수 동일`, `쪽번호 제거`, `워터마크 전체 페이지`, `한컴 재열기`를 별도 상태로 표시한다.
- 실패 위치로 바로 이동하고 재시도/대상 다시 선택을 제공한다.
- 원본 다운로드와 새 artifact를 분리하며 원본은 항상 보존한다.

## 11. 구현 경계

제안 모듈:

- `backend/rebranding/models.py`
- `backend/rebranding/scanner.py`
- `backend/rebranding/planner.py`
- `backend/rebranding/hwpx_mutator.py`
- `backend/rebranding/hwp_worker_operation.py`
- `backend/rebranding/proof.py`
- `backend/tests/test_hwp_rebranding.py`
- `frontend/app/.../rebrand/page.tsx`

Windows COM 작업은 기존 worker의 `operation_kind=REBRAND_HWP`로 직렬화하고 timeout 시 Python process뿐 아니라 해당 작업이 만든 Hwp descendant까지 종료·recycle한다. 작업 시작 전후 Hwp process inventory를 비교한다. 이번 로컬 조사에서 복제 HWP의 COM 변환이 60초 안에 끝나지 않고 Hwp process가 남았으며, 이전 worker 실행에서 남은 것으로 보이는 Hwp.exe 26개도 관측됐다(2026-09-19 13시 기준, 일괄 종료는 수행하지 않음). 이 경로를 성공으로 간주하지 않고 timeout/process-leak fixture로 사용한다. 원본 파일은 수정되지 않았다.

## 12. 필수 fixture

- plain header text
- header table + logo picture + title text
- title이 하나의 image에 합쳐진 문서
- master-page text box/image title
- body top anchored title shape
- first page/odd/even/both header variants
- 2개 이상 section과 서로 다른 page setup
- 전용 page number, header/footer field, master-page field, print header/footer, literal/image number
- 기존 watermark 0/1/다수
- title control 바로 옆 section break/table/endnote/shape
- endnote·equation·table·drawing이 많은 시험지
- HWP 2014/2020/HWPX, 손상·암호·보호 문서
- macro/OLE/external linked image

## 13. 인수 조건

1. 제목 table/image가 있는 fixture에서 선택 block 밖 object 삭제 0건.
2. 5개 page-number mechanism 각각 제거, 다른 footer 내용 보존.
3. 3개 section과 odd/even/first-page 조합에서 academy title·watermark 누락/중복 0건.
4. 본문·문항·표·수식·도형·미주 semantic/object diff 0건.
5. 페이지 수와 문제 시작 위치 변화 0건.
6. actual HWP reopen/PDF render와 masked visual diff 통과.
7. timeout/crash 시 원본 불변, final artifact 없음, Hwp descendant leak 0건.
8. tenant B가 tenant A logo/source/preview/artifact를 조회하지 못함.
9. 사용자 확인 전 mutation 0건, 취소 시 artifact/revision 생성 0건.

이 기능은 `기존 파일에 브랜드를 덧씌우는 편집`이며 원문 복원 정확도와 별도 operation/revision으로 기록한다.
