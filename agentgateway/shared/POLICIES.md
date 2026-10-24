# 정책 실습

싱글과 HA 폴더 각각의 `config-policies.yaml`은 바로 실행할 수 있는 전체 설정입니다.
기본 `config.yaml`을 유지하므로 기존 smoke/failover 테스트와 정책 실습을 구분할 수 있습니다.

| 정책 | 예시 | 기대 결과 |
| --- | --- | --- |
| `localRateLimit` | 용량 20, 10초마다 20 충전, 요청 버킷 기준 | 버킷 소진 시 MCP 도구 오류, 충전 후 다시 허용 |
| `mcpAuthorization` | `mcp.tool.name == "echo"` | echo 조회·호출 허용, add 목록 제외 및 직접 호출 차단 |
| `cors` | 모드별 로컬 UI 출처만 허용 | 허용 출처의 브라우저 preflight 응답 |
| `dnsRebindingProtection` | true | 비루프백 Host/Origin 차단 |

rate limit의 `maxTokens`는 여기서 LLM 토큰 수가 아니라 요청 버킷 용량입니다.
이 예시는 실제 echo 도구 호출로 제한을 검증합니다. v1.6.0에서는 HTTP 200이어도 MCP 결과의 `isError: true`와 `rate limit exceeded`가 제한 실패를 나타냅니다. HTTP 상태만으로 성공 여부를 판단하지 않습니다. 사용자/API 키별 제한은 아닙니다.
CORS는 인증이나 curl 접근 차단 기능이 아닙니다. 도구 제한 역시 사용자 인증을 대신하지 않습니다.

## 실행

`single/` 또는 `ha/`에서 실행합니다. 최초 데이터 폴더 준비는 각 README를 따릅니다.

```bash
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
AGENTGATEWAY_CONFIG=./config-policies.yaml docker compose config --quiet
AGENTGATEWAY_CONFIG=./config-policies.yaml docker compose up -d --build --wait
```

계속 정책 모드를 사용하려면 `.env`의 `AGENTGATEWAY_CONFIG`를 `./config-policies.yaml`로 지정합니다.
명령 앞의 값은 해당 명령에만 적용되므로 다음 `up`에서도 동일하게 전달해야 합니다.

```bash
# single/에서
python3 ../shared/test-policies.py http://127.0.0.1:3000/mcp http://localhost:4000
# ha/에서
python3 ../shared/test-policies.py http://127.0.0.1:13000/mcp http://localhost:14001
```

테스트는 버킷 충전을 위해 시작 시 11초, 제한 초과 확인 뒤 11초 기다립니다.
도구 목록 필터, echo 성공, add 차단, CORS, 100회 도구 호출 중 rate limit 오류 발생, 충전 후 성공을 검사합니다.
다른 클라이언트가 동시에 요청하면 버킷을 공유하므로 테스트 결과에 영향을 줄 수 있습니다.
일반 `smoke-test.py`와 `ha/test-failover.py`는 add 허용을 기대하므로 기본 설정에서 실행합니다.

```bash
# 기본 모드 복원 (single/ 또는 ha/에서)
AGENTGATEWAY_CONFIG=./config.yaml docker compose up -d --wait
```

## HA에서의 제한 범위

로컬 카운터는 인스턴스 메모리에만 존재하며 재시작하면 초기화됩니다.
HA 두 인스턴스의 20개 버킷은 서로 독립적입니다. 따라서 전체 서비스가 10초에 정확히 20개만 받는 구성이 아닙니다.
분산 상황과 충전 시점에 따라 전체 허용량이 달라지고, 한 대 장애 시 가용한 버킷 수도 줄어듭니다.
PostgreSQL 설정 저장을 켠다고 로컬 rate limit 카운터가 공유되는 것은 아닙니다.
전역 제한에는 Envoy Rate Limit gRPC 프로토콜을 구현한 외부 서비스와 공유 저장소를 사용하는 `remoteRateLimit` 구성이 필요합니다. 이 샘플에는 포함하지 않습니다.

- [Rate limiting](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/resiliency/rate-limits/)
- [MCP authorization](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/mcp-authz/)

## 확인한 결과

v1.6.0 로컬 Docker 실행에서 싱글·HA 모두 도구 목록 필터, echo 허용, add 차단, CORS 허용, 제한 초과 및 충전 후 복구를 확인했습니다.
100회 burst 중 싱글 86회, HA 66회가 rate limit 오류였으며 앞선 검증 요청도 버킷을 소비한 결과입니다.
이 수치는 처리량 측정이나 고정된 허용량 보장이 아닙니다. 비루프백 Origin의 HTTP 403 차단도 두 모드에서 확인했습니다.

