# TASK-2: Phase 1 - MVP 수집 파이프라인 구축

## 목표

Codex telemetry를 중앙 OTel Collector로 수집하고, Loki/Prometheus/Grafana에서 기본 사용량을 확인한다.

---

## 시스템 구성

```text
Codex CLI
  -> OTLP Ingest Gateway
      -> OTel Collector
      -> Loki
      -> Prometheus
      -> Tempo (로컬 검증용 포함, 운영 필수는 Phase 6부터)
  -> Grafana

Normalizer / Cost Pipeline (향후)
  -> PostgreSQL (운영 필수는 Phase 4부터)
```

---

## 로컬 docker compose 기준 서비스 상세

`docker-compose.yml`은 아래 기준으로 작성한다.

| 서비스 | 포트 | 사용 Phase | 데이터 저장 위치 | 필수 여부 |
|--------|------|------------|------------------|----------|
| OTLP Ingest Gateway | 4318 | Phase 1 | 없음 | 필수 |
| OTel Collector | 13133 | Phase 1 | 없음 | 필수 |
| Loki | 3100 | Phase 1 | `loki-data` | 필수 |
| Prometheus | 9090 | Phase 1 | `prometheus-data` | 필수 |
| Grafana | 3000 | Phase 1 | `grafana-data` | 필수 |
| Alertmanager | 9093 | Phase 1 | `alertmanager-data` | 로컬 alert 검증용 권장 |
| Tempo | 3200 | Phase 6 | `tempo-data` | 로컬에서는 포함 권장 |
| PostgreSQL | 5432 | Phase 4 | `postgres17-data` | 로컬에서는 포함 권장 |

### 운영 파라미터

- Prometheus는 `--web.enable-remote-write-receiver`를 활성화한다.
- Prometheus metrics retention은 `180d`를 기본값으로 둔다.
- Loki raw log retention은 `14d`를 기본값으로 둔다.
- Tempo trace retention은 `7d`를 기본값으로 둔다.
- Grafana datasource는 provisioning으로 자동 연결한다.
- Alertmanager는 최소 1개 receiver를 구성하고, 로컬에서는 noop receiver로도 alert 상태를 검증할 수 있게 한다.
- Collector health endpoint는 `13133`, self metrics endpoint는 `8888`을 사용한다.
- 로컬 compose는 고정 라벨 `deployment.environment=local`을 주입하고, 운영에서는 gateway 또는 collector processor로 `user_id`, `team`, `environment`를 주입한다.
- Loki는 Collector의 OTLP HTTP exporter로 전송하고, `event_name`, `event_kind`, `tool`, `model`, `team`, `user_id` 같은 주요 attribute가 검색 라벨로 유지되는지 실제 적재로 검증한다.
- 외부 Codex ingress는 `4318`의 HTTP gateway만 사용하고, collector의 `4317` gRPC 포트는 외부에 노출하지 않는다.
- gateway는 `x-codex-ingest-token`을 읽어 `ingest_token_id`, `resolved_user_id`, `resolved_team`을 OTLP resource/attribute에 주입한 뒤 내부 collector로 전달한다.

---

## 예시 Codex 설정 (`~/.config/codex/config.toml`)

```toml
[otel]
environment = "production"
log_user_prompt = false
exporter = { otlp-http = {
  endpoint = "https://otel.company.com/v1/logs",
  protocol = "binary",
  headers = { "x-codex-ingest-token" = "USER_SPECIFIC_TOKEN" }
}}
metrics_exporter = { otlp-http = {
  endpoint = "https://otel.company.com/v1/metrics",
  protocol = "binary",
  headers = { "x-codex-ingest-token" = "USER_SPECIFIC_TOKEN" }
}}
trace_exporter = { otlp-http = {
  endpoint = "https://otel.company.com/v1/traces",
  protocol = "binary",
  headers = { "x-codex-ingest-token" = "USER_SPECIFIC_TOKEN" }
}}
```

---

## 예시 OTel Collector 구성 (`collector-config.yaml`)

```yaml
receivers:
  otlp:
    protocols:
      http:
      grpc:
processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
  batch:
exporters:
  otlp_http/loki:
    endpoint: http://loki:3100/otlp
  prometheusremotewrite:
    endpoint: http://prometheus:9090/api/v1/write
  otlp_grpc/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true
service:
  pipelines:
    logs:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp_http/loki]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheusremotewrite]
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp_grpc/tempo]
```

---

## 사용자/팀 식별 방식

현재 운영 기본값은 `사용자 1명당 active OTLP token 1개`다. Collector 또는 Gateway는 이 token을 기준으로 canonical identity attribute를 주입한다.

```text
OTLP Token dj.yoo-primary   -> resolved_user_id=dj.yoo,   resolved_team=backend
OTLP Token alice.kim-primary -> resolved_user_id=alice.kim, resolved_team=platform
OTLP Token bob.lee-primary   -> resolved_user_id=bob.lee,   resolved_team=frontend
```

로컬 docker compose 기준 환경에서도 `ingest-gateway`가 실제 `x-codex-ingest-token`을 검증하고 주입한다. 운영에서는 같은 패턴을 reverse proxy 또는 별도 gateway 레이어로 그대로 가져가면 된다.

---

## 로컬 검증 절차

