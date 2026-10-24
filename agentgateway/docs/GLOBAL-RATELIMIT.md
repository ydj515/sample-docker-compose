# 6단계 — HA 전역 Rate Limit

[문서 안내](../README.md) · [Compose 선택](COMPOSE.md) · [로드맵](../POLICY-ROADMAP.md)

실행 위치: `agentgateway/single/` 또는 `agentgateway/ha/` (별도 표시 우선). 최초 준비는 각 모드 README를 따릅니다. 검증 기록은 v1.6.0의 과거 실행 결과입니다.

`config-global-ratelimit.yaml`과 `compose-global-ratelimit.yml`을 함께 사용합니다.
싱글과 HA 각각 Envoy Rate Limit gRPC 서비스와 Redis를 추가합니다. 두 모드의 Redis는 별도이며,
**HA 프로젝트 안의 gateway-1/2가 같은 Redis 카운터를 사용**합니다. single과 ha 사이의 공유는 아닙니다.
기존 로컬 rate limit을 이 설정에 겹치지 않아 원격 카운터만 관찰합니다.

```text
client → gateway-1 또는 gateway-2 → Envoy Rate Limit (gRPC :8081) → Redis
              └── 허용 시 → mcp-demo
```

역할은 다음과 같습니다.

- agentgateway: `sample-global` domain과 CEL로 계산한 descriptor를 전송하고 허용/차단 결과를 적용.
- `shared/ratelimit/config.yaml`: 제한의 키, 시간 단위, 허용 횟수를 정의.
- Envoy Rate Limit: descriptor에 맞는 정책을 찾고 Redis 카운터로 판정.
- Redis: 공유 사용량과 만료 시간을 보관. AOF와 프로젝트별 named volume 사용.
- 기존 SQLite: gateway UI/설정용 저장소이며 전역 제한 카운터를 저장하지 않음. PostgreSQL은 추가하지 않음.

| 경로 | descriptor | 제한 | 소진 응답 |
| --- | --- | --- | --- |
| HTTP `/global-limit` | client | 같은 클라이언트 5회/시간 | HTTP 429 |
| HTTP `/global-recovery` | recovery-client | 같은 클라이언트 2회/초 | HTTP 429, 다음 시간창에서 복구 |
| MCP `/mcp` | mcp-client | 같은 클라이언트 10회/시간 | 도구 호출은 HTTP 200 + result.isError=true |

모든 값은 `x-demo-client`에서 읽으며 없으면 `anonymous`를 사용합니다.
시간창은 고정 창입니다. 매 요청마다 시간이 연장되는 sliding window나 local token bucket과 다릅니다.
키를 바꾸면 별도 한도를 얻는 **실습용 식별자**입니다. 운영에서는 인증된 사용자/조직 claim으로 대체해야 합니다.
RLS 정책에 매칭되지 않는 descriptor는 제한을 받지 않을 수 있으므로 domain/key 일치가 필수입니다.

### 실행 및 검증

```bash
# single/ 또는 ha/에서
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
export AGENTGATEWAY_CONFIG=./config-global-ratelimit.yaml
docker compose -f docker-compose.yml -f compose-global-ratelimit.yml config --quiet
docker compose -f docker-compose.yml -f compose-global-ratelimit.yml up -d --wait

# single/에서
python3 ../shared/test-global-ratelimit.py http://127.0.0.1:4000 --lifecycle .
python3 ../shared/test-global-ratelimit-mcp.py http://127.0.0.1:3000/mcp

# ha/에서: 직접 MCP 포트는 테스트 때만 노출
docker compose -f docker-compose.yml -f compose-global-ratelimit.yml -f compose-auth.yml up -d --wait
python3 ../shared/test-global-ratelimit.py http://127.0.0.1:14001 http://127.0.0.1:14002 --lifecycle .
python3 ../shared/test-global-ratelimit-mcp.py http://127.0.0.1:16001/mcp http://127.0.0.1:16002/mcp

# 복합 정책 복원 및 실험 서비스 정지. Redis volume은 보존.
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
docker compose -f docker-compose.yml -f compose-global-ratelimit.yml stop ratelimit redis
unset AGENTGATEWAY_CONFIG
```

