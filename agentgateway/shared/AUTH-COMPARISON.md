# OAuth·mTLS 개별 샘플과 통합 비교

기존 개별 샘플은 그대로 유지합니다. `config-oidc-mtls.yaml`은 양쪽 MCP 연결의 mTLS와
Gateway의 OAuth access token 검증·도구 인가를 결합한 비교 대상입니다.

| 비교 항목 | OAuth 단독 (`config-oidc.yaml`) | mTLS 단독 (`config-mtls.yaml`) | OAuth+mTLS (`config-oidc-mtls.yaml`) |
| --- | --- | --- | --- |
| 클라이언트→Gateway | 기존 로컬 HTTP | mTLS | mTLS + Bearer token |
| Gateway→MCP | HTTP | mTLS | mTLS |
| 도구 권한 | 토큰 역할로 echo/add 구분 | 신뢰 인증서면 두 도구 허용 | 토큰 역할로 echo/add 구분 |
| 인증 서버 | Keycloak `agentgateway` realm | 없음 | 별도 `agentgateway-mtls` realm |
| 인증서 관리 | 없음 | CA·서버·클라이언트 인증서 | 동일 |
| 토큰 관리 | 발급·만료·검증 키 관리 | 없음 | 동일 |
| 주요 실패 구분 | 401 또는 도구 거부 | TLS 오류 / Nginx 400 / upstream 503 | 인증서 검사 이후 401 또는 도구 거부 |

OAuth 단독의 기존 HTTP 샘플을 OAuth+HTTPS로 표시하지 않습니다. 위 구성은 보안 기능과 실패 양상을
비교하며, 같은 전송 조건에서의 성능 비교는 아닙니다. OAuth+HTTPS 단독 변형은 아직 별도로 추가하지 않았습니다.

## 연결별 검증 주체

```text
single: client -- mTLS + access token --> Gateway -- mTLS --> MCP
HA:     client -- mTLS + access token --> Nginx -- mTLS + access token --> Gateway -- mTLS --> MCP
```

HA에서 클라이언트 인증서는 Nginx가 확인합니다. Gateway가 TLS 연결에서 확인하는 인증서는
Nginx의 `proxy-client` 인증서입니다. 원본 클라이언트 인증서 신원이 Gateway로 자동 전달되는 구성은 아닙니다.
Gateway는 access token의 서명·issuer·audience·만료와 `jwt.demo_role`을 검증합니다.
MCP 서버는 Gateway의 `gateway-client` 인증서를 확인합니다.

**인증서와 토큰을 각각 요구하지만 서로 결합하지 않습니다.** 인증서 바인딩 토큰(RFC 8705),
인증서 주체와 토큰 주체 일치 검사, Keycloak token endpoint의 mTLS client authentication은 포함하지 않습니다.
Keycloak 로그인·토큰 발급 및 내부 JWKS 조회는 기존과 같은 로컬 HTTP 실험입니다.
UI HTTP 포트에는 MCP 인증이 적용되지 않습니다.

## 준비와 실행

각 모드 폴더에서 실행합니다. 기존 인증서 세대를 재사용하거나 없는 경우에만 생성합니다.
이미 있는 인증서는 덮어쓰지 않으며, 만료했다면 앞선 인증서 갱신 절차로 새 세대를 선택합니다.

```bash
# single/ 또는 ha/
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
test -d ./mtls-certs/v1 || python3 ../shared/prepare-mtls.py ./mtls-certs/v1
export MTLS_CERT_DIR=./mtls-certs/v1
python3 ../shared/prepare-oidc.py . --mtls
export AGENTGATEWAY_CONFIG=./config-oidc-mtls.yaml
docker compose -f docker-compose.yml -f compose-mtls.yml -f compose-oidc-mtls.yml config --quiet
docker compose -f docker-compose.yml -f compose-mtls.yml -f compose-oidc-mtls.yml up -d --build --wait

# single/
python3 ../shared/test-oidc.py . --mtls-cert-dir "$MTLS_CERT_DIR" --expiry

# ha/: Gateway 직접 경로 두 개와 Nginx 경유 경로
python3 ../shared/test-oidc.py . \
  https://localhost:14401/mcp/mtls https://localhost:14402/mcp/mtls https://localhost:13443/mcp/mtls \
  --mtls-cert-dir "$MTLS_CERT_DIR" --expiry
```

공개 resource/audience는 single `https://localhost:3443/mcp/mtls`,
HA `https://localhost:13443/mcp/mtls`입니다. HA 직접 경로도 같은 audience를 검증합니다.
issuer는 single `http://localhost:18080/realms/agentgateway-mtls`,
HA `http://localhost:28080/realms/agentgateway-mtls`입니다.
MCP metadata는 `/.well-known/oauth-protected-resource/mcp/mtls`에서 제공하며 조회에도 클라이언트 인증서가 필요합니다.

`data/oidc-mtls` 아래의 자격 증명과 realm import는 권한 600으로 생성합니다.
기존 `data/oidc` 및 `oidc-data`는 보존하고 통합용 `oidc-mtls-data` volume을 사용합니다.
두 샘플은 같은 Compose 서비스·호스트 포트를 사용하므로 **전환 실행**하며 동시에 기동하지 않습니다.
Keycloak import 경로는 tmpfs이고 그 안에 realm 파일 하나를 읽기 전용으로 마운트합니다.
계정·realm·서명 키는 별도 영속 volume에 남습니다. 이미 존재하는 realm은 자동 재수입하지 않습니다.

## 검증할 조합

