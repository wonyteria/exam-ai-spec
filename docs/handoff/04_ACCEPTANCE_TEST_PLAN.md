# 인수 테스트와 출시 증거 계획

문서 상태: **Devin 구현·검증용 제안 명세. 아래 테스트를 이번 문서 작성에서 실행하거나 통과한 것이 아니다.**

대상: 여러 학원이 웹으로 이용하는 중앙 SaaS. 플랫폼이 AI 처리와 한글 변환을 제공한다. 학원 PC에 Codex·Windows 변환기를 설치하도록 요구하지 않는다. Codex 구독은 개발·검증에만 사용하고 운영 추론 인증으로 재사용하지 않는다. Gemini는 기본 제공자·자동 대체 제공자에서 제외한다. 운영 AI 공급자·비용·데이터 전송 정책이 승인되기 전에는 격리된 fixture와 mock만 사용한다.

이 계획은 [제품 요구사항](./01_PRODUCT_REQUIREMENTS.md), [설계 계약](./02_ARCHITECTURE_CONTRACTS.md), [페이지·팝업 명세](./03_PAGE_UX_SPEC.md)의 행동을 검증한다. 요구사항과 AT ID의 최종 연결은 [TRACEABILITY.csv](./TRACEABILITY.csv)를 따른다. `요구영역`은 상호 대조용이며 별도의 요구사항 ID가 아니다.

## 1. 판정 원칙과 현재 기준

- 성공한 빌드, 테스트 개수, AI 두 회차의 동일 답, HTTP 200, 파일 열기 성공만으로 최종 시험지 적합성을 선언하지 않는다.
- 검증 단위는 `(tenant_id, document_id, revision_id, template_version, renderer_version, format, artifact_hash)`다. AI 추출·정답 검증에는 모델·prompt·schema·source hash도 남긴다. 증거는 해당 버전에만 유효하다.
- 검사 상태 `NOT_RUN/RUNNING/PASSED/FAILED/UNAVAILABLE`을 구분한다. 실행되지 않은 검사는 PASSED가 아니다. 중요한 이슈의 면제는 최종 출고 허용 사유가 될 수 없다.
- 먼저 내용 검증, 다음 내부 초안 생성, 그다음 실제 파일 검증, 마지막으로 해당 형식의 최종 출고를 허용한다. 파일을 생성하려면 이미 파일 검증이 끝나야 하는 순환 조건을 만들지 않는다.
- 최종 출고는 요청 형식별 판정이다. V1 정식 출시 자격은 제품이 약속한 HWPX/HWP/PDF 전체의 실검증 성공을 요구하지만 개별 작업 장애에서는 검증에 실패한 형식만 다운로드를 차단한다. HWP 변환기 장애는 HWP 최종 출고를 차단한다. 별도 검증을 완료한 HWPX/PDF까지 자동 실패시키거나, 반대로 HWPX 성공을 HWP 성공으로 복제하지 않는다.
- 원본의 인쇄 문제와 사용자의 최신 서식 요구가 기준이다. 사람 HWP와 기존 Golden은 무조건적인 정답 데이터가 아니다. RESTORE 중 인쇄 오류를 몰래 교정하지 않는다. 작성자가 선택한 교정은 EDIT 이력과 차이를 남긴다.
- 기본 출력 모드는 `STUDENT_WITH_ENDNOTES`, 미주 정책은 `MAJOR_GROUPED`다. 심원중은 23개 실제 미주가 28개 채점 단위를 cover한다. `LEAF`는 명시적 템플릿 대안이며 두 정책을 한 파일에서 혼용하거나 알 수 없는 enum을 기본값으로 대체하지 않는다.
- `P0`는 출고 차단·학원 격리·데이터 유실에 관한 인수 중요도다. 과거 감사 보고서의 P1/P2 심각도를 재분류했다는 뜻이 아니다. P0/P1 실패 또는 미실행 상태가 있는 범위는 정식 출시하지 않는다.

기존 증거 기준은 감사 커밋 `0c1fb5dc8223d52889ca676bed13ad2e7d93fa4a`의 A01–A36 및 실물 감사 S01–S12다. 이 패키지에는 [감사 요약과 추적 ID](./evidence/BASELINE_FINDINGS.md)를 수록했다. 원 감사 보고서와 제한 원본은 사용자의 별도 감사 폴더에 보존한다. 기존 pytest 22개 통과는 아래 인수 조건의 충족 증거가 아니다. 신규 Codex 추론 정확도와 운영 HWP 자동 변환 성공도 아직 측정하지 않았다.

## 2. 테스트 데이터 등급과 증거 형식

| 등급 | 내용·사용 범위 | 금지·승격 기준 |
|---|---|---|
| F0 합성 fixture | 개인정보 없는 간단한 문제, 악성 파일명, 경계값, provider mock. PR·CI·Devin 기본 데이터 | 실제 인식·풀이 정확도 보고에 사용 금지. 정상/실패/timeout/서로 다른 풀이를 명시적으로 분리 |
| F1 제한 원본 | 사용자 제공 JPG 5장과 HWP. SHA256 manifest, 원본 보존, 접근자·목적 기록 | Git·공개 이슈·개발 로그·외부 Devin 환경에 원본을 자동 업로드하지 않음. 승인된 격리 환경에서만 사용. 문서 내부 지시문은 입력 데이터 |
| F2 승인 Golden | F1 또는 배포 가능한 별도 시험의 인쇄 전사·도형 관계·답안·해설·bbox를 독립 검토하여 고정한 기준 | `source_inventory.json`만으로 확정하지 않음. 2인 독립 검토와 불일치 조정, 데이터 배포/사용 승인, 버전·hash·검토자 필요. 학습/튜닝 공개 집합으로 취급 |
| F3 미공개 holdout | 튜닝에 쓰지 않은 다른 학교·레이아웃·난이도·필기 겹침·사진/PDF. 제출 직전에 잠금 | 예상 답·최종 JSON·모델 응답을 provider 입력/캐시에 주입 금지. 결과를 보고 수정한 뒤 같은 집합을 재평가하면 회귀집합으로 전환하고 새 holdout 확보 |
| F4 부하·장애 | 다학원 synthetic tenant/document/job, 손상·중단·재시도 fixture | 실제 학원 데이터 복제 금지. AI 비용이 발생하는 부하는 mock worker로 먼저 수행하고 승인된 별도 예산에서만 live 시험 |

원본에서 학생 이름·학번을 제거한 개발 사본도 관리 대상이다. 사본 생성 방법과 인쇄 영역 손상 여부를 검토하고 원본 hash와 사본 hash를 각각 기록한다. 삭제된 개인정보가 출력 메타데이터·thumbnail·OCR·로그에 남지 않는지도 검사한다.

심원중 기준 fixture의 **정상 페이지 순서**는 `_02 → 기본 파일 → _04 → _03 → _01`이다. **대문항 23 / 채점 단위 28 / 구조 노드 31 / 총점 100**을 별도 값으로 검증한다. 객관식은 20문항·선택지 100개, Q4 `<보기>`는 별도 진술 3개다. 논술 부모 3개와 자식 8개를 중복 합산하지 않는다. 이 수치는 해당 샘플의 기대값이며 모든 시험에 강제하는 스키마 제약이 아니다.

