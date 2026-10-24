# 5단계 — 요청 처리

[문서 안내](../README.md) · [Compose 선택](COMPOSE.md) · [로드맵](../POLICY-ROADMAP.md)

실행 위치: `agentgateway/single/` 또는 `agentgateway/ha/` (별도 표시 우선). 최초 준비는 각 모드 README를 따릅니다. 검증 기록은 v1.6.0의 과거 실행 결과입니다.

`config-request-processing.yaml`과 `compose-processing.yml`을 함께 사용합니다.
동일한 작은 서버 이미지를 별도 `mirror-demo` 서비스로 빌드하며, 미러 서버는 수신 기록을 남기고 503을 반환합니다.
외부 포트는 추가하지 않습니다. `/processing/*`는 HTTP 실험 경로이며 일반 MCP 도구에는 적용하지 않습니다.

| 경로 | 확인 결과 |
| --- | --- |
| `/processing/headers` | 요청 add는 기존 값에 추가, set은 교체, remove는 제거; 응답 헤더도 변경 |
| `/processing/body` | CEL로 요청 본문을 `Hello sample`로 교체하고 backend 수신 내용 확인 |
| `/processing/response` | 응답 본문과 Content-Type 교체 |
| `/rewrite-source` | `/processing/rewritten`으로 경로 교체, query 유지 |
| `/processing/mirror` | 100% 미러링, POST 한 번 수신, 미러 503에도 원본 200 유지 |
| `/processing/delay` | 200ms 지연 주입 후 backend 전달 |
| `/processing/delay-timeout` | 500ms 지연 중 100ms 전체 timeout으로 504, 600ms 후에도 backend 수신 0회 |

**미러링 제한:** 고정 v1.6.0 이미지와 이 설정에서 원본은 `mirror payload`를 수신했지만 미러 본문은 빈 문자열이었습니다.
테스트는 이 관찰을 명시적으로 고정합니다. POST 본문의 완전 복제에 성공한 예제가 아니므로 본문 기반 shadow 검증에 그대로 사용하지 않습니다.
메서드·경로·query 전달과 오류 격리만 확인했습니다. 아래 추가 조사에서 v1.6.0 구현상 본문 미지원과 buffer 정책으로도 해결되지 않음을 확인했습니다.

```bash
# single/ 또는 ha/에서
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
AGENTGATEWAY_CONFIG=./config-request-processing.yaml docker compose -f docker-compose.yml -f compose-processing.yml config --quiet
AGENTGATEWAY_CONFIG=./config-request-processing.yaml docker compose -f docker-compose.yml -f compose-processing.yml up -d --build --wait

# single/에서
python3 ../shared/test-request-processing.py http://127.0.0.1:4000
# ha/에서
python3 ../shared/test-request-processing.py http://127.0.0.1:14001
python3 ../shared/test-request-processing.py http://127.0.0.1:14002

# 복합 정책 복원 후 실험용 미러 서버 정지 (데이터 삭제 없음)
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose -f docker-compose.yml -f compose-processing.yml stop mirror-demo
```

- 제약: HTTP route 기준이며 host rewrite, 원본 본문을 읽는 CEL, 스트리밍 본문은 미검증입니다. 장애 주입은 고정 지연만 포함합니다.
- 위험: 미러링은 별도 서버에도 요청을 전달하므로 실제 업무 서버를 연결하면 부작용이 발생할 수 있습니다. 샘플의 내부 테스트 서버로 한정합니다.
- 예외: 카운터는 프로세스별 최근 1,000개 ID이며 재시작하면 초기화됩니다. 본문은 64 KiB로 제한하고 응답 헤더는 테스트용 허용 목록만 노출합니다. 실제 자격증명이나 업무 본문을 probe에 보내지 않습니다.

공식 근거: [Header manipulation](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/traffic-management/manipulation/),
[Transformations](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/traffic-management/transformations/),
[Rewrites](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/traffic-management/rewrites/),
[Mirroring](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/resiliency/mirroring/),
[Fault injection](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/resiliency/fault-injection/).

### 실행 기록 — 5단계 (2026-10-19)

