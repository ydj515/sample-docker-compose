# 7단계 D: OAuth 2.0 / OIDC

[문서 안내](../README.md) · [Compose 선택](COMPOSE.md) · [로드맵](../POLICY-ROADMAP.md)

실행 위치: `agentgateway/single/` 또는 `agentgateway/ha/` (별도 표시 우선). 최초 준비는 각 모드 README를 따릅니다. 검증 기록은 v1.6.0의 과거 실행 결과입니다.

`config-oidc.yaml` + `compose-oidc.yml`로 Keycloak을 함께 실행합니다.
Gateway는 Resource Server 역할이며, 인증 서버의 토큰 발급·사용자 로그인은 Keycloak이 담당합니다.
`provider`를 지정하는 인증 서버 proxy/DCR 방식은 이번 샘플에 포함하지 않습니다.

| 흐름 | 주체 | 검증 내용 |
| --- | --- | --- |
| OAuth Client Credentials | viewer / calculator confidential client | client secret 검증 후 access token 발급 |
| OIDC Authorization Code + PKCE | browser public client + demo-viewer 사용자 | S256, state, nonce, ID token 서명·issuer·audience·만료 검증 |
| MCP 요청 | Gateway | access token 서명·issuer·audience·만료 및 `jwt.demo_role` 권한 |

`viewer` 및 browser 로그인 사용자는 echo만, `calculator`는 echo와 add를 사용할 수 있습니다.
역할은 Keycloak의 샘플 client mapper가 서명한 `demo_role` claim입니다. 요청 헤더의 역할은 신뢰하지 않습니다.
사용자별 역할 관리 예제가 아니라, 각 클라이언트에 고정 역할을 부여하는 최소 예제입니다.
ID token은 로그인 클라이언트가 검증하고, MCP에는 access token을 보냅니다.
비밀번호 grant는 비활성화했으며 테스트는 실제 Authorization Code 교환을 수행합니다.

| 주소 | single | HA |
| --- | --- | --- |
| 공개 issuer | `http://localhost:18080/realms/agentgateway` | `http://localhost:28080/realms/agentgateway` |
| audience / resource | `http://localhost:3000/mcp` | `http://localhost:13000/mcp` |
| Gateway 내부 JWKS | `http://keycloak:8080/realms/agentgateway/protocol/openid-connect/certs` | 동일, Compose 네트워크별 분리 |

공개 issuer와 내부 JWKS 주소를 구분합니다. 컨테이너의 localhost는 호스트가 아니므로
내부 키 조회에는 서비스 DNS를 사용합니다. HA 두 replica는 같은 issuer와 공개 resource를 검증합니다.
MCP 보호 리소스 metadata는 `/.well-known/oauth-protected-resource/mcp`에 있으며,
`authorization_servers`로 Keycloak을 안내합니다. 인증 누락 시 401의 `WWW-Authenticate`도 제공합니다.

### 실행

```bash
# single/ 또는 ha/에서
python3 ../shared/prepare-oidc.py .
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
export AGENTGATEWAY_CONFIG=./config-oidc.yaml
docker compose -f docker-compose.yml -f compose-oidc.yml config --quiet
docker compose -f docker-compose.yml -f compose-oidc.yml up -d --build --wait

# single/에서
python3 ../shared/test-oidc.py . --expiry

# ha/에서: replica별 직접 포트도 검사
docker compose -f docker-compose.yml -f compose-oidc.yml -f compose-auth.yml up -d --wait
python3 ../shared/test-oidc.py . http://127.0.0.1:16001/mcp http://127.0.0.1:16002/mcp http://localhost:13000/mcp --expiry

# 복합 정책 복원, Keycloak 중지. 인증 자료와 DB volume은 보존.
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
docker compose -f docker-compose.yml -f compose-oidc.yml stop keycloak
unset AGENTGATEWAY_CONFIG
```

Keycloak healthcheck가 realm discovery HTTP 200을 확인한 뒤 Gateway가 시작합니다.
테스트는 Python 표준 라이브러리와 실행 중인 mcp-demo의 Node crypto만 사용합니다.
`--expiry`는 60초 수명 토큰에 추가 61초 여유를 두므로 약 2분 더 걸립니다.
이는 만료 후 initialize 거부 검증이며 기존 세션에서의 만료 처리·정확한 만료 경계·clock skew 허용값을 측정하는 테스트는 아닙니다.

### 계정·로그인·저장 데이터

