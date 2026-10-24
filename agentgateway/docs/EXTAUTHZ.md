# 7단계 C — 외부 인가 (2026-10-19)

[문서 안내](../README.md) · [Compose 선택](COMPOSE.md) · [로드맵](../POLICY-ROADMAP.md)

실행 위치: `agentgateway/single/` 또는 `agentgateway/ha/` (별도 표시 우선). 최초 준비는 각 모드 README를 따릅니다. 검증 기록은 v1.6.0의 과거 실행 결과입니다.

`config-extauthz.template.yaml`에서 실행 설정을 생성하고 `compose-extauthz.yml`을 함께 사용합니다.
Node 내장 HTTP 모듈만 사용하는 `shared/authz-server`를 Compose에서 직접 빌드합니다.
HTTP ExtAuthz 방식이며 OPA·gRPC·외부 SaaS 의존성은 추가하지 않습니다.

```text
client → Gateway API Key 인증 → HTTP 외부 인가 서비스
                      └── 허용 → HTTP/MCP backend
                      └── 거부·연결 실패·timeout → 차단
```

기존 `prepare-auth.py`에 `extauthz` 변형을 추가했습니다. 기본 인자와 3단계 auth 생성 동작은 유지합니다.
키가 있으면 재사용하며, 실행 설정에는 키 원문 대신 SHA-256 hash와 user/role metadata만 기록합니다.
사용자 키 파일은 `data/auth-keys.json`, 실행 설정은 `data/config-extauthz.yaml`이며 Git 제외·소유자 전용 권한입니다.

### 판정 규칙

| 대상 | viewer | calculator |
| --- | --- | --- |
| HTTP GET `/processing/authz` | 허용 | 허용 |
| HTTP POST `/processing/authz` | 거부 | 허용 |
| MCP initialize·initialized·ping·tools/list | 허용 | 허용 |
| MCP echo 호출 | 허용 | 허용 |
| MCP add 호출 | 거부 | 허용 |
| 알 수 없는 역할·경로·MCP 메서드/도구·잘못된 JSON·batch | 거부 | 거부 |

`x-authz-role`, `x-demo-role` 같은 사용자 헤더를 신뢰하지 않습니다.
Gateway에서 API Key를 검증한 뒤 `apiKey.role/user`를 CEL로 읽어 인가 요청 헤더를 생성합니다.
`includeRequestHeaders: []`로 원본 요청 헤더를 인가 서비스에 복사하지 않습니다.
`includeRequestBody`로 전달한 MCP JSON을 인가 서비스가 해석해 도구 호출을 판정합니다.

이 실습은 **호출 차단**을 보여 줍니다. viewer의 tools/list에도 add가 보이지만 실제 호출은 403입니다.
허용된 도구만 목록에 노출하려면 별도의 `mcpAuthorization` 정책이 필요하며, 여기서는 외부 인가만 분리해 관찰합니다.
HTTP 방식의 ExtAuthz에는 결정 캐시를 설정하지 않았고 요청마다 서비스가 판정합니다.

### 응답·본문·실패 처리

- 인가 응답의 `x-policy-winner`만 backend 요청에 복사합니다. 사용자 제공 동명 헤더가 `external-authz`로 교체되는지 검증합니다.
- 본문 최대 1,024 bytes, `allowPartialMessage: false`. 초과 시 413이며 backend 수신은 0회입니다. 실제 서비스에 맞춰 크기를 조정해야 합니다.
- `failureMode: deny`를 명시합니다. 이 정책의 값은 `deny`이며 remoteRateLimit의 `failClosed`와 필드값을 혼동하지 않습니다.
- 인가 HTTP 요청 timeout·TCP 연결 timeout은 각각 100ms입니다. 실습용 값이며 운영 지연 예산을 측정해 조정해야 합니다.
- 인가 서비스가 403을 반환하면 HTTP 403, 명시적으로 503을 반환하면 HTTP 503이 전달됐습니다.
- 500ms 지연 응답과 서비스 정지는 v1.6.0에서 약 100ms 뒤 HTTP 403 `external authorization failed`로 차단됐습니다.
- MCP viewer add 거부는 HTTP 403입니다. 앞선 rate limit의 HTTP 200 + isError 형태와 다릅니다.

