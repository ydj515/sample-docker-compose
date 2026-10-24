# 정책 실습 로드맵

구현·검증 기록 기준: 2026-10-18~19, agentgateway v1.6.0. 문서 구조 정리: 2026-10-20. 공식 최신 문서는 갱신될 수 있으므로 실제 샘플 버전의 실행 결과와 구분합니다.
이 문서는 단계별 상태와 검증 범위를 관리합니다. 실행 파일 조합은 [Compose 안내](docs/COMPOSE.md), 최초 기동은 [single](single/README.md) 또는 [HA](ha/README.md)를 참고하세요.
완료 표시는 아래에 연결한 과거 실행 기록 기준이며, 현재 실행 중인 컨테이너 상태를 뜻하지 않습니다.

학습 순서는 [실습 권장 순서](docs/LEARNING-PATH.md)를 따릅니다. 아래 번호는 구현 기록 순서입니다.

## 확인한 규칙

| 구분 | 규칙 | 현재 근거 |
| --- | --- | --- |
| 적용 단계 | 게이트웨이·리스너 → 라우트 → 백엔드, 여러 단계의 정책은 각 단계에서 적용 | 헤더 변환·수정 조합으로 싱글·HA 검증 완료 |
| 같은 단계의 종류별 실행 순서 | YAML 키 작성 순서로 판단하지 않음. 버전별 구현·실행 확인 필요 | 미검증 |
| 조건부 정책 | 위에서부터 첫 일치 항목 하나 적용. 무조건 fallback은 마지막에 최대 1개. 미일치·fallback 없음이면 해당 정책 미실행 | 싱글·HA 두 인스턴스 검증 완료 |
| MCP 대상별 설정 | 지원되는 같은 종류의 대상 정책이 백엔드 공통 정책보다 우선 | requestHeaderModifier 대체를 싱글·HA 검증 완료 |
| Rate limit 복수 항목 | 각 제한을 모두 만족해야 함. 로컬 카운터는 인스턴스별 | 싱글·HA 검증 완료 |
| MCP 권한 복수 규칙 | 규칙 간 OR, 한 규칙 내부의 동시 조건은 && | 싱글·HA 검증 완료 |

MCP 대상에서 지원하는 정책은 backendAuth, backendTLS, requestHeaderModifier입니다.
이를 모든 정책에 적용되는 "하위가 상위를 덮어쓴다"는 규칙으로 일반화하지 않습니다.

## 단계별 작업

| 순서 | 범위 | 완료 조건 | 상태 |
| --- | --- | --- | --- |
| 0 | [기본·복합 정책](shared/POLICIES.md) | 도구 권한, 두 rate limit, CORS, 제한 후 복구 검증 | 완료 |
| 1 | [conditional 선택 순서](docs/POLICY-ORDER.md) | 동시 일치 시 첫 항목, 마지막 fallback, 미일치 시 backend 전달 확인 | 완료 |
| 2 | [적용 단계와 설정 충돌](docs/POLICY-STAGES.md) | gateway/route/backend 실행 흔적, MCP 대상별 헤더 덮어쓰기 검증 | 완료 |
| 3 | [인증과 정책 충돌](docs/API-KEY.md) | API Key 인증과 권한·rate limit 동시 실패 응답·카운터 확인 | 완료 (API Key; JWT는 7D·7F 참고) |
| 4 | [시간 제한·재시도](docs/RESILIENCE.md) | 지연·오류를 주는 테스트 backend로 timeout/retry 검증, 부작용 중복 범위 기록 | 완료 (HTTP route) |
| 5 | [요청 처리](docs/REQUEST-PROCESSING.md) | 헤더 변경, 본문 변환, 경로 재작성, 미러링·장애 주입 검증 | 완료 (HTTP, 미러 본문 미지원 확인) |
| 6 | [HA 전역 rate limit](docs/GLOBAL-RATELIMIT.md) | 외부 Rate Limit gRPC 서비스와 공유 저장소로 인스턴스 간 카운터 검증 | 완료 (Redis, HTTP·MCP) |
| 7 | [연결 보안·외부 인가](docs/TLS.md) | backend 인증/TLS, 외부 인가, MCP OAuth/OIDC 예시 및 의존 서비스 정리 | 완료 (TLS·mTLS·갱신·HTTP 외부 인가·OAuth/OIDC 개별 샘플) |
| 8 | LLM 전용 정책 | 모델 라우팅, guardrails, 토큰·비용 예산; 별도 LLM 환경 확보 후 검증 | 보류 |
| 별도 A2A | [Mock LLM 메시지 교환](shared/A2A.md) | Agent Card 재작성, 동기 메시지, API 키, local rate limit 비교 | 완료 (동기 Message 부분 구현) |

새 라이브러리, 외부 서비스 상태 변경, DB 스키마 변경 등이 필요하면 사용자 지침에 따라 별도 범위를 확인합니다.
미검증 기능을 설정 파일 존재만으로 완료 처리하지 않습니다.


## 7단계 상세

| 단계 | 실습 문서 | 범위 |
| --- | --- | --- |
| 7A | [HTTP·HTTPS](docs/TLS.md) | 클라이언트·백엔드 연결 네 조합, CA·호스트명 실패 |
| 7B | [mTLS·인증서 갱신](docs/MTLS.md) | 상호 인증, 세대 전환·롤백 |
| 7C | [외부 인가](docs/EXTAUTHZ.md) | API Key 역할 기반 HTTP·MCP 인가, 장애 차단 |
| 7D | [OAuth / OIDC](docs/OIDC.md) | Keycloak, Client Credentials, Authorization Code + PKCE |
| 7E | [OAuth+mTLS 비교](shared/AUTH-COMPARISON.md) | 두 인증의 독립 검증, 실패 조합 |
| 7F | [갱신·회전·실패 비교](shared/AUTH-LIFECYCLE.md) | 인증서 실패, refresh/logout, JWKS 캐시·복구 |

7A~7F는 기록된 실습 범위에서 완료했습니다. 각 문서의 미검증 항목과 운영상 한계까지 완료한 것은 아닙니다.

## 남은 범위와 재검증 조건

- 8단계는 별도 LLM 환경 확보 전까지 보류합니다. Mock A2A는 실제 모델 라우팅·guardrail·토큰/비용 예산 검증을 대신하지 않습니다.
- 같은 단계에서 서로 다른 정책 종류의 보편적인 실행 순서는 미검증입니다. 개별 충돌 실험 결과를 전체 정책에 일반화하지 않습니다.
- v1.6.0의 미러 본문 미지원과 JWKS 장애 후 복구 제한은 각각 [요청 처리](docs/REQUEST-PROCESSING.md), [갱신·회전](shared/AUTH-LIFECYCLE.md)에 남깁니다.
- 이미지나 정책을 변경하면 해당 실습의 테스트와 복원 후 회귀 검증을 다시 실행합니다. 기존 기록의 수치를 새 버전 결과로 사용하지 않습니다.
