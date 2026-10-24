# 7단계 B — mTLS와 인증서 갱신 (2026-10-19)

[문서 안내](../README.md) · [Compose 선택](COMPOSE.md) · [로드맵](../POLICY-ROADMAP.md)

실행 위치: `agentgateway/single/` 또는 `agentgateway/ha/` (별도 표시 우선). 최초 준비는 각 모드 README를 따릅니다. 검증 기록은 v1.6.0의 과거 실행 결과입니다.

`config-mtls.yaml`과 `compose-mtls.yml`은 양방향 인증용 별도 설정입니다.
`/mcp/mtls`에 접근하려면 서버 CA 검증뿐 아니라 클라이언트 인증서도 제시해야 합니다.
기존 HTTP·HTTPS 비교 파일은 유지하며 mTLS 설정과 동시에 합치지 않습니다.

```text
single: client --mTLS--> gateway --mTLS--> mcp-mtls
HA:     client --mTLS--> Nginx --mTLS--> gateway --mTLS--> mcp-mtls
```

| 인증서/CA | 역할 |
| --- | --- |
| ca | Gateway·Nginx·MCP 서버 인증서를 검증하는 CA |
| frontend-ca | 외부 client와 Nginx→Gateway 인증서를 검증하는 CA |
| backend-ca | Gateway→MCP와 MCP health check 인증서를 검증하는 CA |
| client | 사용자의 테스트 클라이언트 인증서 |
| proxy-client | Nginx가 Gateway에 제시하는 인증서 |
| gateway-client | Gateway가 MCP 서버에 제시하는 인증서 |
| health-client | MCP 서버 내부 health check용 인증서 |
| wrong-ca / rogue-client | 잘못된 CA의 인증서 차단 검증용 |

Gateway HTTPS listener는 `tls.root`로 client CA를 지정하고, MCP target의 `backendTLS.cert/key`로
backend에 제시할 클라이언트 인증서를 설정합니다. Node MCP 서버는 `requestCert: true`, `rejectUnauthorized: true`와 backend-ca를 사용합니다.
Nginx는 `ssl_verify_client on`, `proxy_ssl_certificate/key`, `proxy_ssl_verify on`을 함께 사용합니다.
각 서버·클라이언트 leaf에는 serverAuth/clientAuth EKU를 구분합니다.

mTLS 설정에는 MCP용 평문 listener/route가 없습니다. HA의 13000 포트는 `/healthz` 외 요청을 403으로 차단합니다.
UI 포트 4000/14001/14002는 로컬 HTTP로 유지되며 mTLS 보호 대상에 포함하지 않습니다.
HA에서는 Gateway가 인증하는 상대가 Nginx의 proxy-client입니다. 최초 사용자의 인증서 신원을 그대로 전달하거나
그 신원으로 도구 권한을 판정하는 예제는 아닙니다.

### 처음 실행

```bash
# single/ 또는 ha/에서, 최초 한 번
python3 ../shared/prepare-mtls.py ./mtls-certs/v1
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
export AGENTGATEWAY_CONFIG=./config-mtls.yaml
export MTLS_CERT_DIR=./mtls-certs/v1
docker compose -f docker-compose.yml -f compose-mtls.yml config --quiet
docker compose -f docker-compose.yml -f compose-mtls.yml up -d --build --wait

# single/에서
python3 ../shared/test-mtls.py https://localhost:3443 ./mtls-certs/v1
# ha/에서
python3 ../shared/test-mtls.py https://localhost:13443 ./mtls-certs/v1
python3 ../shared/test-mtls.py https://localhost:14401 ./mtls-certs/v1
python3 ../shared/test-mtls.py https://localhost:14402 ./mtls-certs/v1

# single mTLS 호출: 서버 CA와 클라이언트 인증서 모두 필요
curl --cacert ./mtls-certs/v1/ca.crt \
  --cert ./mtls-certs/v1/client/tls.crt --key ./mtls-certs/v1/client/tls.key \
  https://localhost:3443/mtls-check/good
```

인증서 디렉터리가 이미 있으면 생성기는 덮어쓰지 않습니다. 초기 CA는 365일, leaf는 7일 유효합니다.
`mtls-certs/`는 Git 제외 경로이며 개인키와 디렉터리는 소유자 접근 권한으로 생성합니다.
CA 개인키는 컨테이너에 mount하지 않습니다. 런타임에는 필요한 공개 CA와 leaf 인증서·개인키만 읽기 전용으로 전달합니다.
검증용 rogue-client 개인키는 실패 경로 실험을 위해 Gateway에 mount하며 운영 구성에는 포함하지 않습니다.

### 갱신 예제: v1 → v2

**같은 CA를 유지하고 모든 leaf 인증서·키를 새로 발급하는 갱신입니다. CA 교체가 아닙니다.**
새 leaf의 유효기간은 30일입니다. CA 만료까지 31일 이상 남지 않으면 갱신 생성을 중단합니다.
기존 세대는 보존하므로 문제가 생기면 이전 mount 경로로 되돌릴 수 있습니다.