증거 계층:

| 표기 | 확보할 증거 |
|---|---|
| U | 의미 있는 단위/속성 검사 결과, 실패 입력과 assertion. 구현을 그대로 복제한 계산식만 검사하지 않음 |
| I | API·DB·queue·storage 통합 결과, 상태 전이·revision·hash·권한 판정. 비밀/원문 없는 상관 ID |
| E | 브라우저 E2E 동작, 화면/접근성 tree, API 결과, 저장 후 재조회. 스크린샷만으로 저장 성공 판정 금지 |
| W | 실제 운영 대상 Windows·한글 버전에서 자동 열기/저장/재열기, 객체 목록, 페이지 렌더, 변환 작업 로그 |
| H | 원본 대조 및 수학/학년 적합성 사람 검토, 검토자·일시·범위·불일치 해결 기록 |
| L | 장애/부하 실험의 요청·실행·완료 수, 중복·격리·지연 분포와 큐 상태. 평균값만 보고하지 않음 |

모든 AT 결과에는 AT ID, 코드 commit, 환경/버전, 데이터 등급·fixture hash, 실행 시각, 관측값, PASS/FAIL/BLOCKED/NOT_RUN, 증거 경로를 남긴다. 스크린샷과 원문 로그는 제한 보관하고 보고서에는 마스킹본을 사용한다. mock/cache/live/human 보정 여부를 실행 manifest에 각각 표시한다.

## 3. 인수 테스트 60개

아래의 각 행은 입력·사전조건, 행동, 기대 결과를 갖는 실행 계약이다. 한 행 안에 여러 assertion이 있으면 모두 만족해야 PASS다. UI와 API 양쪽 검사가 명시된 경우 UI만 확인하고 완료 처리하지 않는다.

### A. 로그인·학원 격리·문서함 (AT-001–006)

| ID / 요구사항 / 중요도 / 요구영역 | 입력·사전조건 | 행동 | 합격 assertion | 증거 |
|---|---|---|---|---|
| AT-001 / REQ-01, REQ-23 / P0 / 인증 | F0: 미로그인·만료·해지 세션, 활성 학원 A 계정 | 로그인→새로고침→세션 만료→문서 직접 URL 및 API 호출→재로그인 | 미인증 접근 차단. 존재하지 않는 문서와 타학원 문서의 정보 노출 차이 없음. 재로그인 후 허용 문서로 복귀하고 실패를 빈 문서로 표시하지 않음 | I+E: 응답/리다이렉트·복귀 화면 |
| AT-002 / REQ-01 / P0 / 권한 | F4: A owner/admin/teacher/reviewer, B 사용자, 별도 platformoperator; 02§3의 역할·DocumentAccess grant 행렬 | 업로드/RESTORE확정/solution review/EDIT/복제/EXPORT/삭제/멤버·설정을 UI·직접 API·job submit/retry로 시도 | 배정 reviewer는 READ/RESTORE·solution review만 허용. reviewer의 EDIT·CREATE·artifact 생성·초안/final 다운로드·final 출고는 **403**, EXPORT grant 발급도 거절. 다른 tenant ID는 존재 유출 없는404. teacher는 본인/명시 공유 및 EXPORT grant 적용. platformoperator에 학원 원문 접근 자동 부여 금지 | I+E: 역할×grant×작업 결과표·우회 요청 |
| AT-003 / REQ-01, REQ-24, REQ-25 / P0 / 학원 격리 | A/B 문서·source/crop·revision·job·미주·artifact·cache | B 세션에서 A ID·query·body tenant_id·SSE·다운로드/서명 URL을 치환하여 조회·수정 | 모든 경로 서버에서 거절. 목록·검색·개수·에러·캐시 적중으로 A 존재/내용을 노출하지 않음. signed URL은 계약한 수명·철회 정책을 만족 | I: 전체 자원 경로 권한 시험 |
| AT-004 / REQ-01, REQ-24 / P0 / 세션 변경 | A/B에 속한 계정과 A에서 열린 편집·SSE 화면 | B로 전환하고 A의 늦은 응답 도착, 뒤로가기, 로그아웃 후 이전 탭 재사용 | B 화면에 A 결과 병합 금지. 캐시·선택·다운로드 권한 재평가. 로그아웃/멤버 제거 후 새 요청 차단. 기존 artifact URL의 잔여 유효시간이 정책 이내 | I+E: 지연 응답·탭 기록 |
| AT-005 / REQ-02, REQ-22, REQ-23 / P1 / 문서함·복구 | 진행/검토필요/실패/완료 문서, 같은 제목, 0개 검색 결과; 고정 원본revision·권한별 계정 | 문서함 필터/검색/페이지 이동→문서 복제→owner/admin 보관·해제→브라우저 재시작 | 같은 tenant READ+CREATE 권한에서만 복제. 새 document/revision1과 모든 canonical object ID를 발급·참조 remap; 원본 불변. ACL·artifact·다운로드링크·proof/PASSED는 복사하지 않고 초기grant·NOT_RUN·clone lineage 적용. 보관/해제는 같은 문서ID와 권한 유지, teacher/reviewer 실행403. 목록·검색·상태·job.document_id 복귀 정확, `?doc=` 불필요, 빈목록/오류 구분 | I+E: 복제ID맵·권한·재시작 전후 상태 |
| AT-006 / REQ-22, REQ-23 / P0 / 상태 안내 | 존재하지 않음·삭제됨·접근불가·서버 장애 문서/작업 ID | 문서함 및 업로드/진행/검토/편집/출력의 직접 URL 접근 | 무한 UPLOADED·0문항 성공·빈 문서 위장 금지. 권한에 맞는 안전한 오류와 재시도/문서함 이동 제공. 내부 경로·stack·다른 학원 정보 미노출 | I+E: 상태별 화면 |

### B. 업로드·페이지 준비 (AT-007–012)