1. `cp .env.example .env`
2. `docker compose up -d`
3. Grafana(`http://localhost:3000`), Prometheus(`http://localhost:9090`), Loki(`http://localhost:3100`), Tempo(`http://localhost:3200`)가 올라오는지 확인
4. Alertmanager(`http://localhost:9093`)가 올라오는지 확인
5. Codex CLI에서 OTLP endpoint를 `http://localhost:4318/v1/{logs|metrics|traces}`로 설정하고, `x-codex-ingest-token` header를 함께 보낸다
6. 실제 Codex 세션 또는 `scripts/send_sample_otel.py`로 샘플 telemetry 전송
7. Grafana Explore에서 Loki/Tempo/Prometheus에 데이터가 들어오는지 검증
8. Collector self-metrics와 health endpoint로 파이프라인 상태 확인
9. Alertmanager 또는 Prometheus Rules UI에서 alert rule 상태 확인

### 2026-04-28 로컬 검증 결과

- `docker compose up -d`로 전체 스택 기동 확인
- `python3 scripts/send_sample_otel.py`로 OTLP 로그/메트릭/트레이스 주입 확인
- Prometheus에서 `codex_api_request_total`, `codex_tool_call_total` 값 조회 확인
- Loki에서 `event_name=codex.sse_event`, `event_name=codex.tool_result` 라벨 검색 확인
- Tempo Search API에서 `service.name=codex-cli` trace 조회 확인
- Alertmanager에서 `OTelCollectorDown` firing 및 collector 재기동 후 alert 해제 확인

---

## 기본 Grafana 쿼리 예시

### 모델별 요청 수

```promql
sum by (model) (
  increase(codex_api_request_total[$__range])
)
```

### 모델별 token 사용량

> 아래 쿼리는 Phase 2에서 token usage parser가 `codex.sse_event(kind=response.completed)`를 기반으로 파생 metric를 만든다는 전제를 둔다. OpenAI 공식 문서는 token count가 이벤트에 포함될 수 있음을 설명하지만, `codex_total_tokens_total`이라는 Prometheus metric 이름 자체를 보장하지는 않는다.

```promql
sum by (model) (
  increase(codex_total_tokens_total[$__range])
)
```

### 팀별 token 사용량

> 아래 쿼리 역시 Phase 2의 파생 metric 생성 이후를 기준으로 한다.

```promql
sum by (team) (
  increase(codex_total_tokens_total[$__range])
)
```

### tool별 호출 수

```promql
sum by (tool) (
  increase(codex_tool_call_total[$__range])
)
```

---

## 주요 Task

| Task ID | Task | 담당 | 우선순위 |
|---------|------|------|----------|
| P1-T01 | OTel Collector 배포 | Platform | P0 |
| P1-T02 | OTLP HTTP endpoint 구성 | Platform | P0 |
| P1-T03 | OTLP 인증 토큰 구성 | Platform | P0 |
| P1-T04 | Codex CLI OTel 설정 템플릿 작성 | Platform | P0 |
| P1-T05 | 개발자별/팀별 OTLP token 발급 방식 구성 | Platform, Security | P0 |
| P1-T06 | Loki OTLP ingest 경로 구성 | Platform | P0 |
| P1-T07 | Prometheus exporter 또는 remote write 구성 | Platform | P0 |
| P1-T08 | Grafana datasource 연결 | Platform | P0 |
| P1-T09 | 기본 dashboard 생성 | Platform | P0 |
| P1-T10 | Collector health dashboard 구성 | Platform | P1 |
| P1-T11 | 수집 실패 알림 구성 | Platform | P1 |
| P1-T12 | 로컬 검증용 docker compose 작성 | Platform | P0 |
| P1-T13 | Prometheus remote write receiver 활성화 | Platform | P0 |
| P1-T14 | 볼륨/retention 기본값 정의 | Platform | P0 |
| P1-T15 | Grafana datasource provisioning 구성 | Platform | P0 |
| P1-T16 | Collector 공통 resource label 주입 구성 | Platform | P1 |
| P1-T17 | Prometheus alert rule 구성 | Platform | P1 |
| P1-T18 | Alertmanager 로컬 검증 구성 | Platform | P1 |
| P1-T19 | 샘플 OTLP 전송 스크립트 작성 | Platform | P1 |
| P1-T20 | Grafana health dashboard provisioning | Platform | P1 |

---

## 산출물

- OTel Collector 배포 manifest
- Codex config.toml 템플릿
- Loki datasource
- Prometheus datasource
- Grafana MVP dashboard
- 운영 runbook
- 로컬 검증용 docker compose 및 설정 파일
- Alertmanager 설정
- 샘플 OTLP 전송 스크립트

---

## 완료 기준

- [ ] 최소 3명 이상의 개발자 PC에서 Codex telemetry가 수집된다.
- [ ] Grafana에서 모델별 요청 수를 확인할 수 있다.
- [ ] Grafana에서 tool call 수를 확인할 수 있다.
- [ ] Loki에서 raw event를 검색할 수 있다.
- [ ] Collector 장애 시 알림이 발생한다.
- [ ] 로컬 docker compose로 전체 참조 스택을 재현할 수 있다.
- [ ] 저장소별 기본 retention 값이 설정 파일에 반영되어 있다.
- [ ] Alertmanager에서 collector down alert 상태를 확인할 수 있다.
- [ ] 샘플 OTLP 스크립트로 로컬 수집 경로를 검증할 수 있다.

---

이전 단계: [TASK-1.md](./TASK-1.md) - Phase 0: 사전 검증 및 정책 정의

다음 단계: [TASK-3.md](./TASK-3.md) - Phase 2: Token Usage 정규화 및 Dashboard 구축