- `prepare-oidc.py`는 `data/oidc/credentials.json`과 realm import JSON을 권한 600으로 생성하고 재실행 시 보존합니다. 비밀값·코드·토큰은 출력하지 않습니다.
- realm의 사용자·client·서명 키 등은 Keycloak의 `oidc-data` volume에 저장됩니다. Gateway 설정은 기존 YAML/SQLite 방식입니다. PostgreSQL 설정 저장 기능을 추가한 것이 아닙니다.
- Keycloak은 이미 있는 realm을 재수입하지 않습니다. 생성 파일을 고쳐 재기동해도 기존 계정/mapper가 변경되지 않습니다. 이 샘플은 초기 import와 재사용만 지원하며 자동 초기화·DB 삭제를 하지 않습니다.
- browser client는 public이며 callback은 `http://127.0.0.1:18765/callback`, scope는 `openid`, PKCE는 S256입니다. 자동 테스트가 redirect를 가로채므로 callback 웹서버는 띄우지 않습니다.
- 로그인은 HTTP form·cookie·redirect 수준으로 검증합니다. 실제 브라우저 UI, 특정 MCP 앱의 자동 로그인, DCR·실시간 폐기는 이 단계에서 검증하지 않았습니다. refresh token·logout과 fixture 기반 JWKS 회전은 후속 7단계 F에서 별도로 다룹니다.
- Keycloak의 localhost secure cookie를 HTTP 테스트에서도 전달하도록 Python cookie policy를 조정했습니다. 테스트 대상과 로그인 form은 localhost/loopback으로 제한합니다. 운영 HTTP 전송 예제로 사용하지 않습니다.

- 제약: 기존 TLS/mTLS·외부 인가·전역 rate limit과 분리한 로컬 HTTP 실험입니다. Keycloak은 digest 고정 26.8.0의 `start-dev` + 내장 DB이며 HA에서도 단일 인스턴스입니다. 운영 인증 서버 HA 구성이 아닙니다.
- 위험: 소유자 전용 import 파일을 읽도록 로컬 Keycloak만 root로 실행합니다. 호스트 포트는 loopback이고 관리자 계정은 생성하지 않습니다. 운영은 TLS, 비루트 실행, 외부 DB와 별도 비밀 관리가 필요합니다. UI 포트에는 이 MCP 인증이 적용되지 않습니다.
- 예외: 서명된 JWT는 일반적으로 로컬 검증되므로 계정 변경이나 logout 즉시 무효화를 보장하지 않습니다. IdP 정지 시 기존 JWKS 캐시로 검증 가능한 범위·키 갱신 장애 동작은 이번 검증에 포함하지 않습니다.

공식 근거: [MCP authentication](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/mcp-authn/),
[MCP authorization](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/mcp-authz/),
[Keycloak containers](https://www.keycloak.org/server/containers).

### 실행 기록 — 7단계 D

2026-10-19, agentgateway v1.6.0 / Keycloak 26.8.0에서 single, HA 두 replica 직접 포트,
HA Nginx 경유 총 네 경로를 검증했습니다.

- Client Credentials 발급, 잘못된 client secret의 401, 로그인 Authorization Code + S256 PKCE를 통과했습니다.
- ID token의 RSA 서명·issuer·audience·nonce·만료를 Node crypto로 검증했고, 변조 서명·잘못된 nonce를 거부했습니다.
- 사용된 code 재사용과 잘못된 PKCE verifier는 각각 HTTP 400으로 거부됐습니다.
- MCP 토큰 누락·잘못된 audience·변조 서명은 401이었고, 누락 응답에 resource metadata 안내가 있었습니다.
- viewer와 OIDC 로그인 사용자는 echo만 보였으며 add 직접 호출은 HTTP 400 / JSON-RPC -32602 `Unknown tool: add`였습니다. calculator add 결과는 5였습니다. 위조 역할 헤더는 권한을 올리지 못했습니다.
- 네 경로 모두 만료 시간 + 61초 뒤 같은 access token으로 initialize하면 401이었습니다.
- Keycloak 재생성 후 동일 volume으로 토큰 발급·로그인·네 MCP 경로 검증을 다시 통과했습니다. healthcheck와 Gateway 시작 의존성도 적용했습니다.
- 준비 스크립트 재실행은 두 모드의 기존 비밀값·import 내용을 보존했고 파일 권한 600을 확인했습니다.

마무리: 세 Gateway의 config mount를 `config-multi-policies.yaml`로 복원하고 두 Keycloak 컨테이너를 정지했습니다.
계정·realm import·DB volume은 보존했습니다. 복원 후 single/HA 모두 복합 정책의 도구 권한,
클라이언트별 제한·전체 제한과 refill 복구 회귀 테스트를 통과했습니다.