| ID / 요구사항 / 중요도 / 요구영역 | 입력·사전조건 | 행동 | 합격 assertion | 증거 |
|---|---|---|---|---|
| AT-007 / REQ-03, REQ-04 / P1 / 업로드 | F0 PNG/JPG, 회전 EXIF, 3쪽 PDF, 여러 PDF+사진 | 파일 선택·드롭→페이지 미리보기→회전/제외/재정렬→시작 | 실제 지원 형식만 안내·처리. PDF 전 페이지 래스터화. 사용자가 확정한 page manifest가 저장/인식/원본 탐색에 동일 적용. EXIF 중복 회전 없음 | I+E: page hash·순서·렌더 |
| AT-008 / REQ-03, REQ-04 / P0 / 업로드 무결성 | 이름은 같고 bytes는 다른 2장, 같은 bytes 반복, page1/2/10 | 중복 파일을 선택하고 순서 변경 후 업로드 | 고유 asset ID로 덮어쓰기 없음. 중복은 명시적 안내/선택. 파일명 정렬이 사용자 순서를 덮지 않음. F2 심원중은 고정 논리 순서와 일치 | I+E: manifest·저장 hash |
| AT-009 / REQ-03, REQ-25 / P0 / 파일 경계 | `../`, 절대/UNC/예약 이름, 잘못된 MIME, 위장 확장자, 손상·암호화 PDF, 제한 초과 파일 | multipart/API로 제출, PDF·이미지 파서 호출 | 서버의 파일·페이지·해상도·압축 해제 제한 적용. 지정 저장 경계 밖 쓰기/외부 fetch/명령 실행 없음. 지원불가 사유와 재입력 경로 표시 | U+I: 악성 corpus·저장경계 검사 |
| AT-010 / REQ-03, REQ-05, REQ-12 / P1 / 입력 품질 | 흐림·잘림·어두움·심한 기울기·빈 페이지와 정상 입력 | 품질 검사 실행→문제 영역 확대→교체/계속 검토 | 불확실 원본의 위치·사유 표시. 정상 인쇄 내용을 임의 보완하여 확정하지 않음. 심각 누락이면 재촬영/검토필요로 남고 자동 최종 출고 금지 | I+E+H: 원본과 경고 대조 |
| AT-011 / REQ-03, REQ-20, REQ-23 / P1 / 업로드 복구 | 업로드 도중 네트워크 중단·일부 파일 실패 | 파일별 재시도/취소, 같은 파일 재선택, 중복 시작 클릭 | 완료 파일 보존, 실패 파일 식별. idempotency로 동일 시작 중복 job 없음. 취소한 페이지가 job에 재유입되지 않음. 재선택 input 정상 동작 | I+E: asset/job 수·재시도 |
| AT-012 / REQ-04, REQ-24 / P0 / 메타데이터·개인정보 | 학교·학년·학기·시험·범위 누락/상충, 이름/학번 손글씨; 검증된 이전revision | 추출 제안 확인→metadata PATCH→현재/과거revision 렌더→로그/thumbnail 검사 | metadata/curriculum/template는 불변 revision snapshot. grade/scope 변경은 CAS와 새revision을 거쳐 curriculum·정답/풀이·논리·산출물 검증 무효화; 표시 header 변경은 style proof 갱신. 과거판본은 최신metadata를 쓰지 않음. 학생 신원정보 최종파일/일반로그 배제, 범위 미확정은 검수완료 금지 | I+E+H: snapshot/hash·무효화·개인정보 검색 |

### C. 작업 진행·재시도·취소 (AT-013–018)

| ID / 요구사항 / 중요도 / 요구영역 | 입력·사전조건 | 행동 | 합격 assertion | 증거 |
|---|---|---|---|---|
| AT-013 / REQ-11, REQ-20, REQ-23 / P0 / 작업 lifecycle | 각 단계 정상/초기화 실패/AI 실패/검토필요 fixture | 파이프라인 실행, 상태·DB 저장·SSE·lease·slot 순서 기록 | durable 저장 전 SUCCEEDED 공개 금지. 검토 이관은 WAITING_REVIEW event+checkpoint/issue/handoff 저장 후 **terminal COMPLETED_REVIEW_HANDOFF**로 닫고 모든lease/동시slot 반납. 문서는 검토필요 유지. 실패 원인/복구 표시, skipped/unavailable을 성공 처리 금지 | I+E: 02§9 사건순서·checkpoint·slot |
| AT-014 / REQ-20, REQ-22, REQ-23 / P1 / 진행 복귀 | 실행job·terminal review handoff, SSE 끊김/중복/역전; 검토 후 새revision | 재접속→검토완료→중복resume→successor 대기 중 또 편집→최신작업 종료 | snapshot/cursor와 최신handoff 복원. 부모job을 되살리지 않고 현재revision 입력의 successor 생성; 같은handoff/revision resume은 동일job. 미시작 낡은successor는 CANCELLED/OBSOLETE_INPUT, handoff SUPERSEDED. 실행중 낡은결과는 이전revision 격리. 성공/실패/취소 체인summary 정확, slot누수 없음 | I+E: 02§9 chain·이벤트·revision |
| AT-015 / REQ-14, REQ-20, REQ-26 / P0 / durable retry | checkpoint 및 provider 요청 전/후 worker kill; attempt당 여러call | worker 재시작·중복메시지·실제 재시도·늦은usage 응답 주입 | checkpoint 기반 재개, 중복canonical/artifact 게시0. 외부요청 **전에 provider_call_id+reservation 영속저장**. attempt당 각call 별ledger, 재호출은 새call ID와 retry lineage. 불명확비용 USAGE_PENDING, 늦은usage/중복응답은 같은call 1회 settlement. 외부 exactly-once 과금 보장 주장 금지 | I+L: crash별 call ledger·checkpoint |
| AT-016 / REQ-14, REQ-20 / P0 / 취소 | 대기 job 및 추론/렌더 중 job; provider 늦은 응답 | 취소 후 늦은 완료 메시지 주입, 다시 새 job 시작 | 취소 acknowledgement와 실제 외부 호출 중단 가능 여부 구분. cancellation token/attempt 검사로 늦은 결과 게시 금지. 새 작업 오염 없음. 이미 발생 비용은 숨기지 않음 | I+E+L: 상태 전이·late write |
| AT-017 / REQ-20, REQ-21 / P0 / 제공자·quota | 운영 profile: provider 미설정·quota 초과·429·timeout·장애 | 작업 시작/재개, 설정된 대기 후 retry | 안전한 대기/재시도/실패 상태, 상한 있는 backoff. 몰래 Gemini·유료 fallback·개인 Codex 인증으로 전환하지 않음. 학원 quota와 플랫폼 상한 구분. 대기 작업이 완료로 표시되지 않음 | I+E: 호출 기록·egress deny 결과 |
| AT-018 / REQ-01, REQ-20, REQ-26 / P0 / 다학원 동시성 | F4: 10학원·50세션·20개 job 제안 부하, WAITING_QUOTA/AUTH/WORKER와 review handoff 포함 | 한 학원이 큐를 채우고 다른 학원이 제출; 30분 부하+worker 재시작·장기 검토대기 | 공정배분·동시성 상한 준수. WAITING_* 및 terminal COMPLETED_REVIEW_HANDOFF는 active lease/tenant slot을 점유하지 않음. 검토 후 현재revision successor만 claim. 종료 후 lost/duplicate job0, 상태/chain 설명 가능, p95/p99·메모리·slot누수 기록 | I+L: 학원별 처리·대기·slot |

### D. 원문·구조·예외 검토 (AT-019–026)