```bash
# single/에서: 새 세대 생성 → Compose 재생성 → mTLS 및 실제 인증서 검증
python3 ../shared/rotate-mtls.py single ./mtls-certs/v1 ./mtls-certs/v2
# ha/에서는 위 명령 대신
python3 ../shared/rotate-mtls.py ha ./mtls-certs/v1 ./mtls-certs/v2

# 이후 Compose 명령에서 새 세대를 명시
export MTLS_CERT_DIR=./mtls-certs/v2
export AGENTGATEWAY_CONFIG=./config-mtls.yaml

# 인증서만 발급하고 전환은 나중에 하려면 rotate-mtls.py 대신 실행
# python3 ../shared/prepare-mtls.py ./mtls-certs/v2 --renew-from ./mtls-certs/v1

# 이전 세대로 롤백: 이전 인증서가 아직 유효한 경우
MTLS_CERT_DIR=./mtls-certs/v1 docker compose -f docker-compose.yml -f compose-mtls.yml up -d --force-recreate --wait

# 기존 복합 정책으로 복원; 인증서 파일은 보존
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
docker compose -f docker-compose.yml -f compose-mtls.yml stop mcp-mtls
unset MTLS_CERT_DIR AGENTGATEWAY_CONFIG
```

`rotate-mtls.py`는 새 디렉터리에 생성하고 `--force-recreate`로 컨테이너를 재생성합니다.
Docker 단일 파일 bind mount와 프로세스의 인증서 캐시 때문에 파일 교체만으로 갱신됐다고 가정하지 않습니다.
이 스크립트는 로컬 예제용이며 **중단이 발생하는 전환**입니다. HA도 순차 무중단 갱신을 구현하지 않았습니다.
실패하면 자동 롤백하지 않으며 이전 세대 파일을 보존합니다. 출력된 경로를 사용해 위 명령으로 복원합니다.
스크립트 내부 환경 변수는 부모 셸에 남지 않으므로 이후 명령에서는 MTLS_CERT_DIR를 다시 지정해야 합니다.

### 검증 결과와 경계

- 정상 client 인증서로 single·HA Nginx·HA 두 replica에서 MCP initialize/list/echo/add 성공.
- 인증서 없음, wrong-ca 인증서, backend-ca 서명 인증서로 frontend 접근 시 차단.
- backend에 클라이언트 인증서를 보내지 않거나 rogue-client를 보내면 HTTP 503. 정상 Gateway 인증서는 허용.
- Gateway 직접 접속은 TLS 오류로 차단되며 Nginx는 TLS 연결 이후 HTTP 400/403으로 거절할 수 있어 두 형태를 구분해 검사.
- v2에서 CA 동일성, leaf serial 변경, 만료일 연장 확인. 실제 HTTPS 연결에서 Gateway 인증서 fingerprint와 v2 파일 일치 확인.
- MCP 서버에 별도 mTLS 연결해 실제 제시한 backend 인증서 fingerprint가 v2와 일치함을 확인.
- 갱신 후 새 client 인증서로 양 구간 MCP 호출 성공. 이전 client 인증서도 아직 만료되지 않았으므로 계속 허용됨을 확인.

- 제약: mTLS는 신뢰 CA가 발급한 인증서 소유를 확인합니다. 개별 SAN allowlist나 사용자별 MCP 도구 권한은 별도 정책이며 이번 단계에는 없습니다.
- 위험: 인증서 갱신은 이전 인증서를 폐기하지 않습니다. 탈취 대응을 위한 CRL/OCSP·명시적 차단 정책은 미구현입니다. 같은 CA 아래 발급된 client 인증서는 만료 전까지 허용될 수 있습니다.
- 예외: CA rotation, 자동 발급 서버, 자동 스케줄 갱신, 무중단 rolling rotation, 만료된 인증서의 실제 시간 경과 테스트는 포함하지 않습니다. 로컬 예제는 인증서 검증을 끄지 않습니다.

공식 근거: [Backend TLS](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/backend-tls/),
[설정 스키마의 LocalTLSServerConfig.root](https://agentgateway.dev/schema/config).

### 실행 마무리 — 7단계 B

single·HA 모두 v1 발급 → v2 갱신/전환 → v1 롤백을 실행했습니다.
롤백 후 single, HA Nginx, HA 두 replica 직접 접속에서 인증서 차단·정상 MCP 호출·v1 서버 fingerprint 검증을 다시 통과했습니다.
mTLS 실행 중 평문 MCP 포트와 UI 포트에 `/mcp/mtls`를 요청해 우회 경로가 없음을 확인했습니다.
이미지 빌드의 Node 테스트 4개와 생성 개인키의 소유자 전용 파일 권한 검사를 통과했습니다.

마지막으로 세 gateway의 `config-multi-policies.yaml` 및 HA의 기존 `nginx.conf` mount 복원을 확인했습니다.
mTLS MCP 서비스는 두 모드 모두 정지하고 v1/v2 인증서는 보존했습니다.
복원 후 `test-multi-policies.py`의 권한·복합 제한·refill 복구도 single/HA 모두 통과했습니다.
