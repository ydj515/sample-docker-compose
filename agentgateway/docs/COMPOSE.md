# Compose 파일 선택 안내

[문서 안내](../README.md) · [single 실행](../single/README.md) · [HA 실행](../ha/README.md) · [로드맵](../POLICY-ROADMAP.md)

각 모드에서 `docker-compose.yml`이 기본 구성이고, `compose-*.yml`은 실습에 필요한 서비스·포트·인증서 마운트를 더하는 파일입니다.
**실습 하나를 고른 뒤 기본 Compose와 그 실습의 추가 파일을 함께 사용합니다.** 모든 추가 파일을 한꺼번에 합치는 구성이 아닙니다.

## 설정 파일과 Compose의 역할

- `AGENTGATEWAY_CONFIG`: Gateway에 마운트할 정책 설정 하나를 선택합니다. 기본값은 `./config.yaml`입니다.
- `-f docker-compose.yml -f compose-…yml`: 기본 서비스에 실습용 구성을 추가합니다. 아래 표의 순서대로 지정합니다.
- `config-*.template.yaml`: 생성 스크립트의 입력입니다. Gateway에는 생성된 `data/config-*.yaml`을 지정합니다.
- 같은 모드의 실습은 같은 Compose 프로젝트와 포트를 사용하므로 전환 실행합니다. single과 HA는 프로젝트명·기본 포트가 달라 동시에 실행할 수 있습니다.

명령은 `agentgateway/single/` 또는 `agentgateway/ha/`에서 실행합니다. 데이터 디렉터리와 UID/GID 준비는 각 모드 README를 먼저 따릅니다.

## 추가 Compose 없이 설정만 선택하는 실습