| ID / 요구사항 / 중요도 / 요구영역 | 입력·사전조건 | 행동 | 합격 assertion | 증거 |
|---|---|---|---|---|
| AT-019 / REQ-07 / P0 / 문항 계층 | 승인된 F2 심원중 전사 및 다른 문항수 fixture | 페이지 병합→canonical 구성→목록·검토·출력 집계 | 심원중 23대문항/28채점단위/31노드/100점. 부모 점수 중복 없음. 다른 시험은 그 기준대로 집계. 공유 지문/도형·자식 연결 유지 | U+I+H: 구조 diff·집계 |
| AT-020 / REQ-06, REQ-07, REQ-11 / P0 / 원문 충실도 | F2 원문 전체, Q4 보기 3개, 상충 OCR 후보 | 추출→후보 통합→확정→export 내부 초안 | 번호·지문·보기100개·보기 진술3개·배점·부정어·각/선분 기호 누락·중복 0. 충돌 후보를 각기 독립 정답으로 승인하지 않음. 원문 오타는 issue로 남기고 무단 교정 없음 | I+H: 필드별 source↔canonical diff |
| AT-021 / REQ-05, REQ-06, REQ-11 / P0 / 필기 분리 | 필기가 인쇄선과 겹친 F2 6/9/12/14번; 학생 계산·장문 풀이 | original/clean/판정 마스크 비교 후 복원 | 인쇄선·문자 보존과 필기 제외를 별도 검사. 12번 AD/BC 등 삭제를 발견하면 issue로 차단. 근거 없는 선/값 복원 금지. 픽셀 삭제량을 정확도 지표로 사용하지 않음 | I+H: 겹침별 확대 대조 |
| AT-022 / REQ-05, REQ-08, REQ-10 / P0 / 학생 흔적 배제 | Q10 학생④4와 정답⑤5; Q16 학생②6과 정답③7; Q11/15 학생 스케치 | OCR·도형 추출·풀이 및 최종 문서 생성 | 학생 선택·풀이를 정답/인쇄 조건에 복제하지 않음. 학생 보조 도형 제외. 애매한 해칭/눈금은 원본 위치+판정 상태를 갖고 확인 전 final 차단 | I+H: negative fixture 결과 |
| AT-023 / REQ-03, REQ-06, REQ-12 / P0 / source 추적 | 회전·크롭·PDF 페이지가 있는 문서, 위치가 다른 같은 문구 | 특정 수식/선택지/도형 issue 열기→원본 확대 | 정확한 source asset/page/bbox로 이동. 좌표 변환 일치. 잘못된 페이지·인접 문제 crop을 근거로 확정 불가. 원본 bytes와 기존 crop version 불변 | U+I+E: 좌표 overlay·hash |
| AT-024 / REQ-12, REQ-14 / P0 / 검토 확정 | 수정 가능한 typed issue, 네트워크 실패 및 오래된 revision | 후보 선택/직접 수정→확정→문서 재조회·재시작 | canonical 해당 field가 원자적으로 변경·revision 증가·관련 proof 무효화. 저장 실패 시 issue/입력 유지. 중복 클릭 1변경. 다른 필드 미변경. stale 요청 충돌 안내 | I+E: before/after·revision |
| AT-025 / REQ-11, REQ-12, REQ-23 / P0 / 검토 누락·빈 문서 | 0문항, 누락 번호, 해소되지 않은 도형/논리 issue, issue 카드만 0개 | 검토 페이지 진입→재추출/문항 추가/재검증→출력 접근 | 카드 수 0과 출고 가능을 혼동하지 않음. 누락 위치에서 복구 동작 가능. 모든 필수 검사를 통과한 뒤에만 형식별 출고 가능. 핵심 issue WAIVED는 final 차단 | I+E: gate와 UI 비교 |
| AT-026 / REQ-12, REQ-22 / P1 / 원본 비교 팝업 | 작은 화면·키보드 이용자, 긴 문제 crop·2개 원본 후보 | 원본 전체/부분 확대·이동·원본↔복원 비교→닫기/다시 열기 | 문항/필드/페이지 표시, 비교 배율·위치 관계 명확. focus trap/초기 focus/Esc/복귀 focus 동작. 배경 조작 차단. 저장 필요 없는 확대만으로 원본/문서 변경 없음 | E+H: 키보드·확대·모바일 |

### E. 정답·해설·학년 검증 (AT-027–031)

| ID / 요구사항 / 중요도 / 요구영역 | 입력·사전조건 | 행동 | 합격 assertion | 증거 |
|---|---|---|---|---|
| AT-027 / REQ-10, REQ-11, REQ-27 / P0 / 오답 회귀 | F2 정답: Q2③/Q4③/Q8④/Q9①/Q10⑤/Q14⑤/Q20⑤; 기존 오답7개 fixture | 기존 틀린 답을 canonical/검증 후보에 각각 주입 | 7개 모두 오류/충돌로 검출. 최종 정답 기호뿐 아니라 계산값→선택지 내용→기호의 대응 검사. 기존 expected와 일치한다는 이유로 통과 금지 | U+I+H: 7문항 근거·gate |
| AT-028 / REQ-10, REQ-11, REQ-21, REQ-27 / P0 / 검증 독립성 | 02§7.1 불변policy; seeded응답2개/유효풀이1개/leaf누락/solved=false/충돌/timeout | 각 조합 검사→권한없는 포괄확정→허용된 특정field/leaf 사람판정→정책목록 변조 시도 | 자동판정은 동일input digest의 **유효 독립solve 최소2회**; 다른run ID만 있는 같은cache는 불인정. 누락·quota로 최소회차/필수check 축소 금지. HUMAN_ADJUDICATION은 policy가 허용한 unresolved source/solution 대상만 REVIEW권한·근거·이유·actor/time·digest로 재평가, HUMAN_ADJUDICATED로 표시. 다른미해결·기계적필수검사 면제 금지 | U+I: policy digest·run/slot·adjudication·state |
| AT-029 / REQ-10, REQ-19 / P0 / 풀이 충실도 | 28개 채점 단위, 객관식 답만/논술 자식 일부 누락 fixture | 정답·풀이 coverage 검사, 각 미주 연결 검사 | 28개 모두 정답+이유/풀이 단계·참조가 있음. 부모 풀이 하나로 자식 coverage를 임의 충족하지 않음. 계산·각 이름(CRQ/CRP)·결론·합동조건 모순을 검출 | U+I+H: leaf coverage·해설 검수 |
| AT-030 / REQ-04, REQ-10 / P0 / 학년 적합성 | 중2 교육과정/시험범위 profile, 논술2의 원주각·접현각 무설명 풀이 | 풀이 step→사용 개념 매핑→범위 검사→대안 풀이 검토 | 승인 범위 밖 공식은 자동 완료 불가. 반지름·수직·이등변·내각합/RHS 기반 설명처럼 범위 내 근거를 제시. 범위 미확정은 확인 필요 상태 | I+H: 개념 근거·사람 검토 |
| AT-031 / REQ-08, REQ-09, REQ-10, REQ-27 / P0 / 기준본 독립 검토 | 사람 HWP의 Q13 도형 누락, Q12 배점 누락,10pt수식, 객관식 풀이 없음 | F2 승격 절차와 신규 추출 평가를 수행 | HWP 오류를 Golden에 복제하지 않음. 인쇄 원문·최신 사용자 서식·독립 검산으로 충돌 해결 기록. source_inventory 초안/캐시를 승인 Golden으로 오표시하지 않음 | H+I: 2인 검토·승격 manifest |

### F. 에디터·AI 제안·이력 (AT-032–038)

