# 최종 인계 명세 독립 검토

판정: **PASS — 개발 인계 명세의 정합성 검토 통과.** 2026-09-19 최초 REVISE에서 제시한 RV-01–08의 수정 내용을 재확인했다. 확인된 미해결 중대 명세 충돌은 없다.

이 판정은 제품 구현 완료, 실제 AI 정확도, 테스트 실행 성공 또는 운영 출시 승인을 뜻하지 않는다. 이번 검토는 문서 대조이며 제품 코드·원본·모델·한글 실행을 수행하지 않았다.

검토 범위는 AUTHORING_BRIEF, REQUIREMENT_INDEX, 01–07 문서이며, 수정 재검토는 01/02/03/04/07과 START_HERE·DEVIN_START_PROMPT를 대상으로 했다. 기존 감사와 실물 감사의 핵심 결론도 대조했다. TRACEABILITY/BACKLOG의 최종 자동 무결성 검사와 ZIP 구성 검사는 통합 담당자의 별도 확인 범위다. 06의 외부 모델 가격/기능 출처는 이번 독립 검토에서 재조회하지 않았다.

| 지적 | 수정 확인 근거 | 결과 |
|---|---|---|
| RV-01 자연어 수정 승인 규칙 | 01 REQ-13, 03 §9.2, 04 AT-033이 모든 자연어 콘텐츠 변경을 제안→명시 적용→새 revision으로 통일. 직접 typed 검토 확정과 구별 | 해소 |
| RV-02 업로드 제한 충돌 | 01 §4와 02 §12가 50MiB/50페이지/총 200MiB/40MP로 일치. byte/pixel 단위와 capability 설정 기준 명시, AT-009에서 서버 제한 검사 | 해소 |
| RV-03 미주 enum 충돌 | 02 §4, 03 §12.1, 07 ADR-08이 MAJOR_GROUPED/LEAF로 통일. AT-043에 unknown enum 거부와 모드별 coverage 명시 | 해소 |
| RV-04 검토 대기 작업의 영구 미종료 | 02 §9에서 WAITING_REVIEW는 event, 부모 job은 terminal COMPLETED_REVIEW_HANDOFF로 종료·lease/slot 반납. ReviewHandoff/successor·중복 resume·낡은 입력·결과 전파 정의. 03 §7, AT-013/014/018에 반영 | 해소 |
| RV-05 필수 검증과 출력 모드 계약 | 02 §6–7.1에 독립 solve 최소 2회, 불변 verification policy, content/format/mode별 check enum과 증거 표 정의. 특정 field/leaf 사람 판정과 기계 증거 면제를 구별. STUDENT_ONLY는 미주 0/답 누출 부재, 통합본은 실제 미주 coverage. ANSWER_ONLY는 02/03 모두 정답+풀이. AT-028/043/045에 대응 | 해소 |
| RV-06 가변 metadata의 판본 오염 | 02 §4–5에서 metadata/curriculum/template snapshot과 digest·무효화 규칙 정의. Document의 검색 metadata는 파생 인덱스. AT-012/051에서 과거 revision 재렌더와 학년/범위 변경 검사 | 해소 |
| RV-07 nullable 공급자 ID에 의존한 비용 정산 | 02 §10.1에서 요청 전 provider_call_id와 reservation 영속화, call별 settlement, 새 실제 호출 ID·retry lineage·USAGE_PENDING 정의. AT-015/057에서 crash·늦은 usage·중복 응답·attempt 내 복수 호출 검증 | 해소 |
| RV-08 복제·문서 생명주기 계약 누락 | 02 §5/11에 clone과 archive/unarchive/delete/restore API·권한·lifecycle_version·tombstone·복구 계약 추가. 복제는 새 canonical ID/권한/NOT_RUN이며 proof·ACL 미복사. 03 §5/팝업 및 AT-005/054에 화면·참조·권한·보존 검증 연결 | 해소 |

추가 정합성 확인:

- reviewer는 배정 검토·미리보기·proof/이력 조회만 가능하며 EDIT/CREATE/EXPORT 및 artifact 생성·다운로드가 금지된다. 02의 서버 권한, 03의 화면, AT-002의 직접 API/job 우회 검사가 일치한다.
- 내용 검사→CONTENT_READY→내부 artifact 생성→해당 bytes의 포맷별 proof→동일 bytes 최종 승격 순서다. content-ready 검사에서 아직 생성하지 않은 artifact proof를 요구하지 않아 순환 의존이 없다.
- HWP 장애의 개별 문서 차단은 형식별로 적용하지만 V1의 3형식 지원 출시에는 실제 3형식 증거를 요구한다. 두 기준을 혼동하지 않는다.
- 사용자 확정인 다학원 웹 전용·중앙 AI/HWP·개발용 Codex·Gemini 기본 제외가 진입 문서까지 유지된다. 수치·모델·인프라 후보는 제안/배포 전 결정으로 구별한다.
- holdout 결과를 보고 수정한 뒤 같은 집합을 쓰면 회귀집합으로 전환하고 새 holdout을 확보하는 규칙이 있다. 캐시 재생·새 추론·사람 보정·실제 한글 증거를 구별한다.

운영 API 계정·예산·자료 처리 승인, 중앙 한글 사용 조건·환경, 승인 Golden·미사용 holdout, 실제 산출물 proof, 백업 복구, 지원 범위와 품질 수치 확정은 계속 출시 차단 조건이다. 명세 검토 PASS로 이 조건을 통과 처리하지 않는다. 후속 의미 변경은 연결된 요구사항·계약·화면·AT를 함께 갱신하고 다시 대조해야 한다.