## 여러 정책·규칙 동시 적용

`single/config-multi-policies.yaml`, `ha/config-multi-policies.yaml`은 복합 정책의 전체 설정 예시입니다.

| 조합 | 규칙 | 결합 의미 |
| --- | --- | --- |
| Rate limit 2개 | 인스턴스 전체 60개 + `x-demo-client`별 20개, 각 10초마다 충전 | 두 제한을 모두 통과해야 함 |
| MCP 권한 규칙 2개 | echo 허용 + calculator 역할의 add 허용 | 규칙 중 하나만 참이어도 허용 (OR) |
| 서로 다른 정책 | rate limit + MCP 권한 + CORS + DNS rebinding 방어 | 각 적용 단계의 조건을 충족해야 함 |

핵심 설정은 다음과 같습니다. 동일한 YAML 키를 반복하지 않고 목록으로 여러 항목을 넣습니다.

```yaml
mcp:
  policies:
    localRateLimit:
      - maxTokens: 60
        tokensPerFill: 60
        fillInterval: 10s
        type: requests
      - maxTokens: 20
        tokensPerFill: 20
        fillInterval: 10s
        type: requests
        key: request.headers["x-demo-client"]
    mcpAuthorization:
      rules:
        - 'mcp.tool.name == "echo"'
        - 'mcp.tool.name == "add" && request.headers["x-demo-role"] == "calculator"'
```

예를 들어 client-a가 20개 제한에 걸려도 client-b의 버킷과 전체 버킷에 여유가 있으면 client-b는 호출할 수 있습니다.
반면 전체 60개 버킷이 소진되면 새로운 클라이언트 값을 보내도 제한됩니다.
위 숫자는 초기 버킷 용량이며, 초기화·조회 등 다른 정책 적용 요청과 충전 시점에 따라 실제 연속 도구 호출 횟수는 달라집니다.
HA에서도 전체 버킷은 **인스턴스 전체**를 의미하며 두 인스턴스를 합친 전역 버킷이 아닙니다.

```bash
# single/ 또는 ha/에서
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose config --quiet
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --build --wait

# single/에서
python3 ../shared/test-multi-policies.py http://127.0.0.1:3000/mcp
# ha/에서
python3 ../shared/test-multi-policies.py http://127.0.0.1:13000/mcp
```

테스트는 viewer의 add 차단, calculator의 두 도구 허용, 클라이언트별 제한, 다른 클라이언트의 독립 버킷,
클라이언트 키를 바꿔도 적용되는 전체 제한, 충전 후 복구를 검사합니다. 시작과 복구 확인 시 각각 11초 기다립니다.
이 모드에는 `test-multi-policies.py`를 사용합니다. 기본 정책의 `test-policies.py`와 기대 권한이 다릅니다.

- 제약: `x-demo-role`과 `x-demo-client`는 클라이언트가 임의로 바꿀 수 있는 학습용 헤더입니다. 실제 권한이나 과금 식별자로 신뢰하면 안 됩니다. 운영에서는 검증된 JWT/API 키의 신원·역할을 사용해야 합니다.
- 위험: 권한 규칙 목록은 OR이므로 광범위한 허용 규칙 하나가 제한을 무력화할 수 있습니다. 역할과 도구를 동시에 요구하려면 한 표현식 안에서 `&&`로 묶습니다.
- 예외: 클라이언트 헤더 누락·키 표현식 평가 실패·빈 값은 해당 규칙의 공통 버킷을 사용합니다. 제한 면제가 아닙니다.

## 이후 적용 순서

정책 적용 단계, 조건부 선택, 대상별 덮어쓰기, 미검증 실행 순서는 [정책 적용 기록](../POLICY-ROADMAP.md)에서 구분해 관리합니다.

[OAuth/OIDC 설정](../docs/OIDC.md)은 `mcpAuthentication`으로
access token을 검증한 뒤 `mcpAuthorization`에서 서명된 `jwt.demo_role`을 사용합니다.
학습용 `x-demo-role` 헤더를 신뢰하는 복합 정책과 구분합니다.

## A2A 정책 비교

[A2A 샘플](A2A.md)은 `a2a: {}` 유무에 따른 Agent Card URL과 공통 API 키·local rate limit을 비교합니다.
A2A 인식 설정 자체는 skill 인가나 Task 소유권 정책이 아닙니다.
