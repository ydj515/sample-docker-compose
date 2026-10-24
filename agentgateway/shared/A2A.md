# Mock LLM A2A 비교 샘플

외부 모델·API 키·추가 패키지 없이 Node.js 내장 HTTP 서버를 Compose에서 빌드합니다.
A2A 0.3.0의 동기 메시지 교환 일부를 구현하며, `hello` 입력에는 `Mock LLM: hello`를 반환합니다.
실제 모델 품질·토큰 사용량·LLM guardrail 검증을 대체하지 않습니다. 기존 8단계 LLM 정책은 보류 상태입니다.

## 계약과 비교 범위

| 경로/항목 | 동작 |
| --- | --- |
| GET `/a2a/.well-known/agent-card.json` | `a2a: {}`가 내부 URL을 클라이언트가 접근한 Gateway URL로 재작성 |
| GET `/raw/.well-known/agent-card.json` | A2A 정책 없음. 내부 `http://a2a-demo:3010/a2a`가 그대로 반환됨 |
| POST `/a2a` 또는 `/raw` | JSON-RPC `message/send`, 텍스트 Message 입력 → 즉시 agent Message 반환 |
| 인증 | 두 경로 모두 `Authorization: Bearer <local-api-key>` 필요; 누락/잘못된 키 401 |
| 호출 제한 | 두 경로 각각 Gateway replica별 사용자별 20회/10초. Agent Card 조회·오류 요청도 소비 |
| 오류 | JSON 파싱 -32700, 잘못된 요청 -32600, 미지원 메서드 -32601, 미지원 입력 -32602 |
| HTTP 제한 | JSON 이외 415, 본문 64 KiB 초과 413, Origin 있는 요청 403 |

필수 입력: `jsonrpc`, `id`, `method`, `params.message`의 `kind: message`, `role: user`,
비어 있지 않은 `messageId`, 텍스트 `parts`. 응답은 `kind: message`, `role: agent`, 생성된
messageId/contextId, text part, `metadata.mock: true`를 포함합니다.
`contextId`는 전달할 수 있지만 대화 이력은 저장하지 않습니다.
Task, streaming, push notification, file/data part, configuration은 지원하지 않습니다.
미지원 configuration/taskId는 조용히 무시하지 않고 거부합니다. 전체 A2A 적합성 인증 샘플은 아닙니다.

API 키는 Gateway가 검증합니다. 내부 서버 자체는 인증하지 않으며 호스트 포트를 공개하지 않습니다.
Agent Card의 bearer scheme은 이 Gateway 진입점의 인증을 설명합니다.
`a2a: {}` 자체가 skill 권한이나 Task 소유권을 검증하는 것은 아닙니다.
HA도 A2A 서버는 1개이며 Gateway 2개만 비교합니다. local rate limit은 전역 제한이 아닙니다.

## 실행

저장소 루트에서 실행합니다. 기존 키 파일은 재사용하고 키 값은 출력하지 않습니다.
이 설정은 포트 3000을 A2A용으로 사용하므로 같은 Gateway의 기존 MCP 샘플을 일시 대체합니다.
기본 Compose의 mcp-demo 컨테이너는 유지되지만 A2A 요청에는 사용하지 않습니다.
4000 관리 UI 매핑은 이 실험에서 사용하지 않습니다.

```bash
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
python3 agentgateway/shared/prepare-auth.py agentgateway/single a2a
AGENTGATEWAY_CONFIG=./data/config-a2a.yaml docker compose \
  -f agentgateway/single/docker-compose.yml -f agentgateway/single/compose-a2a.yml \
  up -d --build agentgateway
python3 agentgateway/shared/test-a2a.py agentgateway/single http://127.0.0.1:3000

python3 agentgateway/shared/prepare-auth.py agentgateway/ha a2a
AGENTGATEWAY_CONFIG=./data/config-a2a.yaml docker compose \
  -f agentgateway/ha/docker-compose.yml -f agentgateway/ha/compose-auth.yml \
  -f agentgateway/ha/compose-a2a.yml up -d --build gateway-1 gateway-2 load-balancer
python3 agentgateway/shared/test-a2a.py agentgateway/ha \
  http://127.0.0.1:16001 http://127.0.0.1:16002 http://127.0.0.1:13000
```

테스트는 버킷 초기화/재충전을 위해 각 주소에서 두 번 11초 대기합니다.
HA 재기동 직후에는 Nginx DNS 수렴 후 실행합니다.
테스트 클라이언트는 `data/auth-keys.json`을 내부에서 읽고 키를 출력하지 않습니다.
직접 호출할 메시지 예시:

```json
{
  "jsonrpc": "2.0",
  "id": "demo-1",
  "method": "message/send",
  "params": {
    "message": {
      "kind": "message",
      "role": "user",
      "messageId": "user-1",
      "parts": [{"kind": "text", "text": "hello A2A"}]
    }
  }
}
```

## 기존 복합 정책 복원

```bash
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose \
  -f agentgateway/single/docker-compose.yml up -d agentgateway
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose \
  -f agentgateway/ha/docker-compose.yml up -d gateway-1 gateway-2 load-balancer

docker compose -f agentgateway/single/docker-compose.yml \
  -f agentgateway/single/compose-a2a.yml stop a2a-demo
docker compose -f agentgateway/ha/docker-compose.yml \
  -f agentgateway/ha/compose-a2a.yml stop a2a-demo
python3 agentgateway/shared/test-multi-policies.py http://127.0.0.1:3000/mcp
python3 agentgateway/shared/test-multi-policies.py http://127.0.0.1:13000/mcp
```

## 근거

- [A2A 0.3.0 specification](https://a2a-protocol.org/v0.3.0/specification/)
- [agentgateway v1.6.0 A2A example](https://github.com/agentgateway/agentgateway/blob/v1.6.0/examples/traffic-a2a/config.yaml)
- [v1.6.0 A2A processing](https://github.com/agentgateway/agentgateway/blob/v1.6.0/crates/agentgateway/src/a2a/mod.rs)

## 별도 A2A 실행 기록 — 2026-10-19

Node 단위/HTTP 테스트 2개와 Compose 빌드를 통과했습니다.
single(3000), HA Gateway 직접(16001/16002), Nginx(13000)에서 다음을 확인했습니다.

- `a2a: {}` 적용 시 Agent Card URL 재작성, 미적용 `/raw`에서는 내부 URL 유지.
- 모킹 Message 응답, JSON 파싱/미지원 메서드/잘못된 params 오류.
- API 키 누락/잘못된 키 401, 버킷 소진 429, 다른 사용자 버킷 허용, 10초 refill 이후 복구.

검증 범위는 위의 [계약과 비교 범위](#계약과-비교-범위)에 한정합니다.

세 Gateway의 mount를 `config-multi-policies.yaml`로 복원하고 양쪽 a2a-demo를 정지했습니다.
설정·자격 증명·컨테이너는 보존했습니다. 복원 후 single/HA 복합 정책 회귀 테스트를 통과했습니다.