실패 실험용 `/processing/error`, `/processing/slow`도 정상 API Key가 필요합니다.
HTTP backend의 요청 ID별 수신 기록으로 차단 요청이 전달되지 않았는지 확인합니다.
`/authz-stats?id=...`는 loopback UI 포트에 있는 테스트용 수신 기록 조회 경로이며 인증을 적용하지 않았습니다.
개인정보·실제 업무 본문을 이 실험 경로에 보내지 않습니다.

### 실행

```bash
# single/ 또는 ha/에서
python3 ../shared/prepare-auth.py . extauthz
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
export AGENTGATEWAY_CONFIG=./data/config-extauthz.yaml
docker compose -f docker-compose.yml -f compose-extauthz.yml config --quiet
docker compose -f docker-compose.yml -f compose-extauthz.yml up -d --build --wait

# single/에서
python3 ../shared/test-extauthz.py http://127.0.0.1:4000 http://127.0.0.1:3000/mcp ./data/auth-keys.json --lifecycle .

# ha/에서: replica별 검증용 직접 MCP 포트 추가
docker compose -f docker-compose.yml -f compose-extauthz.yml -f compose-auth.yml up -d --wait
python3 ../shared/test-extauthz.py http://127.0.0.1:14001 http://127.0.0.1:16001/mcp ./data/auth-keys.json --lifecycle .
python3 ../shared/test-extauthz.py http://127.0.0.1:14002 http://127.0.0.1:16002/mcp ./data/auth-keys.json --lifecycle .
# Nginx 경유 MCP도 검증
python3 ../shared/test-extauthz.py http://127.0.0.1:14001 http://127.0.0.1:13000/mcp ./data/auth-keys.json

# 복합 정책 복원 및 인가 서비스 정지. 키·설정 파일은 보존.
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
docker compose -f docker-compose.yml -f compose-extauthz.yml stop authz
unset AGENTGATEWAY_CONFIG
```

`--lifecycle`은 해당 로컬 프로젝트의 authz 서비스를 잠시 정지한 뒤 `finally`에서 다시 시작합니다.
두 인스턴스가 같은 authz를 사용하므로 서비스 장애 테스트는 동시에 실행하지 않습니다.
외부 인가 서비스에 호스트 포트는 열지 않습니다. 비밀번호·키·요청 본문을 로그에 남기지 않습니다.

- 제약: 기존 TLS/mTLS와 분리한 HTTP 실험입니다. 사용자 인증은 API Key, 도구 호출 권한은 외부 인가가 담당합니다. mTLS 통합·JWT/OAuth·gRPC ExtAuthz·인가 결과 캐시는 후속 범위입니다.
- 위험: Compose 내부의 인가 서비스는 Gateway가 전달한 역할 metadata를 신뢰합니다. 운영에서는 접근 제어와 mTLS 등으로 이 신뢰 경계를 보호해야 합니다. 외부 인가 서비스는 HA에서도 단일 인스턴스라 장애 시 모든 보호 요청이 차단됩니다.
- 예외: 본문은 JSON 단일 MCP 요청 기준이며 batch는 거부합니다. 실험용 1 KiB 한도 때문에 큰 정상 요청도 차단될 수 있습니다. 내부 인가 판정과 인증 실패를 같은 에러로 일반화하지 않습니다.

공식 근거: [External authorization](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/external-authz/).

### 실행 기록 — 7단계 C

인가 서비스 Node 테스트 3개를 통과했습니다. single, HA 두 replica 각각에서 HTTP 허용·거부,
API Key 누락·위조 역할 헤더, 응답 헤더 교체, 본문 초과, 인가 서비스 503·timeout을 검증했습니다.
HTTP 차단 요청의 backend 수신은 모두 0회였고, timeout 후 600ms를 더 기다려도 전달되지 않았습니다.
인가 서비스 정지·복구도 각 replica에서 순차 검증했습니다. 정지 시 약 103~108ms에 403, 복구 후 정상 허용됐습니다.
잘못된 API Key의 401도 single/HA 두 replica에서 별도로 확인했습니다.
MCP는 single, HA 직접 포트, HA Nginx 경유에서 viewer echo 허용/add 거부와 calculator add 허용을 확인했습니다.

마무리: 기존 auth 설정 생성과 extauthz 변형의 hash 치환 결과가 각각 템플릿과 일치함을 확인했습니다.
세 gateway의 config mount는 `config-multi-policies.yaml`로 복원했고 양쪽 authz 컨테이너는 정지 상태입니다.
키·생성 설정은 보존했습니다. 복원 후 single/HA의 기존 복합 정책 권한·두 제한·refill 복구 테스트도 통과했습니다.
