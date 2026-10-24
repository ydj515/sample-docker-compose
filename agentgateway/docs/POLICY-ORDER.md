# 1단계 — 조건부 정책 선택 순서

[문서 안내](../README.md) · [Compose 선택](COMPOSE.md) · [로드맵](../POLICY-ROADMAP.md)

실행 위치: `agentgateway/single/` 또는 `agentgateway/ha/` (별도 표시 우선). 최초 준비는 각 모드 README를 따릅니다. 검증 기록은 v1.6.0의 과거 실행 결과입니다.

각 모드 폴더의 `config-policy-order.yaml`은 기존 기본 MCP 설정에 우선순위 실험용 HTTP 경로만 추가합니다.
rate limit이나 역할별 권한과 섞지 않아 조건 선택 결과를 따로 관찰할 수 있습니다.

```bash
# single/ 또는 ha/에서, 최초 데이터 폴더 준비는 각 README 참고
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
AGENTGATEWAY_CONFIG=./config-policy-order.yaml docker compose config --quiet
AGENTGATEWAY_CONFIG=./config-policy-order.yaml docker compose up -d --wait

# single/에서
python3 ../shared/test-policy-order.py http://127.0.0.1:4000
# ha/에서 각 인스턴스 검증
python3 ../shared/test-policy-order.py http://127.0.0.1:14001
python3 ../shared/test-policy-order.py http://127.0.0.1:14002

# 직전에 사용하던 복합 정책 복원
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
```

`/policy-order/admin`은 admin 규칙과 일반 규칙에 모두 일치하지만 첫 규칙의 403만 반환해야 합니다.
`/policy-fallback/other`는 조건 불일치 후 마지막 fallback의 418을 반환해야 합니다.
`/policy-no-fallback/other`는 조건에 맞지 않아 MCP 테스트 서버로 전달되고 그 서버의 JSON 404를 반환해야 합니다.

- 제약: HA의 1단계 테스트는 각 UI/HTTP 포트에서 실행하며 MCP 로드밸런서 장애 전환 검증은 아닙니다.
- 위험: 광범위한 conditional 항목을 앞에 두면 뒤의 구체적인 정책이 적용되지 않습니다.
- 예외: 같은 단계에서 서로 다른 정책 종류의 실행 순서와 권한·rate limit 충돌 순서는 이 테스트로 증명하지 않습니다.

## 근거 문서

- [정책 적용 위치](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/policies/attachment/)
- [조건부 정책](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/policies/conditional-policies/)
- [MCP 대상별 정책](https://agentgateway.dev/docs/standalone/latest/documentation/mcp/mcp-target-policies/)
- [현재 구현된 정책 실습](../shared/POLICIES.md)

## 실행 기록 — 1단계

2026-10-18 로컬 Docker에서 싱글 7개, HA 인스턴스별 7개씩 총 21개 HTTP 상태·본문 검증을 통과했습니다.
동시 일치 시 첫 규칙 적용, 마지막 fallback 적용, 미일치 시 backend 전달을 확인했습니다.
후속 검증은 [2단계 적용 단계와 설정 충돌](POLICY-STAGES.md)에 기록했습니다.
