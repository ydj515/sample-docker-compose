# 실습 권장 순서

[문서 안내](../README.md) · [Compose 선택](COMPOSE.md) · [구현 상태](../POLICY-ROADMAP.md)

권장: single에서 기본 동작과 정책을 익힌 뒤 HA, 연결 보안, OAuth 통합, 갱신·장애 순서로 진행합니다.
이유: 먼저 요청·정책의 정상 동작을 확인하면 이후 오류가 분산, 인증서, 토큰 중 어디에서 발생했는지 구분하기 쉽습니다.
트레이드오프: HA나 인증 실습에 바로 들어가는 것보다 선행 실습이 늘어납니다.
전환 조건: single의 MCP smoke test와 복합 정책 테스트를 이미 통과했다면 아래 5번 HA 실습부터 시작해도 됩니다. 단, 이후 실습의 선행 조건은 각각 충족해야 합니다.
가정: Docker Compose를 사용할 수 있고, 이 저장소의 agentgateway 실습은 처음 진행합니다.

아래 번호는 학습 순서입니다. 로드맵의 0~8단계는 구현 기록 번호이므로 서로 다릅니다.
실행 명령은 연결된 문서를 사용하고, 설정과 추가 Compose 조합은 [선택 안내](COMPOSE.md)에서 확인합니다.

## 기본 동작부터 통합 인증까지

| 순서 | 실습 | 먼저 확인할 것 | 다음으로 넘어갈 기준 |
| --- | --- | --- | --- |
| 1 | [single 기본 실행](../single/README.md) | Docker Compose, 데이터 디렉터리, UID/GID | `smoke-test.py`의 초기화·도구 조회·echo/add·잘못된 입력 검사 통과 |
| 2 | [기본·복합 정책](../shared/POLICIES.md) | 1번 MCP 정상 호출 | `test-policies.py`, `test-multi-policies.py`로 도구 권한·제한·refill 복구 확인 |
| 3 | [조건부 선택](POLICY-ORDER.md) → [적용 단계](POLICY-STAGES.md) → [API Key](API-KEY.md) | 2번 복합 정책과 요청 제한 이해 | 각 문서의 테스트 통과; 첫 일치 정책·대상별 대체·401과 도구 오류의 차이 확인 |
| 4 | [Timeout·Retry](RESILIENCE.md) → [요청 처리](REQUEST-PROCESSING.md) | 1번 기본 실행; HTTP 실험은 UI 포트 사용 | 재시도 횟수·timeout·변환 검사 통과; 미러 빈 본문은 성공적 복제가 아닌 제한 재현으로 확인 |
| 5 | [HA 기본·장애 전환](../ha/README.md) → [HA 복합 정책](../shared/POLICIES.md) | single에서 1~2번 통과 | HA smoke, 양방향 Gateway 중단·복구, 복합 정책 테스트 통과; 로컬 제한이 인스턴스별임을 확인 |
| 6 | [전역 Rate Limit](GLOBAL-RATELIMIT.md) | 5번 HA와 로컬 카운터 구분 | 두 Gateway의 HTTP·MCP 합산 한도 및 refill 확인; 이후 `--lifecycle`로 장애·재시작 검사 |
| 7 | [HTTP·HTTPS](TLS.md) → [mTLS·갱신](MTLS.md) | 기본 single/HA 호출 정상; 문서에 따라 CA·인증서 생성 | HTTP/HTTPS 네 조합, 잘못된 인증서 거부, mTLS 호출, v1→v2 전환·롤백 확인 |
| 8 | [외부 인가](EXTAUTHZ.md) | 3번 API Key·도구 권한 | HTTP·MCP 허용/거부와 인가 서비스 장애 차단 확인. TLS/mTLS와 분리해 실행 |
| 9 | [OAuth / OIDC](OIDC.md) | 기본 호출과 도구 권한 이해; 단독 realm 준비 | Client Credentials·PKCE 로그인·역할·무효/만료 토큰 검사 통과 |
| 10 | [OAuth+mTLS 비교](../shared/AUTH-COMPARISON.md) | 7번 mTLS와 9번 OAuth를 각각 통과; 유효한 인증서·통합 realm 준비 | 정상 인증서+토큰 호출, 인증서/토큰 실패 조합, 단독 샘플 전환 검증 통과 |
| 11 | [갱신·회전·실패](../shared/AUTH-LIFECYCLE.md) | 10번 통합 설정 정상; 복원할 인증서 세대 확보 | 아래의 장애 실습 순서로 진행하고 복원 후 복합 정책 테스트 통과 |

