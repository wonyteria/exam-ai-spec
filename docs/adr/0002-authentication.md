# ADR-0002: 인증·테넌트 인가

상태: 인터페이스 고정, 외부 인증 서비스 선택 보류(RG-02)
날짜: 2026-09-19

## 결정

- 인증은 **서버 세션(HTTP-only 쿠키)**을 기본 계약으로 한다. Bearer 토큰도 어댑터로 수용하되 브라우저 경로는 세션이다.
- 인가는 **tenant membership + document action permission** 두 단계로, 모든 API·SSE·crop·download·job·artifact 핸들러가 요청 시점의 membership·role·grant·artifact/revision 상태를 다시 확인한다.
- 자체 비밀번호 해시·로그인 화면을 구현하지 않는다. 외부 인증 서비스(IdP) 선택은 운영 결정(RG-02). 그 전까지는 `AuthContext` 인터페이스 뒤에 dev stub(명시적 개발용 헤더)을 두고, stub은 프로덕션 빌드에서 비활성화한다.
- reviewer는 review/preview만 가능 — artifact 바이너리 다운로드와 release/export 권한 없음.

## 근거

- 학원 PC에 클라이언트 설치 없이 브라우저만 사용한다는 요구와 호환된다.
- IdP 선택이 지연돼도 tenant isolation·권한 테스트(WP01)는 인터페이스 뒤에서 완전히 구현·검증 가능하다.
- dev stub을 production에서 비활성화하지 않으면 인증 우회가 되므로 빌드 플래그로 차단한다.

## 영향

- WP01: `membership`/`role`/`grant` 스키마 + `require_permission` dependency + cross-tenant negative test.