| ID / 요구사항 / 중요도 / 요구영역 | 입력·사전조건 | 행동 | 합격 assertion | 증거 |
|---|---|---|---|---|
| AT-032 / REQ-07, REQ-13, REQ-14 / P0 / 문항 식별 | 동일 인쇄번호가 있는 섹션, 논술 부모/자식, 재정렬 문서 | 목록 선택→직접 편집/자연어 특정 문항 수정 | immutable ID로 정확한 대상을 변경. display label/position 혼용 없음. 모호한 자연어는 대상 선택이 필요하며 임의 다른 문항 변경 금지 | U+I+E: target ID·diff |
| AT-033 / REQ-13, REQ-14, REQ-22, REQ-23 / P0 / AI 변경 팝업 | 모든 자연어 내용변경 종류: 문구·수식·도형·배점·조건·풀이; 입력B 작성중 | A요청→대상·변경계획·영향확인→제안 diff→명시적 적용/거절 | **모든 자연어 내용변경은 plan-before-apply**, 계획·제안 생성 중 canonical 불변. 계획/승인 밖 변경0, 적용은 원자적 새revision. 새입력B 보존. HUMAN_VERIFIED 자동승격 금지. RESTORE/EDIT 계보 및 검증무효화 표시 | I+E: 계획·승인·diff·history |
| AT-034 / REQ-11, REQ-13, REQ-14 / P0 / 검증 무효화 | 답2의 `1+1` 문제, 공유 부모 지문/도형, 검증 완료 revision | `1+2`로 변경·부모 조건 변경·단순 색상/간격 변경을 각각 수행 | 내용/부모 변경은 해당 답·풀이·도형·출력 proof의 dependency대로 무효화. 이전 답/최종 배지 재사용 금지. 서식 변경은 내용 proof 보존 가능하나 artifact/layout proof 재실행 | U+I+E: invalidation graph 비교 |
| AT-035 / REQ-13, REQ-14, REQ-23 / P0 / 동시 편집 | 사용자/탭2개가 같은 revision, AI 결과 지연 | A 저장 후 B 저장·낡은 AI apply·기존 issue 확정 | optimistic lock으로 충돌 반환, 조용한 마지막 쓰기 덮어쓰기 없음. 사용자 차이/재적용 경로 제공. old revision artifact가 새 revision 결과로 노출되지 않음 | I+E: 충돌 응답·버전 |
| AT-036 / REQ-14 / P0 / undo·버전 | 원본→직접수정→AI수정→템플릿 변경; 재시작 | 이력 조회→특정 변경 undo→redo→다시 내보내기 | 이력 지속. undo/redo는 각각 새 revision이며 과거 원본/문서/artifact 불변. 새 편집 후 기존 redo 적용 가능 여부를 계약대로 제한. 정답·proof를 무조건 되살리지 않고 현재 의존성 재평가. 누가/무엇/왜 변경했는지 보존 | I+E: hash·revision DAG |
| AT-037 / REQ-13, REQ-22, REQ-23 / P1 / 편집 오류 복구 | HTML오류·비JSON·500·timeout·권한 철회 응답 | 편집/적용/검증 버튼 클릭→오류→정상 재시도 | busy 해제, 입력·선택·제안 유지, 사용자 오류/재시도 제공. 미저장 이탈 경고에 저장/버리기/머무름 제공. 저장 실패를 성공 toast로 표시 금지 | E+I: 실패별 화면·DB |
| AT-038 / REQ-08, REQ-13, REQ-14, REQ-22, REQ-25 / P0 / 도형 편집 팝업 | Q3/6/8/16의 직각·동일길이·평행·수직이등분 및 접점 fixture | 원본 나란히 보기→점/라벨/선 종류 수정→검증/적용/취소 | 적용 전 preview만 변경. 관계 제약 위반/라벨 누락 위치 표시. 승인 primitives만 저장, 임의 model SVG/script 실행 금지. 취소 무변경·적용 revision/검증 연계 | U+I+E+H: geometry diff·제약 |

### G. 수식·도형·레이아웃·미주·내보내기 (AT-039–048)

| ID / 요구사항 / 중요도 / 요구영역 | 입력·사전조건 | 행동 | 합격 assertion | 증거 |
|---|---|---|---|---|
| AT-039 / REQ-09, REQ-17, REQ-18 / P0 / 수식 객체 | 본문·보기·도형 라벨·해설에 수학숫자/분수/각/선분/단위 | HWPX/HWP 생성→객체 추출→한글 재열기·편집 | 수학 표현이 실제 편집 가능한 수식 객체. 숫자 it/단위 roman/11pt를 토큰·style과 실제 렌더로 확인. 11pt±0.1pt는 제안 허용값. raw LaTeX/일반텍스트 대체는 final 실패 | I+W+H: 객체 inventory·토큰·렌더 |
| AT-040 / REQ-08, REQ-17, REQ-18 / P0 / 재작도 | F2의 인쇄 도형 전체, Q13, 접점/중점/각/길이/점선 fixture | 구조화 geometry에서 출력→점·선·라벨 편집→원본 비교 | 관계·라벨·선종류·표식 누락/임의 추가 0. 편집 가능한 native/vector 객체. crop·래스터화만으로 재작도 완료 금지. 겹친 label·접점 이탈 없음 | I+W+H: relation coverage·렌더 |
| AT-041 / REQ-15, REQ-16 / P1 / 문제 블록 배치 | 길이 다른 객관식4개, 큰 도형, A4 기본 템플릿 | 2열×열당2개 배치·내부 렌더·한글 재열기 | 열 우선 순서 좌상→좌하→우상→우하. 같은 행(1,3)/(2,4) 시작 y차 ≤0.5pt 제안. 최대 block 높이+padding 적용. 11pt 유지, 겹침/잘림 없음. 용지 변경도 재검증 | I+W+H: 좌표 측정·페이지 이미지 |
| AT-042 / REQ-07, REQ-15 / P0 / overflow·논술 공간 | 장문/긴 선택지/큰 도형·논술 부모3+자식8; 줄 없는 원본 blank; 한쪽 초과group/leaf | 페이지 넘김·템플릿/용지 변경·출력 | 임의 축소/누락 금지. group은 가능하면 함께 두되 큰group은 자식경계, 한쪽 초과leaf는 허용 문단/표 경계로 controlled split, 계속라벨·공유지문/도형 참조 유지. 모든부모/자식을 무조건 같은쪽에 강제하지 않음. 자식별 답안높이 ≥승인기준, blank에 임의줄 금지. 불가능배치 final차단 | I+W+H: split/flow tree·답안 bbox |
| AT-043 / REQ-10, REQ-19 / P0 / 실제 미주 | 02§7.1 policy snapshot, 기본 STUDENT_WITH_ENDNOTES/MAJOR_GROUPED와 명시대안 LEAF, unknown enum | 각정책 출력→미주 앵커대조; unknown/mixed정책 제출; STUDENT_ONLY 별도검사 | MAJOR_GROUPED는 심원중 실제23미주에28leaf coverage, LEAF는28미주. 누락/중복/오연결0, 알수없는enum거절. 기본모드 본문답누출0/미주답+풀이모두존재. STUDENT_ONLY artifact는 미주0을 기대하되 모든leaf content검증 유지; 모드별 expected manifest와 policy digest 고정 | I+W+H: enum·객체·모드별coverage |
| AT-044 / REQ-17, REQ-19 / P0 / 배포 유형·답 노출 | 기본 STUDENT_WITH_ENDNOTES와 STUDENT_ONLY/ANSWER_ONLY/TEACHER를 명시 선택한 fixture | 각 유형 생성→본문/미주/숨김텍스트/첨부·preview 점검 | 기본모드는 본문 답누출0+미주 정답/풀이 coverage. STUDENT_ONLY는 산출물 모든 영역에 답/풀이/학생필기0, content 답검증은 그대로 수행. ANSWER_ONLY는 문항라벨·답/풀이와 정책상 본문생략을 검증. TEACHER는 고정 템플릿과 모드표시. 서로 다른 유형 artifact/cache 혼용 금지 | I+W+H: 모드별 expected manifest·inventory |
| AT-045 / REQ-11, REQ-17, REQ-18 / P0 / 형식별 fail-closed | 02§7.1 필수check×RESTORE/EDIT×output_mode×format; 0문항/ATU없음/NOT_RUN/UNAVAILABLE/criticalWAIVED/손상파일 | 필수check 하나씩 제거·실패·정책digest변조→UI/API final요청; 권한있는 내부proof용생성; 특정human판정 | content필수누락은 모든final차단, format proof실패는 해당format차단. capability없다고 checklist축소 금지. 실제HWP재열기/객체/해시/layout은 human waive불가. 허용source/solution판정만 명시적근거로 재평가. output_mode별검사와download bytes정합성 검사; 내부service proof생성과 reviewer EXPORT권한 분리 | U+I+E: policy별 gate truth table |
| AT-046 / REQ-14, REQ-17, REQ-18 / P0 / 출력 버전 정합성 | rev1 HWPX 생성 뒤 rev2 내용 수정; 같은 이름 재출력 | HWP/PDF/HWPX 생성·다운로드·동시 요청·캐시 hit | 요청 revision/template/mode별 artifact 고정. rev1 HWPX를 rev2 HWP에 사용 금지. manifest/hash와 다운로드 bytes 일치. 재시도 시 동일 작업의 정합성 유지 | I+W+E: lineage·hash 비교 |
| AT-047 / REQ-17, REQ-18 / P0 / 실제 파일·역검증 | 검증된 F2 동일revision, 지원 Windows/한글/폰트 환경 | HWPX→한글 열기→HWP 저장→재열기→PDF 출력; artifact 재추출/렌더 대조 | 3형식에 동일문항/수식/도형/미주/번호/배점. 한글 `?`, 빈 파일, 클리핑/깨진 폰트 0. W 증거 없이는 HWP final PASS 불가. PDF 보존검사는 PDF 자체로 수행 | I+W+H: round-trip·render·semantic diff |
| AT-048 / REQ-11, REQ-17, REQ-21, REQ-27 / P0 / 추론↔출고 완주 | 잠금 F3 holdout, 빈 응답 cache, 승인된 운영 후보 provider·예산 | 웹 업로드→새 추론→필요 검토→편집→검증→3형식 출고 | 모든 단계 provenance/보정량/형식별 proof 확보. 예상 JSON/답 미주입. 처리 불가 입력은 정직하게 review/reject. 해당 실제 시험의 critical 오류0을 사람 대조로 확인 후 최종 인수 | I+E+W+H: full run manifest |