3~4번은 single에서 먼저 실행합니다. 인스턴스별 차이도 확인하려면 5번 완료 후 각 문서의 HA 명령으로 반복합니다.
7~11번 역시 single을 먼저 확인하고 HA 직접 두 경로·Nginx 경로를 검증합니다. HA 직접 호출만으로 Nginx 경유 검증을 대신하지 않습니다.

## 갱신·장애 실습의 내부 순서

11번은 한꺼번에 실행하지 않고 다음 순서로 확인합니다. 명령은 [갱신·회전 문서](../shared/AUTH-LIFECYCLE.md)에 있습니다.

1. **인증서 사전 검사:** 정상 세대 검사 후 키 불일치·다른 CA·만료·CA 수명 부족의 거부를 확인합니다.
2. **인증서 실제 실패 주입:** `--runtime --variant oidc-mtls`로 TLS 실패 후 정상 세대 복원과 fingerprint를 확인합니다. 컨테이너 재생성으로 중단이 발생합니다.
3. **토큰 갱신·로그아웃:** OAuth 단독과 통합에서 `--refresh`를 실행합니다. refresh 거부와 기존 access token의 즉시 폐기 여부를 구분합니다.
4. **JWKS 회전·장애:** mTLS 인증서를 준비한 상태에서 별도 fixture로 전환합니다. A→A+B→B, JWKS 장애, 복구를 관찰하고 자동 반영과 재시작 복구를 구분합니다.

JWKS의 기존 기록은 복구 후 60초 동안 자동 반영을 관찰하지 못한 결과입니다. 이를 자동 복구 성공으로 판정하지 않습니다.
이전 refresh token 재사용 허용도 현재 샘플의 관찰 결과이며, 일회용 refresh token 회전을 구현한 증거가 아닙니다.

## 별도로 진행할 A2A

[Mock A2A](../shared/A2A.md)는 3번 API Key 이후 진행할 수 있습니다. HA 비교는 5번 이후 실행합니다.
Agent Card 재작성·동기 메시지·키 인증·로컬 제한을 확인한 뒤 기존 복합 정책으로 복원합니다.
A2A는 같은 Gateway의 MCP 설정을 대체하므로 MCP 실습과 전환 실행합니다.
실제 LLM 모델 라우팅·guardrail·토큰/비용 정책은 이 경로에 포함하지 않으며 로드맵의 보류 상태를 유지합니다.

## 매 실습을 마칠 때

1. 해당 실습의 테스트로 결과를 확인합니다. Compose 기동 성공만으로 통과 처리하지 않습니다.
2. 문서의 복원 명령으로 설정을 전환하고 보조 서비스를 정지합니다. 키·인증서·DB volume은 보존합니다.
3. 복원한 설정에 맞춰 검사합니다. `config.yaml`은 `smoke-test.py`, `config-multi-policies.yaml`은 `test-multi-policies.py`를 사용합니다.
4. 다음 실습의 환경변수와 준비 자료를 확인합니다. 상세 방법은 [전환·중지·복원](COMPOSE.md#전환중지복원)을 따릅니다.

- 제약: 기존 실행 기록은 v1.6.0의 로컬 관찰이며, 새 실행의 결과는 직접 확인해야 합니다.
- 위험: 장애 전환·lifecycle·인증서 갱신 테스트는 서비스를 중지하거나 재생성합니다. 진행 중인 다른 실습 요청을 끊을 수 있습니다.
- 예외: 실패 또는 강제 종료 후에는 문서의 복원 절차를 먼저 수행하고 다음 실습으로 넘어갑니다.
