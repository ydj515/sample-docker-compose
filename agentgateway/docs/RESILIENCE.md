# 4단계 — Timeout·Retry

[문서 안내](../README.md) · [Compose 선택](COMPOSE.md) · [로드맵](../POLICY-ROADMAP.md)

실행 위치: `agentgateway/single/` 또는 `agentgateway/ha/` (별도 표시 우선). 최초 준비는 각 모드 README를 따릅니다. 검증 기록은 v1.6.0의 과거 실행 결과입니다.

`config-resilience.yaml`은 기본 MCP 설정을 유지하고 UI/HTTP 포트에 `/resilience/*` 실험 경로를 추가합니다.
공유 서버는 요청 ID별 수신 횟수를 메모리에 기록하고, 지정 횟수만큼 503/400을 반환하거나 최대 2초 지연합니다.
카운터는 최근 최대 1,000개 ID를 유지하고 서버 재시작 시 초기화됩니다. 업무 데이터 변경은 하지 않습니다.

| 시나리오 | 설정·입력 | 검증할 결과 |
| --- | --- | --- |
| 일시 오류 복구 | 503 두 번 후 정상, retry attempts=3 | 세 번째 호출에서 200 |
| 재시도 소진 | 계속 503, retry attempts=3 | v1.6.0 실측 총 4회 후 503 |
| 재시도 대상 코드 아님 | codes=[503], 서버는 400 | 1회 후 400 |
| POST 재전달 | 503 두 번 후 정상, retry 활성화 | POST가 3회 backend에 도착 |
| 재시도 정책 없음 | POST, 서버 503 | 1회만 전달 |
| backend timeout | backendRequestTimeout=200ms, 서버 1500ms 지연 | 약 200ms에 504, backend 수신 1회 |
| 전체 요청 예산 | requestTimeout=400ms, backendRequestTimeout=2s, retry attempts=10 | 전체 예산으로 504, 재시도 상한 전에 중단 |

### 문서와 실제 횟수 차이

공식 최신 retry 문서는 attempts를 최초 요청을 포함한 총 횟수로 설명합니다.
그러나 고정된 v1.6.0 이미지에서 `attempts: 3`은 모두 실패할 때 4회, `attempts: 1`은 2회 수신됐습니다.
테스트는 이 실행 결과를 기준으로 고정했습니다. 버전 변경 시 동일한 카운터 검증을 다시 실행해야 합니다.
재시도하지 않는 경로는 `attempts: 1` 대신 **retry 정책을 생략**했으며 503에 대한 POST 전달이 1회임을 확인합니다.
연결 자체의 실패 등 다른 실패 종류까지 모든 재시도를 금지한다고 일반화하지 않습니다.

### 실행

```bash
# single/ 또는 ha/에서
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
AGENTGATEWAY_CONFIG=./config-resilience.yaml docker compose config --quiet
AGENTGATEWAY_CONFIG=./config-resilience.yaml docker compose up -d --build --wait

# single/에서
python3 ../shared/test-resilience.py http://127.0.0.1:4000
# ha/에서
python3 ../shared/test-resilience.py http://127.0.0.1:14001
python3 ../shared/test-resilience.py http://127.0.0.1:14002

# 복합 정책으로 복원
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
```

검증마다 새로운 요청 ID를 사용하므로 재시작 없이 반복할 수 있습니다.
시간 단정은 로컬 관찰이며 테스트는 지연 응답보다 먼저 종료되는지 여유 있는 상한으로 검사합니다.
HA에서는 각 인스턴스에 직접 요청해 게이트웨이 자체 retry와 Nginx 전환을 혼동하지 않습니다.

- 제약: 이 단계는 HTTP route 정책 검증입니다. MCP tool 결과의 `isError`, SSE 스트림 종료·유휴 시간, LLM 요청 재시도는 검증하지 않습니다.
- 위험: POST도 재전달됩니다. 생성·결제 등 부작용이 있는 요청은 멱등성 보장 없이 retry를 활성화하면 중복 처리가 발생할 수 있습니다. Timeout은 이미 실행된 backend 작업의 롤백 보장이 아닙니다.
- 예외: 재시도 본문 버퍼 크기 초과, 여러 backend 간 선택, 네트워크 장애 종류별 재시도는 이번 범위 밖입니다. 같은 프로세스의 인메모리 카운터를 사용하므로 서버 재시작과 동시에 실행하지 않습니다.

공식 근거: [Retries](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/resiliency/retries/),
[Timeouts](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/resiliency/timeouts/).

### 실행 기록 — 4단계 (2026-10-19)

싱글 7개 + HA 각 7개, 총 21개 시나리오를 통과했습니다.
backend timeout은 약 203~206ms, 전체 예산은 약 404~406ms에 504를 반환했습니다.
전체 예산 테스트는 backend 수신 2회에서 종료됐습니다. 해당 수치는 로컬 검증 당시 관찰값입니다.
기존 MCP echo/add smoke test도 싱글·HA에서 통과했습니다. 후속 검증은 [5단계 요청 처리](REQUEST-PROCESSING.md)에 기록했습니다.