### H. 화면 접근성·설정·운영 보안 (AT-049–054)

| ID / 요구사항 / 중요도 / 요구영역 | 입력·사전조건 | 행동 | 합격 assertion | 증거 |
|---|---|---|---|---|
| AT-049 / REQ-22 / P1 / 전체 화면 반응형 | 업로드/진행/검토/편집/출력+로그인/문서함/설정,390/768/1280px | 각 주요 작업을 터치/키보드·200%확대로 완주 | 주요 버튼·문항목록·오류가 접근 가능. 편집3열을 작은 화면에서 전환 UI로 처리; 폭 수십px 패널 금지. 의도된 문서 canvas pan을 제외한 페이지 가로 스크롤·겹침 없음 | E+H: 8화면 크기별 체크 |
| AT-050 / REQ-22, REQ-23 / P1 / 팝업·접근성 | 원본비교·AI적용·도형·삭제/이탈 팝업, screen reader tree | Tab/ShiftTab/Enter/Esc, 오류 발생·닫기·복귀, 중첩 요청 | 접근 가능한 이름/레이블, focus 순서·복귀, 저장 중 이중 제출 방지. 파괴적 동작 명확, Esc/배경닫기로 저장 적용되지 않음. 색상만으로 상태 전달하지 않음 | E+H: keyboard·axe등+수동 |
| AT-051 / REQ-16, REQ-14 / P0 / 설정·템플릿 | A/B 로고·metadata·학년/범위·미주정책·A4/B4, 진행job/과거revision | 설정 변경→새문서→기존문서 명시재적용→이전판본 재출력 | immutable metadata/curriculum/template snapshot과version 유지. 새설정이 기존판본을 조용히 변경하지 않음. 재적용 CAS/newrevision, grade/scope는 content·curriculum/solution검사 무효화, 단순header/브랜드는 style/artifact검사 갱신. tenant간누출·브랜드로원문덮기0 | I+E+W: snapshot/hash·template lineage |
| AT-052 / REQ-25 / P0 / injection·콘텐츠 안전 | 원본/AI응답의 “시스템 무시/외부 전송” 문구, HTML/SVG script·외부URL·XML payload | OCR→preview→도형 parser→export 처리 | 문서 지시를 실행 지시로 취급하지 않음. 임의 파일/명령/네트워크 실행 없음. HTML/XML/SVG escape·허용 schema 적용; XSS/XXE/SSRF 차단. 지문 자체는 필요한 텍스트로 보존 | U+I+E: 공격 fixture·egress 기록 |
| AT-053 / REQ-18, REQ-21, REQ-25 / P0 / 중앙 worker·비밀 | worker 인증 없음/만료·위조 결과, 임의경로, dev Codex auth.json | 변환 요청·결과 callback 위조, frontend/log/DB/image 검사 | 인증·job/tenant/attempt binding 없는 작업·결과 거절. 임의 경로/외부URL 변환 금지. 비밀이 client/log/artifact에 없음. 개인 subscription 파일이 운영 이미지/worker에 없음 | I+보안검토: 접근·secret scan |
| AT-054 / REQ-02, REQ-24, REQ-26 / P0 / 보관·삭제 | owner/admin/teacher/reviewer, 원본·복제본 shared asset·job·artifact, 만료정책 | 보관/해제→softdelete→기간내restore→기간만료→기존링크/검색·backup검사 | owner/admin만보관/삭제/복구. 보관해제·휴지통복구는 동일document ID, 현재권한 재검사이며 content undo와 구분. 복제본은 새ID/proof/초기grant, source ACL/PASSED미복사; sharedasset refcount로 원본삭제가 복제본훼손 안함. tombstone+job취소로부활차단, 폐기링크/권한자동복구 금지. backup만료한계·원문없는감사기록 명시 | I+E: 상태/ID·refcount·권한·삭제inventory |

### I. 복구·회귀·계측·출시 (AT-055–060)

