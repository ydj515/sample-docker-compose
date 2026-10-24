# 7단계 A — HTTP·HTTPS 비교 (2026-10-19)

[문서 안내](../README.md) · [Compose 선택](COMPOSE.md) · [로드맵](../POLICY-ROADMAP.md)

실행 위치: `agentgateway/single/` 또는 `agentgateway/ha/` (별도 표시 우선). 최초 준비는 각 모드 README를 따릅니다. 검증 기록은 v1.6.0의 과거 실행 결과입니다.

사용자 지정 범위: 클라이언트→Gateway, Gateway→MCP 두 구간 모두 HTTP·HTTPS를 병행합니다.
`config-tls.yaml`과 `compose-tls.yml`은 다른 실험 정책과 분리된 TLS 비교 설정입니다.
이 단계는 서버 인증 TLS이며, mTLS·외부 인가·OAuth/OIDC까지 완료한 것은 아닙니다.

| 요청 경로 | 클라이언트 연결 | Gateway→MCP |
| --- | --- | --- |
| HTTP `/mcp/plain` | HTTP | HTTP |
| HTTP `/mcp/tls` | HTTP | HTTPS, CA·호스트명 검증 |
| HTTPS `/mcp/plain` | HTTPS | HTTP |
| HTTPS `/mcp/tls` | HTTPS | HTTPS, CA·호스트명 검증 |

두 MCP 서버는 같은 Dockerfile로 빌드하며 echo/add 도구가 같습니다.
`mcp-tls`만 Node 내장 HTTPS 서버로 기동합니다. 새 npm 의존성은 없습니다.
`config-tls.yaml`은 명시적인 plain/secure gateway와 MCP route를 사용하며,
HA에서도 세션 고정 없이 비교할 수 있도록 MCP backend를 stateless로 설정합니다.

| 모드 | HTTP 주소 | HTTPS 주소 |
| --- | --- | --- |
| single | `http://127.0.0.1:3000` | `https://localhost:3443` |
| HA Nginx | `http://127.0.0.1:13000` | `https://localhost:13443` |
| HA gateway-1 직접 검증 | HTTP는 Nginx 경유 | `https://localhost:14401` |
| HA gateway-2 직접 검증 | HTTP는 Nginx 경유 | `https://localhost:14402` |

주소 뒤에 `/mcp/plain` 또는 `/mcp/tls`를 붙입니다. 이 비교 설정에서는 기존 `/mcp` 대신 두 경로를 사용합니다.
UI 4000/14001/14002는 기존처럼 HTTP이며 이번 TLS 대상에 포함하지 않습니다.

HA의 HTTPS 경로는 `client → HTTPS Nginx → HTTPS gateway → HTTP 또는 HTTPS MCP`입니다.
Nginx는 `proxy_ssl_verify on`과 신뢰 CA·SNI `gateway-tls`를 지정합니다.
Nginx에서 TLS를 종료한 뒤 평문으로 gateway에 전달하지 않습니다.
HTTP 경로는 `client → HTTP Nginx → HTTP gateway → HTTP 또는 HTTPS MCP`입니다.

### 인증서 준비와 실행

```bash
# single/ 또는 ha/에서, 최초 한 번만 생성
python3 ../shared/prepare-tls.py ./tls-certs
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
export AGENTGATEWAY_CONFIG=./config-tls.yaml
docker compose -f docker-compose.yml -f compose-tls.yml config --quiet
docker compose -f docker-compose.yml -f compose-tls.yml up -d --build --wait

# single/에서
python3 ../shared/test-tls.py http://127.0.0.1:3000 https://localhost:3443 ./tls-certs
# ha/에서
python3 ../shared/test-tls.py http://127.0.0.1:13000 https://localhost:13443 ./tls-certs
python3 ../shared/test-tls.py http://127.0.0.1:13000 https://localhost:14401 ./tls-certs
python3 ../shared/test-tls.py http://127.0.0.1:13000 https://localhost:14402 ./tls-certs

# CA를 명시해 HTTPS→HTTPS backend 건강 확인, single 기준
curl --cacert ./tls-certs/ca.crt https://localhost:3443/tls-check/good

# 기존 복합 정책 복원 및 TLS MCP 서비스 정지
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
docker compose -f docker-compose.yml -f compose-tls.yml stop mcp-tls
unset AGENTGATEWAY_CONFIG
```

