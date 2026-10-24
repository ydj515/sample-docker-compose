# agentgateway single

Docker Compose로 agentgateway UI와 MCP 프록시를 실행하는 로컬 실습입니다.
샘플에 포함된 작은 MCP 서버를 Dockerfile로 직접 빌드해 함께 실행합니다.
Node.js 기본 모듈만 사용하므로 npm 설치나 API 키가 필요 없습니다.

```text
MCP client -> localhost:3000/mcp -> agentgateway -> mcp-demo:3005/mcp
Browser    -> localhost:4000/ui -> agentgateway UI
```

## 실행

Docker와 Docker Compose v2.17 이상이 필요합니다. 이 디렉터리에서 실행합니다.

```bash
# 포트 등을 바꿀 때만 복사하고 수정합니다. 기본값이면 복사하지 않아도 됩니다.
cp -n .env.example .env
mkdir -p data
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 180
docker compose ps
docker compose logs --tail=100 agentgateway mcp-demo
```

- UI: <http://localhost:4000/ui>
- MCP Streamable HTTP: <http://localhost:3000/mcp>
- MCP 테스트 서버는 Compose 내부에서만 접근합니다.

UI의 MCP Tool Playground에서 초기화한 뒤 `echo` 도구를 선택하고
`message`를 입력해 호출합니다. 도구 이름은 실제 조회 결과를 기준으로 선택합니다.
`add` 도구는 숫자 `a`, `b`를 받아 합을 반환합니다. 예: `{"a": 2, "b": 3}` → `5`.
Python 3이 있으면 다음 명령으로 초기화, 도구 조회, echo·add 결과와 잘못된 입력 처리를 자동 검증합니다.

```bash
python3 ../shared/smoke-test.py
# 호스트 MCP 포트를 변경한 경우
python3 ../shared/smoke-test.py http://127.0.0.1:13000/mcp
```

연결 실패, JSON-RPC 오류, echo 결과 불일치는 0이 아닌 종료 코드로 처리합니다.
이는 로컬 MCP 프록시 검증이며 LLM 호출이나 외부 MCP 서버 연동 검증은 아닙니다.

검증 환경에서는 agentgateway v1.6.0의 기동, UI HTTP 200 응답,
MCP 초기화, 2개 도구 조회, echo 및 add 결과, 잘못된 입력 거부를 확인했습니다.
Docker 빌드 중 서버 테스트 3개도 통과했습니다.
브라우저에서 UI를 직접 조작하는 검증은 수행하지 않았습니다.

## 설정과 중지

| 파일 | 용도 |
| --- | --- |
| `docker-compose.yml` | 서비스, 포트, SQLite 데이터 디렉터리 설정 |
| `config.yaml` | UI, MCP 대상, CORS 설정 |
| `.env.example` | 이미지 및 호스트 포트 기본값 |
| `../shared/mcp-server/` | 서버 코드, Dockerfile, Node.js 테스트 (빌드 시 실행) |
| `../shared/smoke-test.py` | 표준 라이브러리만 사용하는 MCP 검증 |

`config.yaml`은 읽기 전용으로 마운트합니다. UI는 조회와 도구 호출에 사용하고,
설정은 호스트 파일에서 수정합니다. UI에서 설정 저장은 실패할 수 있습니다.
수정 후 다음 명령으로 다시 시작합니다.

```bash
docker compose restart agentgateway
# 컨테이너 중지. SQLite 데이터는 ./data에 유지됩니다.
docker compose stop
# 다시 시작
docker compose up -d --build --wait --wait-timeout 180
```

`.env`의 UI 포트를 바꾸면 `config.yaml`의 `allowOrigins` 포트도 함께 변경합니다.
Compose 포트 매핑만 바꾸므로 `config.yaml`의 내부 포트 4000/3000은 유지합니다.
다른 MCP 서버를 연결하려면 `mcp.targets`의 `host`를 변경합니다.
새 터미널에서는 실행 전에 `export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)`를 다시 실행합니다.
Windows에서는 WSL 셸에서 실행합니다.
컨테이너의 `localhost`는 호스트 컴퓨터가 아닌 해당 컨테이너를 가리킵니다.

- 제약: 최초 베이스 이미지 다운로드에는 인터넷이 필요합니다. MCP 서버는 2025-03-26 프로토콜의 초기화, ping, 도구 조회·호출을 구현한 실습용 서버이며 SSE 스트림, 리소스, 프롬프트, 인증은 제공하지 않습니다.
- 위험: 인증 없는 로컬 실습이므로 포트를 외부에 공개하지 않습니다. SQLite에는 실행 데이터가 저장됩니다.
- 예외: 호스트 포트가 이미 사용 중이면 `.env`에서 변경합니다. UI CORS 허용 출처는 기본 포트 기준입니다.

## 공식 자료

- [agentgateway 저장소](https://github.com/agentgateway/agentgateway)
- [Docker 설치](https://agentgateway.dev/docs/standalone/latest/documentation/setup/install/docker/)
- [MCP Streamable HTTP](https://agentgateway.dev/docs/standalone/latest/integrations/mcp/servers/http/)
- [v1.6.0 MCP 기본 예제](https://github.com/agentgateway/agentgateway/tree/v1.6.0/examples/mcp-basic)

## MCP 서버 개발

`../shared/mcp-server/server.mjs`를 수정한 뒤 `docker compose up -d --build --wait`로 다시 빌드합니다.
Dockerfile의 `RUN node --test server.test.mjs`가 실패하면 빌드도 실패합니다.
서버의 `/healthz`가 응답한 후 게이트웨이가 시작됩니다. Compose가 MCP 서버를 교체하면 `depends_on.restart` 설정으로 게이트웨이도 다시 시작합니다.
 MCP 백엔드 포트는 호스트에 공개하지 않습니다.
백엔드는 세션 상태 없이 JSON 응답을 반환하고, 게이트웨이가 클라이언트 MCP 연결을 처리합니다.
잘못된 도구 인자는 JSON-RPC 오류, 숫자 합의 범위 초과는 `isError: true`로 반환합니다.

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

실습마다 같은 Compose 프로젝트를 사용합니다. 전환 전에 해당 문서의 준비 절차를 따르고, 마친 뒤에는 복원 절차로 보조 서비스를 정지합니다.