| ID / 요구사항 / 중요도 / 요구영역 | 입력·사전조건 | 행동 | 합격 assertion | 증거 |
|---|---|---|---|---|
| AT-055 / REQ-24, REQ-26 / P0 / backup·복구 | 격리된 A/B DB/object store/manifest backup, 진행 job·완료 proof | 빈 복구환경에서 restore→문서/다운로드/권한/재시작 검사 | tenant 경계·revision·hash·권한 유지. artifact 누락이면 검증필요로 표시, 성공 위장 없음. 삭제 tombstone 복구 순서 준수. 실제 RPO/RTO 측정 및 승인된 목표 충족 | I+L: 복구 전후 비교·시간 |
| AT-056 / REQ-07, REQ-11, REQ-14, REQ-26, REQ-28 / P0 / 배포·migration | 이전 schema의 논술 부모·자식·history·job 문서 및 backup | dry-run→migration→신규 worker→rollback/recovery 리허설 | 문항/배점/ID/학원 관계 보존. 과거 근거없는 VERIFIED_FINAL은 재검증 필요로 이관. 실패 migration 부분 공개 금지. rollback 제한·복구경로·데이터 손실 여부 기록 | I: migration diff·복구 리허설 |
| AT-057 / REQ-21, REQ-24, REQ-26 / P0 / 관측·회계 | 다학원·attempt당여러provider call·retry·timeout/늦은usage·cache·humanedit·export | 요청전 DB/reservation확인→늦은usage 중복전달→trace/tenant ledger비교 | `(tenant_id,provider_call_id)`로 요청전영속화·call별1회 settlement. provider_response_id없어도 추적가능. timeout은 USAGE_PENDING, 실제retry 새call로합산, 늦은usage누락/이중정산0. 가격표버전/estimate/actual구분. cache≠신규추론, 비밀/원문없는관측 | I+E+L: call·reservation·settlement ledger |
| AT-058 / REQ-10, REQ-11, REQ-21, REQ-27 / P0 / 성능·모델 평가 | 고정 버전의 F2/F3, 승인된 평가 계획과 표본 strata | 최초 blind 평가→오류분류→보정량 측정→신뢰구간 보고 | 아래 측정 프로토콜 준수. 평균만으로 취약층 숨기지 않음. cache 정확도와 live 정확도 분리. 자동통과 오출고를 별도 집계. 미실행 모델/버전에 성능 수치 전이 금지 | H+I+L: 평가표·실행manifest |
| AT-059 / REQ-25, REQ-27 / P0 / CI 회귀 | baseline 재현 A01–A36/S01–S12 중 구현 범위, 모든 code 변경 | lint/typecheck/unit/integration/E2E·static security 검사 | 범위별 결함 재현이 수정 전 실패·수정 후 통과하는 증거. AI 비용·원본 전송 없는 PR CI. 필요한 테스트 skip을 PASS로 세지 않음. 실패/미실행은 release gate에 반영 | U+I+E: CI log·coverage mapping |
| AT-060 / REQ-17, REQ-18, REQ-26, REQ-27, REQ-28 / P0 / 출시 인수 | release candidate hash 고정, 전체 AT evidence, 운영 runbook·지원 행렬 | 인수 담당자가 새 환경에서 설치→F0 smoke→승인 F2/F3→복구·출고 확인 | P0/P1 필수 테스트 PASS, critical 미해결0, 형식별 W proof, 교육과정/원문 검수와 수치 보고 완료. 운영 공급자/한글 라이선스·환경/비용·보관 정책 미확정이면 해당 운영 출시 보류 | I+E+W+H+L: 서명된 release checklist |

## 4. AI 정확도와 사람 검토의 측정 프로토콜

아래 수치는 **현재 성능이 아니라 정식 출시 자격 평가용 제안 목표**다. WP00에서 운영 규모·지원 입력 범위와 함께 고정하고, 목표/데이터를 바꾸면 benchmark_version을 올린다. 목표를 만족시키려고 어려운 사례를 사후 제외하지 않는다. 자동처리의 99.5%/98%/95% 목표는 검토 전 출력의 처리 효율 지표이며, **최종 파일에 남겨도 되는 오류 허용량이 아니다.** 발견된 최종 critical 오류는 0이어야 하며, 불확실한 입력은 review/reject로 막는다.

### 표본과 분모

- 기능 회귀는 F0/F2에서 결정적으로 수행한다. 라이브 정확도는 F3에서만 주장한다. 한 모델의 응답을 다른 회차의 캐시/정답 입력으로 넣으면 독립 검증 실험에서 제외한다.
- 최초 정식 평가의 제안 최소량은 **30개 시험이면서 총 1,000개 이상의 채점 단위**다. 서로 다른 사진 품질·PDF·2열/장문·수학기호·도형/그래프·필기 겹침·논술 계층을 층화한다. 최소량만으로 모든 드문 오류를 배제할 수는 없다.
- 제한 pilot은 WP00에서 명시한 더 작은 표본·학원수·기간으로 수행할 수 있다. 그 경우 “정식 출시 표본 충족”으로 보고하지 않으며, 실제 pilot 최종 파일에서 발견된 critical 오류0·미확인 입력 차단 원칙은 그대로 적용한다.
- 현재 심원중 5장 하나는 필수 회귀 사례이며 범용 정확도 표본이 아니다. 같은 원본의 리사이즈·크롭·회전본은 독립 시험으로 늘려 세지 않는다. 학교/시험 단위로 train/regression/holdout 분할하여 유사 페이지 누출을 막는다.
- 지원 범위 밖 입력은 사전에 정한 사유로 reject하며 reject율에 포함한다. 애매한 실패를 사후에 “지원 범위 밖”으로 재분류하지 않는다. 사람 수정 전 자동 결과와 수정 후 최종 결과를 분리 저장한다.

### 지표와 제안 출시선

| 지표 | 정의·분모 | 제안 목표·판정 |
|---|---|---|
| 문항·선택지·배점 구조 완전성 | 원문 정답 데이터의 필수 노드/필드 대비 누락·중복·오연결 | 최종 출고 집합에서 결함0. 자동처리 초기값은 별도 보고 |
| 인쇄 텍스트 충실도 | 인쇄 토큰별 exact-match, 원문 기호·띄어쓰기의 허용 정규화 목록을 사전 고정 | 자동 결과 99.5% 이상 제안. 숫자/부정어/조건/각·선분 참조는 일반 문자 평균과 별도 critical 집계 |
| 도형 관계 충실도 | 기준 점·선·관계·표식·라벨 대비 누락/오류/불필요 추가 | 자동 결과 관계 단위 98% 이상 제안. 최종 출고는 critical 누락/변형0, 전체 필수 관계 사람 대조 |
| 정답·풀이 적합성 | 28leaf와 같은 채점 단위에서 답·선택지 대응·논리·학년 범위를 모두 만족하는 비율 | 자동 결과 95% 이상 제안. 답만 맞은 비율 별도. 최종 출고는 발견된 오답·잘못된 풀이0 |
| 잘못된 자동 최종통과 | 사후 독립 검수에서 critical 오류가 발견된 자동 통과 채점 단위 / 자동 통과 단위 | 잠금 release corpus에서 0건 필수. 이 관측을 전체 미래 입력에 대한 0% 보증으로 표현 금지 |
| 검토 필요 검출 | critical 오류가 있는 단위 중 review/reject로 차단한 비율 | 오류 유형별 누락·오탐·분모 보고. 신뢰도 점수만으로 임계값 결정 금지 |
| 사람 검토 부담 | exam/leaf별 활동시간, 수정한 leaf/필드 수, review 비율, 재검증 횟수 | 초기에는 관측치와 p50/p95 보고. 억지로 낮춘 review율 대신 최종 정확도 우선. 목표는 pilot 후 별도 고정 |
| 운영 처리시간·원가 | 대기/추론/검토 제외 자동처리/렌더 시간, 실제 호출 및 비용, job별 p50/p95/p99 | 처리량/worker 수/문항수/모델/해상도를 함께 기록. 최종 SLO·월 비용 한도 확정 전 무제한 처리·시간 보장 금지 |