기존 `tls-certs` 폴더가 있으면 생성기는 덮어쓰지 않고 종료합니다. 유효한 인증서는 재사용합니다.
인증서 만료 시 새 디렉터리에 생성한 뒤 Compose의 인증서 mount 경로를 변경하고 서비스를 재생성합니다.
CA와 서버 인증서는 30일 유효하며, OS/브라우저 신뢰 저장소에는 자동 등록하지 않습니다.
CA에는 Basic Constraints·Key Usage·Subject Key Identifier를, 서버 인증서에는 SAN·EKU·SKI·AKI를 명시합니다.
이는 로컬 Python의 엄격한 인증서 검증에서도 통과하도록 확인한 형식입니다.

`tls-certs/`는 Git 제외 경로입니다. 디렉터리·개인키는 생성 시 소유자만 접근할 수 있습니다.
CA 개인키와 CSR은 호스트에 보관합니다. 컨테이너에는 필요한 leaf 인증서·키와 CA 공개 인증서만 읽기 전용으로 mount합니다.
Gateway와 Node TLS 서버는 LOCAL_UID/LOCAL_GID로 실행해 개인키의 전체 읽기 권한을 열지 않습니다.
Nginx 시작 프로세스는 해당 leaf 키를 읽습니다. 샘플 HA 두 replica는 같은 gateway 인증서를 공유하며 각각 발급하는 예제는 아닙니다.

### 실패 검증과 결과

- single, HA Nginx, HA 두 replica 직접 HTTPS에서 initialize·tools/list·echo·add 성공.
- 클라이언트가 CA를 신뢰하지 않거나 잘못된 CA를 사용하면 TLS 검증 실패.
- 올바른 CA라도 SNI/검증 호스트를 `wrong.invalid`로 지정하면 클라이언트가 차단.
- `/tls-check/good`: 올바른 CA와 backend 호스트명으로 HTTP 200.
- `/tls-check/bad-ca`, `/tls-check/bad-host`: v1.6.0에서 `invalid peer certificate`와 HTTP 503. 정상 응답으로 대체하지 않음.
- Nginx HTTPS 경유 6회 호출에서 서로 다른 두 upstream의 `:3443` 연결 확인.
- 새 생성기 출력으로 별도 로컬 TLS 서버에 연결해 Python 기본 엄격 검증 통과.
- 이미지 빌드의 기존 Node 테스트 4개 통과. `insecure`, `insecureHost`, curl `-k`로 검증을 우회하지 않음.

실패 검증 경로는 HTTP health endpoint에서 backendTLS의 거부를 관찰합니다.
MCP target에는 정상 CA·호스트명을 적용했으며, 잘못된 target 인증서가 MCP 오류 응답으로 변환되는 형태까지 검증하지 않았습니다.

- 제약: 로컬 CA 기반 개발 샘플입니다. 인증서 자동 갱신·공인 CA 발급·mTLS·외부 인가는 포함하지 않습니다.
- 위험: HTTP 비교 경로는 암호화되지 않습니다. 모든 공개 포트를 loopback에 바인딩했으며 실제 인증 토큰을 보내는 용도로 쓰지 않습니다. TLS는 사용자 인증이나 MCP 도구 권한을 대신하지 않습니다.
- 예외: UI는 HTTP 유지, Redis/RLS는 이번 TLS 구성에 포함하지 않습니다. 인증서 검증 실패 시 관찰한 503은 이 버전의 HTTP backend 결과이며 모든 MCP 오류가 같은 상태 코드인 것은 아닙니다.

공식 근거: [Listeners](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/listeners/),
[Backend TLS](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/backend-tls/),
[MCP target policies](https://agentgateway.dev/docs/standalone/latest/documentation/mcp/mcp-target-policies/).

검증 후 세 gateway의 복합 정책 mount와 HA의 기존 `nginx.conf` 복원을 확인했습니다.
TLS MCP 서비스는 두 모드 모두 정지했으며 생성 인증서는 보존했습니다.
복원 후 `test-multi-policies.py`의 권한·복합 제한·refill 복구 검증도 single/HA에서 통과했습니다.
