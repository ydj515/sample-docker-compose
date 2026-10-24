# 2단계 실행 — 적용 단계와 MCP 대상별 덮어쓰기

[문서 안내](../README.md) · [Compose 선택](COMPOSE.md) · [로드맵](../POLICY-ROADMAP.md)

실행 위치: `agentgateway/single/` 또는 `agentgateway/ha/` (별도 표시 우선). 최초 준비는 각 모드 README를 따릅니다. 검증 기록은 v1.6.0의 과거 실행 결과입니다.

각 모드의 `config-policy-stages.yaml`과 공통 `test-policy-stages.py`를 사용합니다.
기본 MCP의 echo/add는 유지하고 UI/HTTP 포트에 두 가지 검증 경로를 추가합니다.

| 경로 | 확인 내용 |
| --- | --- |
| `/inspect-headers` | 게이트웨이 변환 → 라우트 변환 → HTTP 백엔드 헤더 수정 |
| `/mcp-inheritance` | 공통 정책만 쓰는 inherited 대상과 자체 정책을 쓰는 overridden 대상 비교 |

```bash
# single/ 또는 ha/에서
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
AGENTGATEWAY_CONFIG=./config-policy-stages.yaml docker compose config --quiet
AGENTGATEWAY_CONFIG=./config-policy-stages.yaml docker compose up -d --build --wait

# single/에서
python3 ../shared/test-policy-stages.py http://127.0.0.1:4000
# ha/에서
python3 ../shared/test-policy-stages.py http://127.0.0.1:14001
python3 ../shared/test-policy-stages.py http://127.0.0.1:14002

# 기존 복합 정책으로 복원
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
```

### 예상 결과와 의미

HTTP 요청은 클라이언트에서 `x-policy-winner: client`를 보냅니다.
게이트웨이는 `x-policy-gateway: gateway`를 기록하고 라우트는 이 값을 읽어 `x-policy-route: gateway>route`를 만듭니다.
백엔드는 `x-policy-backend: backend`를 추가하고 충돌 헤더를 `x-policy-winner: backend`로 최종 변경합니다.
각 단계의 고유 헤더가 함께 남으므로 백엔드 정책이 상위 단계의 실행 자체를 없애는 것은 아닙니다.

MCP 공통 정책에는 `x-policy-winner: common`, `x-policy-common: common-only`를 설정합니다.
대상에 자체 정책이 없는 inherited는 둘 다 받습니다.
overridden에는 `x-policy-winner: target`만 설정하며, 해당 대상은 target 값을 받고 `x-policy-common`은 받지 않습니다.
**v1.6.0의 이 구성에서는 대상 requestHeaderModifier가 공통 requestHeaderModifier 전체를 대체합니다. 개별 헤더를 합치는 동작으로 가정하면 안 됩니다.**

테스트 서버는 `/mcp-inspect`에서 `inspect_headers` 도구를 제공하며, gateway의 `prefixMode: always`를 거치면
`inherited_inspect_headers`, `overridden_inspect_headers`로 노출됩니다.
HTTP와 MCP 검증 응답에는 명시한 5개 `x-policy-*` 헤더만 포함합니다. 인증·쿠키 등 임의 헤더는 반환하거나 로그로 출력하지 않습니다.

- 제약: HTTP 단계 테스트는 transformation과 requestHeaderModifier 조합으로 확인한 결과입니다.
- 위험: 대상별 정책 추가 시 공통 정책의 헤더를 보존하려면 필요한 값을 대상 정책에도 명시해야 합니다.
- 예외: 다른 정책 종류의 병합 방식, 같은 단계의 인증·권한·rate limit 실행 순서는 이 결과로 일반화하지 않습니다. 3단계에서 별도 확인합니다.

## 실행 기록 — 2단계 (2026-10-19 정리)

- 서버 이미지 빌드 중 Node.js 테스트 4개 통과: 기존 도구·오류·HTTP 검증과 probe 헤더 허용 목록 검증.
- 싱글 및 HA 두 인스턴스에서 test-policy-stages.py 통과: 단계별 헤더 유지, 충돌 값 변경, 공통 정책 상속 및 대상 정책 전체 대체 확인.
- 기존 MCP smoke test도 싱글·HA에서 통과했습니다. HA 컨테이너 재생성 직후 첫 호출은 502였고 후속 재실행은 통과했습니다. 무중단 재생성의 증거로 해석하지 않습니다.
- 대상 정책의 x-policy-winner는 target이며, 공통 정책에만 있는 x-policy-common은 대상 응답에 없었습니다.
- 후속 검증은 [3단계 API Key](API-KEY.md)에 기록했습니다.
