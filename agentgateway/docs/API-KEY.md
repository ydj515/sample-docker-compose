# 3단계 — API Key 인증과 실패 조건 충돌

[문서 안내](../README.md) · [Compose 선택](COMPOSE.md) · [로드맵](../POLICY-ROADMAP.md)

실행 위치: `agentgateway/single/` 또는 `agentgateway/ha/` (별도 표시 우선). 최초 준비는 각 모드 README를 따릅니다. 검증 기록은 v1.6.0의 과거 실행 결과입니다.

검증 버전은 v1.6.0입니다. 이번 단계는 API Key strict 인증을 사용합니다. JWT/JWKS의 서명·만료 검증은 포함하지 않습니다.
`config-auth.template.yaml`의 해시 자리표시자를 `prepare-auth.py`로 채워 `data/config-auth.yaml`을 생성합니다.
원본 실습 키는 Git 제외 경로의 `data/auth-keys.json`에 권한 0600으로 저장하고, 게이트웨이 설정에는 SHA-256 해시만 넣습니다.
이미 키 파일이 있으면 재사용하며 키 값을 출력하지 않습니다. 생성 설정도 Git 제외 경로에 저장합니다.

### 확인한 결과

| 조건 | 관찰 결과 |
| --- | --- |
| 인증 누락·틀린 키 | 버킷 소진 전후 모두 HTTP 401 |
| 정상 키, 권한 없는 add | MCP 오류 `Unknown tool: add` |
| 정상 키, 허용 도구, 버킷 소진 | HTTP 200 안의 `isError: true`, rate limit exceeded |
| 정상 키, add 권한 없음 + 버킷 소진 | rate limit 오류가 반환됨 |
| viewer 키 + 위조 x-demo-role: calculator | add 여전히 거부 |
| calculator 메타데이터가 연결된 유효 키 | echo와 add 모두 허용 |

초기화와 initialized 알림을 보낸 뒤, 20개 버킷에서 정상 echo는 기준 18회 허용됐습니다.
인증 실패 요청 10개를 추가한 비교군도 18회였고, 인증된 add 권한 거부 요청 5개를 추가한 비교군은 13회였습니다.
따라서 이 구성에서는 인증된 권한 거부 호출도 요청 제한을 소비하며, 버킷 소진 시 권한 거부보다 제한 초과 응답을 관찰합니다.
이 결과는 요청별 적용 순서를 관찰한 것이며 모든 정책 종류·적용 위치에 대한 보편적 우선순위는 아닙니다.
인증 실패가 어떤 내부 상태에도 영향을 주지 않는다는 의미가 아니라, 비교한 인증 사용자별 버킷 용량에 차이가 없었다는 의미입니다.

### 실행

```bash
# single/에서, 최초 data 디렉터리 준비는 기존 README 참고
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
python3 ../shared/prepare-auth.py .
AGENTGATEWAY_CONFIG=./data/config-auth.yaml docker compose up -d --wait
# 기존 카운터를 초기화하므로 실행 중 요청은 끊길 수 있습니다.
docker compose restart agentgateway
python3 ../shared/test-auth-order.py http://127.0.0.1:3000/mcp data/auth-keys.json
```

```bash
# ha/에서
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
python3 ../shared/prepare-auth.py .
AGENTGATEWAY_CONFIG=./data/config-auth.yaml docker compose -f docker-compose.yml -f compose-auth.yml up -d --wait
docker compose -f docker-compose.yml -f compose-auth.yml restart gateway-1 gateway-2
python3 ../shared/test-auth-order.py http://127.0.0.1:16001/mcp data/auth-keys.json
python3 ../shared/test-auth-order.py http://127.0.0.1:16002/mcp data/auth-keys.json
```

HA override는 정확한 인스턴스별 카운터 비교를 위해 127.0.0.1:16001/16002에 MCP 포트를 추가합니다.
기본 LB 포트 13000도 유지하지만 이번 정량 비교는 LB를 우회합니다. 이 결과는 HA 전역 카운터 검증이 아닙니다.
반복 테스트 전 게이트웨이를 다시 시작합니다. 재시작 없이 즉시 반복하면 이미 소진된 버킷 때문에 실패합니다.
다른 클라이언트가 같은 키로 요청하거나 테스트가 충전 간격 60초를 넘으면 횟수 비교에 영향을 줄 수 있습니다.

```bash
# single/ 또는 ha/에서 복합 정책으로 복원
# HA에서는 override 파일을 빼면 추가 직접 포트도 제거됩니다.
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
```

- 제약: 실습 키는 권한·순서 검증용입니다. 운영 자격증명과 혼용하지 않습니다. API Key는 사용자 메타데이터와 연결되어 있고 임의 역할 헤더는 권한 판정에 사용하지 않습니다.
- 위험: 상위 인증 실패의 정확한 응답, MCP tool 오류, HTTP 상태를 구분해야 합니다. HTTP 200만으로 성공을 판정하면 제한 초과를 놓칩니다.
- 예외: JWT 검증, 키 폐기·회전, TLS, HA 공유 제한, 다른 정책 단계의 동시 실패는 이번 검증에 포함하지 않습니다.

공식 근거: [API Key authentication](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/apikey-authn/),
[v1.6.0 keyHash 구현](https://github.com/agentgateway/agentgateway/blob/v1.6.0/crates/agentgateway/src/http/apikey.rs).

### 실행 기록 — 3단계 (2026-10-19)

싱글 및 HA 두 인스턴스에서 동일한 18/18/13 결과, 인증 실패 401, 위조 역할 무효, calculator 허용,
권한 거부와 제한 초과 동시 조건의 rate limit 응답을 검증했습니다. 이 단계에서는 JWT를 검증하지 않았습니다. 후속 JWT 검증은 [OAuth/OIDC](OIDC.md)와 [JWKS 회전](../shared/AUTH-LIFECYCLE.md)에 기록했습니다.