문자·관계·문항·시험 단위 결과와 95% 신뢰구간을 함께 낸다. 한 시험의 문항끼리 상관되므로 시험 단위 cluster bootstrap 등 적절한 방법을 명시한다. 오류 0 관측의 경우 표본 수와 보수적 상한을 같이 보고하며, 1,000개 문항을 독립 1,000시험으로 취급하지 않는다. 결과표에는 수정 전·수정 후, 전체·각 strata, 모델/버전, miss/reject/review 비율을 모두 남긴다.

### 사람 검토 범위

- F2 기준 확정: **전 문항·도형·답·풀이 2인 독립 검토**와 충돌 조정. 학생 답안이나 참고 HWP 답만 보고 결정하지 않는다.
- 출시 후보 F3: **최종 출력 전 문항의 critical 내용**(조건·숫자·부정어·도형 관계·답·해설·누락)을 원본 및 계산과 대조한다. 자동 인식 confidence가 높다는 이유로 제외하지 않는다.
- 한글 출력 정밀 검토: 심원중 전체 페이지와 모든 고위험 템플릿/수식/미주/장문/논술 사례는 전수. 저위험 정상 페이지의 미세 서식은 **시험별 최소 2쪽 또는20% 중 큰 쪽**을 무작위 검토하는 제안을 적용하며, 결함1건 발견 시 해당 유형/버전을 전수 확대한다. 수식 크기·객체 수·좌표·누락 자동 검사는 전 페이지 수행한다.
- pilot 및 출시 인수 표본은 **독립 QA 검토자**가 위 범위로 대조하고 결과를 서명한다. 이는 출시 검증 절차이며 모든 운영 교사에게 매 문제 전수 검토나 별도 승인자를 강제하는 제품 단계가 아니다. 운영 교사는 실제로 배정된 미해결 issue를 확인하고 정책의 필수검사를 충족하면 출고할 수 있다. 자동 출고 범위 확대는 별도 고정한 위험·표본·운영 관측 기준에 따른다.

## 5. 실행 계층과 출시 gate

| Gate | 실행 위치·시점 | 필수 항목 | 실패/부재 처리 |
|---|---|---|---|
| G0 기준·설계 | WP00, 구현 시작 전 | 원본 접근 정책, F2승격 계획, 지원 형식/한글 버전/폰트·provider 후보, 요구사항→AT 매핑, 제안 수치·pilot/정식출시 표본 고정 | 모호한 운영 조건은 결정보드에 표시. fixture 개발은 계속하되 운영 성공을 약속하지 않음 |
| G1 PR CI | 모든 변경 PR, 격리 CI | lint·typecheck·단위·schema·권한·version/gate·정적 보안·관련 회귀. F0/mock만 | 실패하면 merge 금지. relevant AT 연결 없이 “테스트 추가”만으로 완료 금지 |
| G2 통합·웹 | release 후보, staging | 8개 화면·3개 핵심 팝업·역할/tenant/복구·E2E·다학원 부하 | E2E와 API/DB 결과 상충 시 실패. 화면만 정상인 변경은 통과 아님 |
| G3 실제 Windows | renderer/폰트/template/한글 version 변경마다, release 후보 | AT-039–047과 관련 export proof. 서비스 계정·headless 조건·재시작·timeout에서 자동 HWP 실검증 | 개발자 수동 열기만 있으면 자동 변환은 미검증. HWP unavailable 시 HWP 최종 출시 보류 |
| G4 독립 품질 | model/prompt/schema/preprocess 변경마다, 출시 전 | F3 live 평가, F2 회귀, critical 전수 사람 검토, 정밀 서식 표본, 목표/신뢰구간/보정량 | seeded-cache는 정확도 근거가 아님. 이전 model/버전의 성적 재사용 금지 |
| G5 운영 출시 | 고정 release candidate | AT-060, backup restore·관측·지원/장애 대응·비용 상한·라이선스/개인정보 정책·동의된 운영 공급자 | 증거 없는 항목을 문서 약속으로 대체하지 않음. 제한 pilot과 정식 운영 구분 |

실제 Windows 검증은 **운영과 같은 한글 제품/버전·폰트·변환 계정·세션 방식**을 기록한다. 문서 보안 팝업, 첫 실행 팝업, 비정상 종료, 파일 잠금, font 누락, worker 재시작을 포함한다. 파일을 수동으로 열어 문제없었다는 증거는 자동 worker 완료·역검증 증거를 대신하지 못한다.

제안 성능/회복 목표는 개발 kick-off에서 계약한다. 최종 SLO가 미정이면 개발 완료 보고에 실제 측정치를 쓰고 “운영 준비 완료” 판정은 보류한다. 품질 gate는 속도/비용 목표를 맞추기 위해 생략할 수 없다.

## 6. Devin 완료 보고에 반드시 들어갈 내용

1. 작업 범위와 commit, 변경 파일, 연결된 REQ/AT/A/S ID 및 해결 전 재현·해결 후 결과.
2. 신규/수정 테스트의 실행 log, 환경·fixture hash·PASS/FAIL/BLOCKED/NOT_RUN, 생략 사유. 기존 테스트 개수만 나열하지 않음.
3. 새 추론·캐시·mock·사람 수정의 구분과 provider/model/prompt/schema 버전. 운영 AI 비용이 발생한 실행은 승인 범위·사용량을 별도 기록.
4. revision 고정 HWPX/HWP/PDF, 형식별 proof manifest, 실제 한글 객체 inventory·전체 렌더, 원문·수학 검토 기록. 원본 포함 자료는 제한된 저장소로 전달.
5. 동시편집/취소/retry/다학원 격리/복구 테스트 결과와 남은 위험·지원 한계. “완벽” 또는 임의 입력 무오류를 근거 없이 선언하지 않음.
6. 배포/rollback/restore/장애 대응 실행 지침. 필요한 신규 의존성·운영 서비스·라이선스·비용 결정은 숨기지 않고 분리해 제시.

**최종 수락의 의미:** 정해진 지원 범위와 고정된 평가 집합에서 위 계약을 만족했고, 부족한 입력·검증 실패·운영 장애를 성공으로 내보내지 않는다는 것이다. 모든 미래 시험의 오류 가능성이 사라졌다는 의미는 아니다.