`--lifecycle`은 지정한 로컬 Compose 프로젝트의 RLS·Redis·gateway를 재시작하고 RLS를 잠시 정지합니다.
일반 카운터 테스트만 하려면 옵션을 생략합니다. 서비스 중단 테스트는 `finally`에서 RLS를 다시 시작합니다.
컨테이너 재시작은 수행하지만 데이터 삭제·DB 초기화는 하지 않습니다.
테스트는 고유 클라이언트 ID를 사용하며 정확한 시간 단위 검증을 위해 매시 마지막 30초에는 재실행을 요청합니다.
Compose `--wait`만으로 RLS 정책 로딩을 보장하지 않으므로 테스트에서 실제 허용 응답을 먼저 기다립니다.

### 실패 처리와 검증 범위

`failureMode: failClosed`를 명시했습니다. 공식 문서 본문과 예제 주석의 기본값 설명이 달라 기본값에 의존하지 않습니다.
RLS가 정지하면 정상 backend로 우회하지 않고 HTTP 500을 반환합니다. 연결 실패 판정까지 대기하므로 즉시 차단되는 것은 아닙니다.
최초 5초 client timeout은 장애 응답보다 먼저 종료됐고, 테스트를 40초로 늘려 실제 500을 확인합니다.
이 값은 테스트 client의 대기 시간이며 gateway의 장애 응답 SLA 설정이 아닙니다.

- 제약: RLS와 Redis는 각각 단일 인스턴스입니다. 게이트웨이 간 전역 제한 예제이며 제한 계층 자체의 HA를 제공하지 않습니다. HTTP 장애 검증을 MCP 장애 응답 형태로 일반화하지 않습니다.
- 위험: Redis 손실·만료·정책 키 변경은 사용량에 영향을 줍니다. AOF를 사용하지만 강제 장애·디스크 손실·Redis failover의 무손실성은 검증하지 않습니다. 모든 허용 요청에 원격 판정 비용이 추가되며 처리량 벤치마크는 하지 않았습니다.
- 예외: Redis/RLS 포트는 호스트에 노출하지 않습니다. 내부 통신의 TLS·인증과 운영용 사용자 인증은 이 단계에 포함하지 않습니다. Redis volume 삭제는 카운터 삭제이므로 복원 명령에 포함하지 않습니다.

이미지는 검증 시점의 `envoyproxy/ratelimit:master`와 `redis:7.4-alpine`을 digest로 고정했습니다.
이후 태그가 이동해도 동일한 이미지를 사용하며, digest 갱신은 별도 검증 후 수행합니다.
공식 근거: [agentgateway rate limits](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/resiliency/rate-limits/),
[Envoy Rate Limit 구현과 Redis 설정](https://github.com/envoyproxy/ratelimit).

### 실행 기록 — 6단계 (2026-10-19)

- HA: HTTP 교차 요청은 합산 5회 허용 후 양쪽 429. 12개 동시 요청은 5개 허용·7개 차단. 다른 client는 독립적으로 허용.
- HA 및 싱글: 초 단위 제한 소진 후 다음 시간창에서 복구. RLS·gateway 재시작 후 소진 상태 유지.
- HA 및 싱글: Redis 정상 재시작 후 AOF 기반 소진 상태 유지. 싱글 최초 재시작 직후 검사는 실패했으며 응답 코드는 기록하지 못했습니다. 500만 재확인하는 검사를 추가한 재실행은 통과했습니다. 200은 재시도하지 않고 즉시 실패합니다.
- RLS 정지: HTTP 500으로 차단. HA 두 요청의 합산 대기 약 20초(순차 요청); 즉각 실패 응답이나 운영 SLA를 보장하지 않음.
- HA MCP: 두 초기화 + echo 8회 = 공유 10회 소진. 이후 양쪽 도구 호출은 HTTP 200 + isError=true.
- 싱글 MCP: 초기화 1회 + echo 9회 = 10회 소진. 세션 ID를 유지해 검증.
- 단일 RLS 정지·정상 복구와 Redis 정상 재시작까지만 확인. Redis 강제 종료·분산 failover는 미검증.

세 Gateway의 `config-multi-policies.yaml` mount 복원, 양쪽 RLS·Redis 정지와 Redis volume 보존을 확인했습니다.
일반 smoke는 역할 헤더가 없어 add 노출 검사에 실패했으며, 복합 정책 전용 `test-multi-policies.py`로
single/HA의 권한·두 제한·refill 복구를 다시 검증해 통과했습니다.