싱글 및 HA 두 인스턴스에서 각 7개, 총 21개 검증을 통과했습니다(미러 빈 본문 관찰 포함).
지연 주입 응답은 약 207~208ms, 지연 중 timeout은 약 102~106ms였습니다. 로컬 관찰값입니다.
이미지 빌드의 Node 테스트 4개와 기존 MCP echo/add smoke test도 싱글·HA에서 통과했습니다.
후속 검증은 [6단계 전역 Rate Limit](GLOBAL-RATELIMIT.md)에 기록했습니다. 미러 본문 지원 여부는 아래 추가 조사 결과를 참고합니다.

### 미러 본문 추가 조사 — 2026-10-19

**결론: v1.6.0 내장 requestMirror는 본문을 복제하지 않습니다. 설정 누락이 아닙니다.**
고정 태그의 [httpproxy.rs L1138–1163](https://github.com/agentgateway/agentgateway/blob/v1.6.0/crates/agentgateway/src/proxy/httpproxy.rs#L1138-L1163)에서
원본 요청을 head/body로 분리한 후 미러 요청에는 `http::Body::empty()`를 넣습니다.
[send_mirror L4515–4529](https://github.com/agentgateway/agentgateway/blob/v1.6.0/crates/agentgateway/src/proxy/httpproxy.rs#L4515-L4529)는 Content-Length도 제거합니다.
따라서 요청 버퍼링으로 원본을 보존해도 이 미러 생성 경로가 본문을 버립니다.

`/processing/mirror-buffered` 비교 경로에 아래 정책을 추가해 확인했습니다.
이 경로는 해결책이 아니라 제한 재현용입니다.

```yaml
buffer:
  request:
    maxBytes: 65536
    failureMode: failClosed
```

싱글 4000, HA 14001/14002 각각에서 다음을 확인했습니다.

- 버퍼링 없음/있음 모두: 원본은 한글 포함 POST 본문을 그대로 수신, 미러는 POST·경로·query를 수신하지만 본문은 빈 문자열.
- 명시적 버퍼 64 KiB 초과: 413, 원본·미러 수신 횟수 모두 0. 버퍼 설정 자체가 실제 적용됨을 확인.
- 기존 헤더·본문 변환, rewrite, delay·timeout까지 포함해 인스턴스당 9개 확인, 총 27개 완료. 이 중 6개는 미러 제한의 재현이며 본문 복제 성공을 의미하지 않습니다.

공식 [Body buffering](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/traffic-management/buffer/)의
버퍼 기능과 미러 본문 복제는 별개입니다. 테스트 출력도 해당 항목을 `LIMITATION CONFIRMED`로 구분합니다.

권장: 현재 샘플은 v1.6.0을 유지하고 내장 미러링을 본문 없는 요청의 관찰에 한정합니다.
이유: 코드와 세 인스턴스의 실행 결과가 일치하며 설정만으로 해결되지 않습니다.
트레이드오프: POST JSON/MCP 본문의 shadow 검증은 제공하지 못합니다.
전환 조건: 본문이 필요한 미러 시나리오를 추가할 때 별도 복제 프록시를 검토하거나, 향후 버전에서 원본·미러 본문 일치 테스트를 통과한 뒤 전환합니다.
이번 조사에서 별도 프록시 도입이나 agentgateway 소스 패치는 하지 않았습니다.

- 제약: 미러 body 미지원은 확인한 v1.6.0 기준입니다. 향후 릴리스까지 동일하다고 단정하지 않습니다.
- 위험: 버퍼만 추가하면 메모리 사용과 전체 본문 수신 대기는 늘어나지만 미러 본문은 보존되지 않습니다.
- 예외: 스트리밍/SSE·업그레이드 요청과 외부 복제 프록시는 이번에 검증하지 않았습니다.

### 사용자 결정 — 2026-10-19

미러 본문 미지원 제한을 유지하고 6단계 전역 rate limit으로 진행하기로 했습니다.
본문 복제 프록시 추가나 agentgateway 패치는 진행하지 않습니다. 이 결정은 현재 샘플 범위에 적용합니다.