| 프런트 인증서 | 토큰 | 기대 결과 |
| --- | --- | --- |
| 정상 | calculator | echo·add 허용 |
| 정상 | viewer / OIDC 로그인 사용자 | echo 허용, add 목록 제외 및 호출 거부 |
| 정상 | 없음 / 서명 변조 / 다른 audience | HTTP 401 |
| 정상 | 만료 | 만료 + 61초 후 initialize 401 |
| 없음 / 신뢰하지 않는 CA / backend 전용 인증서 | 없음 / 정상 / 다른 audience | TLS 단계 거부 또는 Nginx 인증서 오류 400 |

추가로 `/mtls-check/good`는 200, `/mtls-check/no-client`와 `/mtls-check/bad-client`는 503을 검사합니다.
이 세 경로는 **mTLS만 요구하는 HTTP 진단 경로**입니다. MCP 도구 경로가 아니며 토큰 검증 대상도 아닙니다.
backend mTLS 실패를 OAuth 실패와 분리해서 확인하기 위한 기존 mTLS 실험 경로를 유지했습니다.

## 개별 샘플 전환과 복원

```bash
# 기존 OAuth 단독으로 전환: 원래 realm과 volume 사용
AGENTGATEWAY_CONFIG=./config-oidc.yaml docker compose -f docker-compose.yml -f compose-oidc.yml up -d --wait
docker compose -f docker-compose.yml -f compose-mtls.yml stop mcp-mtls
python3 ../shared/test-oidc.py .

# 기존 mTLS 단독으로 전환
AGENTGATEWAY_CONFIG=./config-mtls.yaml docker compose -f docker-compose.yml -f compose-mtls.yml up -d --wait
docker compose -f docker-compose.yml -f compose-oidc-mtls.yml stop keycloak
# single: python3 ../shared/test-mtls.py https://localhost:3443 "$MTLS_CERT_DIR"
# ha: python3 ../shared/test-mtls.py https://localhost:13443 "$MTLS_CERT_DIR"

# 실습 후 기존 복합 정책으로 복원
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
docker compose -f docker-compose.yml -f compose-mtls.yml -f compose-oidc-mtls.yml stop keycloak mcp-mtls
unset AGENTGATEWAY_CONFIG MTLS_CERT_DIR
```

- 제약: Keycloak·MCP·Nginx는 단일 인스턴스입니다. 전체 시스템 HA나 운영 배포 예제가 아닙니다. 로그인은 HTTP 프로토콜 수준으로 검증하며 특정 MCP 앱의 인증서·OAuth 동시 지원은 별도 확인해야 합니다.
- 위험: 두 인증 수단의 만료·갱신을 별도로 관리해야 합니다. Keycloak은 기존 로컬 샘플처럼 개발 모드·내장 DB·root 실행이며 운영용 설정이 아닙니다.
- 예외: TLS handshake 오류와 Nginx의 HTTP 400을 같은 OAuth 오류로 처리하지 않습니다. JWT 만료 테스트는 initialize 기준이며 기존 장기 세션의 만료·인증서 폐기·토큰 실시간 폐기는 보장하지 않습니다.

공식 설정 근거: [MCP authorization](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/mcp-authz/),
[Backend TLS](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/backend-tls/).

## 실행 결과 (2026-10-19)

agentgateway v1.6.0 / Keycloak 26.8.0, single·HA 직접 두 경로·HA Nginx 경유에서 다음을 확인했습니다.

- Client Credentials와 OIDC Authorization Code + PKCE 로그인 토큰으로 mTLS MCP 호출 성공.
- viewer는 echo만 표시하고 add 호출은 HTTP 400 / JSON-RPC -32602 `Unknown tool: add`, calculator add 결과는 5.
- 정상 인증서 + 토큰 누락·서명 변조·다른 audience는 401, 만료 + 61초 후 initialize도 401.
- 인증서 없음·다른 CA·backend 전용 인증서 각각에 토큰 없음·정상·다른 audience를 조합한 9가지 요청 모두 프런트에서 차단. 네 경로 총 36가지 거부 조합 확인.
- backend HTTP 진단은 정상 인증서 200, 인증서 누락·잘못된 CA 503.
- UI HTTP 포트 4000·14001·14002의 통합 MCP 경로는 404, HA HTTP 포트 13000에서는 403.
- realm·audience 분리, 준비 스크립트 재실행 시 기존/통합 자격 증명 보존 및 파일 권한 600 확인.

초기 기동에서 import 파일명과 realm 이름 불일치, 이어서 영속 import 디렉터리의 빈 파일을 발견했습니다.
최종 Compose는 올바른 컨테이너 파일명과 tmpfs import 디렉터리로 기동을 통과했습니다.
실패 당시의 볼륨을 삭제하거나 기존 OAuth 데이터를 초기화하지 않았습니다.

통합 검증 후 single/HA에서 OAuth 단독으로 전환해 기존 realm의 로그인·도구 권한 검증을 통과했습니다.
mTLS 단독으로도 전환해 인증서 거부·backend 진단·echo/add 호출·선택 인증서 fingerprint 검증을 통과했습니다.

복합 정책으로 복원한 세 Gateway에서 권한·독립/전체 버킷·refill 회귀 검증을 통과했습니다.
Keycloak·mcp-mtls는 정지하고 기존·통합 realm volume, 자격 증명과 인증서는 보존했습니다.

## 갱신·회전 실패 비교

[인증 수단 갱신·회전·실패 비교](AUTH-LIFECYCLE.md)에 인증서 적용 전 검사와 rollback,
Keycloak refresh grant·logout, JWT 서명 키 겹침·제거·JWKS 장애/복구 실험을 추가했습니다.
실제 Keycloak 토큰 갱신과 테스트 발급자를 사용한 서명 키 회전의 검증 범위를 구분합니다.