| 실습 | `AGENTGATEWAY_CONFIG` | 실행·검증 안내 |
| --- | --- | --- |
| 기본 MCP | `./config.yaml` | [single](../single/README.md), [HA](../ha/README.md) |
| Rate limit·도구 권한 | `./config-policies.yaml` | [기본 정책](../shared/POLICIES.md) |
| 복합 정책 | `./config-multi-policies.yaml` | [복합 정책](../shared/POLICIES.md#여러-정책규칙-동시-적용) |
| 조건부 선택 순서 | `./config-policy-order.yaml` | [1단계](POLICY-ORDER.md) |
| 적용 단계·대상별 덮어쓰기 | `./config-policy-stages.yaml` | [2단계](POLICY-STAGES.md) |
| Timeout·Retry | `./config-resilience.yaml` | [4단계](RESILIENCE.md) |

예를 들어 조건부 선택 실습은 다음과 같이 전환합니다.

```bash
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
AGENTGATEWAY_CONFIG=./config-policy-order.yaml docker compose config --quiet
AGENTGATEWAY_CONFIG=./config-policy-order.yaml docker compose up -d --build --wait
```

## 추가 Compose가 필요한 실습

표의 파일은 모두 **`-f docker-compose.yml` 뒤에 `-f`로 추가**합니다. `없음`은 기본 Compose만 사용한다는 뜻입니다.
HA의 `compose-auth.yml`은 아래 실습에서 인스턴스별 MCP 검증을 위해 사용합니다.

| 실습 | 설정 파일 (`AGENTGATEWAY_CONFIG`) | single 추가 파일 | HA 추가 파일 순서 | 준비·실행·복원 |
| --- | --- | --- | --- | --- |
| API Key | `./data/config-auth.yaml` | 없음 | `compose-auth.yml` | [키 생성부터 실행](API-KEY.md) |
| 요청 처리·미러링 | `./config-request-processing.yaml` | `compose-processing.yml` | `compose-processing.yml` | [요청 처리](REQUEST-PROCESSING.md) |
| 전역 Rate Limit | `./config-global-ratelimit.yaml` | `compose-global-ratelimit.yml` | `compose-global-ratelimit.yml` → `compose-auth.yml` | [공유 카운터](GLOBAL-RATELIMIT.md) |
| HTTP·HTTPS | `./config-tls.yaml` | `compose-tls.yml` | `compose-tls.yml` | [CA·인증서 생성](TLS.md) |
| mTLS | `./config-mtls.yaml` | `compose-mtls.yml` | `compose-mtls.yml` | [인증서 생성·갱신](MTLS.md) |
| 외부 인가 | `./data/config-extauthz.yaml` | `compose-extauthz.yml` | `compose-extauthz.yml` → `compose-auth.yml` | [키·설정 생성](EXTAUTHZ.md) |
| OAuth / OIDC | `./config-oidc.yaml` | `compose-oidc.yml` | `compose-oidc.yml` → `compose-auth.yml` | [realm·자격 증명 생성](OIDC.md) |
| OAuth+mTLS | `./config-oidc-mtls.yaml` | `compose-mtls.yml` → `compose-oidc-mtls.yml` | `compose-mtls.yml` → `compose-oidc-mtls.yml` | [인증서·통합 realm 준비](../shared/AUTH-COMPARISON.md) |
| JWKS 회전 | `./config-jwks-rotation.yaml` | `compose-mtls.yml` → `compose-jwks-rotation.yml` | `compose-mtls.yml` → `compose-jwks-rotation.yml` | [mTLS 인증서 준비 후 회전 실습](../shared/AUTH-LIFECYCLE.md) |
| Mock A2A | `./data/config-a2a.yaml` | `compose-a2a.yml` | `compose-auth.yml` → `compose-a2a.yml` | [키 생성·A2A 실행](../shared/A2A.md) |

OAuth+mTLS는 `compose-oidc.yml`을 함께 넣지 않습니다. 통합용 파일이 별도 realm과 volume을 가진 Keycloak을 정의합니다.
JWKS 회전은 Keycloak 대신 `jwks-fixture`를 사용합니다. 두 실습 모두 TLS 파일이 아닌 `compose-mtls.yml`을 먼저 조합합니다.

추가 파일을 사용하는 예시는 다음과 같습니다. 인증 자료가 필요한 실습은 위 링크의 준비 절차를 먼저 실행해야 합니다.

```bash
# single/ 또는 ha/: 요청 처리 실습
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
AGENTGATEWAY_CONFIG=./config-request-processing.yaml docker compose \
  -f docker-compose.yml -f compose-processing.yml config --quiet
AGENTGATEWAY_CONFIG=./config-request-processing.yaml docker compose \
  -f docker-compose.yml -f compose-processing.yml up -d --build --wait
```

## 각 파일이 추가하는 것

아래 링크는 실제 Compose 파일입니다. single은 기본 파일 포함 10개, HA는 11개입니다.

| 파일 | single / HA | 추가·변경 내용 |
| --- | --- | --- |
| `docker-compose.yml` | [single](../single/docker-compose.yml) / [HA](../ha/docker-compose.yml) | single: Gateway 1개·MCP 서버. HA: Gateway 2개·Nginx·MCP 서버 |
| `compose-auth.yml` | HA [파일](../ha/compose-auth.yml)만 있음 | Gateway별 직접 MCP 포트 16001/16002. 인증 정책이나 인증 서버는 추가하지 않음 |
| `compose-processing.yml` | [single](../single/compose-processing.yml) / [HA](../ha/compose-processing.yml) | 내부 미러 서버 `mirror-demo` |
| `compose-global-ratelimit.yml` | [single](../single/compose-global-ratelimit.yml) / [HA](../ha/compose-global-ratelimit.yml) | `ratelimit`·`redis` 및 카운터 volume. 호스트 포트 없음 |
| `compose-tls.yml` | [single](../single/compose-tls.yml) / [HA](../ha/compose-tls.yml) | HTTPS 포트·인증서 마운트·`mcp-tls`; HA는 Nginx TLS 설정도 교체 |
| `compose-mtls.yml` | [single](../single/compose-mtls.yml) / [HA](../ha/compose-mtls.yml) | mTLS 포트·인증서 마운트·`mcp-mtls`; HA는 Nginx mTLS 설정도 교체 |
| `compose-extauthz.yml` | [single](../single/compose-extauthz.yml) / [HA](../ha/compose-extauthz.yml) | 내부 인가 서버 `authz` |
| `compose-oidc.yml` | [single](../single/compose-oidc.yml) / [HA](../ha/compose-oidc.yml) | Keycloak·단독 realm import·`oidc-data` volume |
| `compose-oidc-mtls.yml` | [single](../single/compose-oidc-mtls.yml) / [HA](../ha/compose-oidc-mtls.yml) | Keycloak·통합 realm import·`oidc-mtls-data` volume; mTLS 파일과 조합 |
| `compose-jwks-rotation.yml` | [single](../single/compose-jwks-rotation.yml) / [HA](../ha/compose-jwks-rotation.yml) | 로컬 서명 키 발급·JWKS 서버 `jwks-fixture`; mTLS 파일과 조합 |
| `compose-a2a.yml` | [single](../single/compose-a2a.yml) / [HA](../ha/compose-a2a.yml) | 내부 Mock A2A 서버 `a2a-demo` |

## 호스트 포트 찾기

모든 공개 포트는 loopback에 바인딩합니다. 기본 MCP/UI 포트는 각 모드 `.env.example`에서 변경할 수 있지만, 추가 Compose의 아래 포트는 파일에 고정되어 있습니다.

| 용도 | single | HA |
| --- | --- | --- |
| 기본 MCP / A2A | 3000 | Nginx 13000 |
| UI / HTTP 정책 실험 | 4000 | Gateway 직접 14001 / 14002 |
| `compose-auth.yml` 직접 MCP / A2A | 해당 없음 | 16001 / 16002 |
| TLS 또는 mTLS | 3443 | Nginx 13443, Gateway 직접 14401 / 14402 |
| Keycloak (단독 또는 통합) | 18080 | 28080 |
| JWKS fixture | 18090 | 28090 |

포트가 같아도 경로는 다릅니다. 기본·OIDC는 `/mcp`, TLS 비교는 `/mcp/plain`·`/mcp/tls`, mTLS 계열은 `/mcp/mtls`, A2A는 `/a2a`·`/raw`를 사용합니다.
A2A 설정은 기존 MCP listener를 대체하며, mTLS 계열은 MCP 평문 접근을 제공하지 않습니다. UI 매핑이 남아 있어도 해당 실습에서 UI를 제공하거나 보호한다는 뜻은 아닙니다.

## 전환·중지·복원

`config --quiet`는 Compose 구성 검사입니다. Gateway 정책의 유효성, 인증 자료 존재, 실제 요청 성공까지 검증하지는 않습니다.
기동 후에는 각 실습 문서에 연결된 테스트를 실행합니다.

실습 중 `ps`, `logs`, `stop`에도 기동할 때의 `-f` 조합과 설정 환경변수를 사용합니다.
기본 설정으로 돌아갈 때는 추가 파일을 빼고 설정을 명시합니다.

```bash
# single/ 또는 ha/: 최초 기본 MCP 설정으로 복원
AGENTGATEWAY_CONFIG=./config.yaml docker compose up -d --wait
unset AGENTGATEWAY_CONFIG MTLS_CERT_DIR
```

기존 상세 문서의 복원 명령은 대개 `config-multi-policies.yaml`을 선택합니다. 이는 최초 기본 설정과 다른 **복합 정책 실습 상태**입니다.
기본 MCP는 `smoke-test.py`, 복합 정책은 `test-multi-policies.py`로 확인합니다.

추가 파일을 빼도 이전 실습의 보조 컨테이너가 자동으로 모두 정지되는 것은 아닙니다. 각 실습 문서의 복원 절차에 따라 해당 파일 조합으로 보조 서비스를 `stop`합니다.
데이터·인증서·키·named volume은 보존합니다. OAuth 단독과 통합은 같은 `keycloak` 서비스명과 호스트 포트를 사용하므로 전환 실행합니다.

- 제약: 한 모드에서 여러 실습을 독립적으로 동시 기동하는 구성은 제공하지 않습니다.
- 위험: 이전 셸의 `AGENTGATEWAY_CONFIG` 또는 `MTLS_CERT_DIR`가 남으면 의도와 다른 정책·인증서 세대를 선택할 수 있습니다.
- 예외: HA 직접 MCP 포트는 Nginx를 우회합니다. 직접 호출 성공만으로 로드밸런서 장애 전환까지 검증한 것은 아닙니다.
