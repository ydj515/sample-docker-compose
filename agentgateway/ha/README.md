# agentgateway HA

Nginx가 두 agentgateway 인스턴스에 MCP 요청을 라운드로빈으로 분산합니다.
공통 소스의 `echo`, `add` MCP 서버도 Compose가 직접 빌드합니다.

```text
localhost:13000/mcp -> Nginx -> gateway-1:3000 ─┐
                           -> gateway-2:3000 ─┴-> mcp-demo:3005/mcp
localhost:14001/ui          -> gateway-1:4000 -> data/gateway-1
localhost:14002/ui          -> gateway-2:4000 -> data/gateway-2
```

## 실행

Docker Compose v2.17 이상이 필요합니다. macOS/Linux 또는 Windows WSL에서 이 폴더를 기준으로 실행합니다.

```bash
cp -n .env.example .env
mkdir -p data/gateway-1 data/gateway-2
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 180
python3 ../shared/smoke-test.py http://127.0.0.1:13000/mcp
```

- MCP 접속 주소: <http://localhost:13000/mcp>
- 인스턴스별 UI: <http://localhost:14001/ui>, <http://localhost:14002/ui>
- UI와 SQLite 실행 데이터는 인스턴스별이며 서로 동기화하지 않습니다.
- UI Playground에서 게이트웨이의 공통 MCP 주소 `http://localhost:13000/mcp`를 사용합니다.
- `config.yaml`은 두 게이트웨이에 동일하게 읽기 전용 마운트합니다.
- `statefulMode: stateless`를 사용하므로 세션 고정 없이 요청을 분산합니다. 상태를 유지하는 외부 MCP 서버에 그대로 적용하지 않습니다.

UI 포트를 변경하면 `config.yaml`의 CORS `allowOrigins`도 변경합니다.
MCP 포트 변경 시 테스트 명령의 URL도 맞춥니다. 새 셸에서는 `LOCAL_UID`, `LOCAL_GID`를 다시 export합니다.

## 장애 전환 검증

두 게이트웨이가 실행 중일 때 실행합니다. 이 스크립트는 로컬 게이트웨이를 한 대씩 중지했다가 복구합니다.

```bash
python3 test-failover.py
# 호스트 포트 변경 시
python3 test-failover.py http://127.0.0.1:23000/mcp
```

검증 순서는 양쪽 분산 확인, gateway-1 중지 후 호출, 복구, gateway-2 중지 후 호출, 복구입니다.
각 중단 단계에서는 30초를 회복 대기 기준으로 사용하며, 개별 HTTP 요청의 제한 시간은 15초입니다.
연속 echo 6회가 성공하면 초기화·도구 조회·echo·add·잘못된 입력 검증을 실행합니다.
회복 시간과 일시적인 HTTP 실패 횟수를 출력하며, 무오류 전환을 성공 조건으로 삼지는 않습니다.
`X-Gateway-Upstream` 응답 헤더로 실제 응답 인스턴스가 바뀌었는지 확인합니다.
실패해도 `finally`에서 중지한 컨테이너를 다시 시작합니다.

```bash
docker compose logs --tail=50 load-balancer gateway-1 gateway-2
# 중지하고 데이터 유지
docker compose stop
```

## 장애 대응 범위

- 제약: 게이트웨이 프로세스 1개 중단에 대한 가용성 실습입니다. Nginx, MCP 서버, Docker 호스트는 각각 단일 장애 지점입니다. Nginx `/healthz`는 로드밸런서 자체만 검사하므로 전체 경로는 smoke test로 확인합니다.
- 위험: 처리 중인 요청이나 스트림은 장애 시 실패할 수 있습니다. 이미 전송된 POST를 강제로 재실행하는 `non_idempotent` 옵션을 사용하지 않아 부작용 있는 도구의 중복 호출을 피합니다. 무손실·정확히 한 번 실행을 보장하지 않습니다.
- 예외: 세션을 저장하는 MCP 백엔드, 인증·TLS, 다중 호스트 장애, 공유 DB 운영은 이 샘플 범위에 포함하지 않습니다. SQLite 파일을 두 인스턴스가 공유하면 안 됩니다.

Nginx는 연결 실패 시 다른 게이트웨이로 전환하며, 실패 인스턴스는 5초 후 다시 시도합니다. Docker DNS 갱신과 요청 기반 장애 감지 중에는 일시적인 502/504가 발생할 수 있습니다.
Docker DNS를 다시 조회하므로 컨테이너 재생성 시 주소 변경도 반영합니다.
MCP 서버 변경 시 두 게이트웨이도 Compose 의존성 설정에 따라 다시 시작하므로 이 작업은 무중단 업데이트가 아닙니다.

- [agentgateway stateless MCP](https://agentgateway.dev/docs/standalone/latest/integrations/mcp/servers/http/)
- [Nginx upstream retry](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_next_upstream)

## 로컬 검증 결과

Compose 문법, 이미지 빌드, 두 인스턴스 분산, 양방향 중단·복구, MCP 전체 호출 테스트를 통과했습니다.
최종 실행은 각 방향 약 1초 후 연속 호출이 성공했지만, 앞선 실행에서는 DNS 전환 중 504가 발생했습니다.
이는 해당 로컬 실행의 결과이며 운영 환경 복구 시간이나 무오류 전환 보장이 아닙니다.

## 다른 실습으로 전환

처음 진행한다면 [실습 권장 순서](../docs/LEARNING-PATH.md)의 선행 조건과 통과 기준을 확인합니다.

[Compose 파일 선택 안내](../docs/COMPOSE.md)에서 실습별 설정, 추가 파일 조합, 준비 작업과 포트를 확인합니다.
[로드맵](../POLICY-ROADMAP.md)은 완료 상태와 미검증 범위를 관리합니다.

| 목적 | 안내 |
| --- | --- |
| 기본·복합 정책 | [Rate limit·도구 권한](../shared/POLICIES.md) |
| 정책 순서·API Key·Timeout·요청 처리·전역 제한 | [실습별 설정과 Compose 조합](../docs/COMPOSE.md) |
| HTTPS·mTLS·외부 인가 | [TLS](../docs/TLS.md), [mTLS](../docs/MTLS.md), [외부 인가](../docs/EXTAUTHZ.md) |
| OAuth / OIDC 로그인 | [Keycloak 준비·실행](../docs/OIDC.md) |
| OAuth+mTLS 및 갱신·회전 | [인증 비교](../shared/AUTH-COMPARISON.md), [갱신·회전](../shared/AUTH-LIFECYCLE.md) |
| Mock A2A | [실행·계약·정책 비교](../shared/A2A.md) |

`compose-auth.yml`은 인증을 켜는 파일이 아니라, Gateway별 검증용 MCP 포트 16001/16002를 추가하는 파일입니다. 인증 정책은 선택한 Gateway 설정에서 적용합니다.

실습마다 같은 Compose 프로젝트를 사용합니다. 전환 전에 해당 문서의 준비 절차를 따르고, 마친 뒤에는 복원 절차로 보조 서비스를 정지합니다.
