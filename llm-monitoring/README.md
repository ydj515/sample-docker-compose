# Codex OTel Observability Stack

Codex CLI의 OpenTelemetry 로그, 메트릭, 트레이스를 로컬에서 수집하고, Grafana와 PostgreSQL에서 조회하기 위한 참조 스택이다.

이 저장소는 OpenAI Codex 공식 문서의 Observability/Telemetry 설정을 기준으로 다음 목적을 가진다.

- Codex 실행 이벤트를 OTLP로 수집한다.
- 모델별 요청 수, 토큰 사용량, tool 사용 패턴을 확인한다.
- raw prompt를 기본적으로 저장하지 않는다.
- token usage 정규화와 향후 비용 집계용 PostgreSQL 저장소까지 확장 가능한 구조를 유지한다.

## 1. 공식 문서 기준 핵심 사항

OpenAI Codex 공식 문서 기준으로 관측 설정은 기본 비활성화이며, `[otel]` 섹션으로 명시적으로 켜야 한다.

- `otel.environment`의 기본값은 `dev`다.
- `otel.exporter` 기본값은 `none`이다.
- `otel.log_user_prompt`는 raw prompt 내보내기를 제어한다.
- `otel.metrics_exporter` 기본값은 `statsig`다.
- `otel.trace_exporter`는 별도로 설정할 수 있다.

이 저장소에서는 보안 정책상 다음 값을 기본 원칙으로 둔다.

- `log_user_prompt = false`
- tool output 원문 장기 저장 금지
- `raw_event`는 redaction 이후 단기 보관

## 2. OpenAI 공식 이벤트/메트릭 기준

공식 문서에서 대표적으로 언급하는 이벤트는 아래와 같다.

- `codex.conversation_starts`
- `codex.api_request`
- `codex.sse_event`
- `codex.websocket_request`
- `codex.websocket_event`
- `codex.user_prompt`
- `codex.tool_decision`
- `codex.tool_result`

중요한 점은 `response.completed`가 최상위 이벤트명이 아니라 `codex.sse_event`의 하위 `kind`로 나타난다는 점이다. 따라서 토큰 사용량 파싱은 `event_name=codex.sse_event`와 `event_kind=response.completed` 조합을 기준으로 설계하는 편이 안전하다.

공식 문서의 OTel 메트릭 이름은 점 표기법을 사용한다.

다만 공식 문서가 보장하는 것은 API/stream/tool 활동 메트릭이며, 토큰 합계 메트릭 이름까지 직접 약속하는 것은 아니다. 이 저장소에서는 토큰 대시보드를 `codex.sse_event(kind=response.completed)` 기반 파생 지표로 취급한다.

| 공식 이름 | Prometheus 적재 후 일반적 이름 |
|----------|-------------------------------|
| `codex.api_request` | `codex_api_request_total` |
| `codex.api_request.duration_ms` | `codex_api_request_duration_ms_bucket` |
| `codex.sse_event` | `codex_sse_event_total` |
| `codex.sse_event.duration_ms` | `codex_sse_event_duration_ms_bucket` |
| `codex.tool.call` | `codex_tool_call_total` |
| `codex.tool.call.duration_ms` | `codex_tool_call_duration_ms_bucket` |

위 변환은 OTLP metric이 Prometheus naming 규칙으로 변환될 때 일반적으로 기대되는 형태다.

## 2.1 Token Usage 해석 원칙

이 저장소는 OpenAI Codex usage payload를 아래 원칙으로 해석한다.

- `input_tokens`는 전체 input token 수다.
- `cached_input_tokens`는 전체 input 내부의 cache hit breakdown이다.
- `output_tokens`는 전체 output token 수다.
- `reasoning_tokens`는 payload가 제공할 경우 전체 output 내부의 breakdown이다.
- 따라서 `cached_input_tokens`와 `reasoning_tokens`는 기본적으로 `input_tokens`, `output_tokens`에 추가로 더하는 별도 총계가 아니다.

PostgreSQL 정규화 스키마에서는 대시보드와 비용 계산을 단순화하기 위해 아래 파생 컬럼을 함께 사용한다.

- `uncached_input_tokens = input_tokens - cached_input_tokens`
- `visible_output_tokens = output_tokens - reasoning_tokens`

## 3. 저장소 구조

```text
.
├── docker-compose.yml
├── .env.example
├── configs
│   ├── grafana
│   ├── loki
│   ├── otel-collector
│   ├── prometheus
│   └── tempo
├── docs
├── scripts
└── Makefile
```

## 4. 로컬 스택 구성

`docker-compose.yml`은 아래 서비스를 띄운다.

| 서비스 | 역할 | 기본 포트 |
|--------|------|----------|
| `otel-collector` | OTLP 진입점 및 fan-out | `4317`, `4318`, `13133` |
| `loki` | raw log 저장/검색 | `3100` |
| `prometheus` | metric 저장/조회 | `9090` |
| `tempo` | trace 저장/조회 | `3200` |
| `grafana` | 통합 UI | `3000` |
| `alertmanager` | alert 수신/상태 확인 | `9093` |
| `postgres` | 정규화/비용 저장소 | `5432` |

2026-04-28 기준으로 실제 기동 및 호환성 검증을 마친 버전 조합은 아래와 같다.

| 서비스 | 버전 |
|--------|------|
| OTel Collector Contrib | `0.150.1` |
| Loki | `3.6.10` |
| Prometheus | `3.5.2` |
| Tempo | `2.10.4` |
| Grafana | `13.0.1` |
| Alertmanager | `0.32.0` |
| PostgreSQL | `17.9-alpine` |

버전 선정 원칙은 다음과 같다.

- PostgreSQL은 메이저 `17`의 최신 안정 패치로 고정한다.
- Prometheus는 공식 다운로드 페이지에서 `LTS`로 표기하는 `3.5.2`를 사용한다.
- Grafana는 `13.x` 계열까지 올린 뒤 provisioning, datasource, dashboard 호환성을 실제로 다시 검증한다.
- Tempo, Alertmanager, OTel Collector는 현재 설정과 호환성이 확인된 안정 패치를 사용한다.
- Loki는 최신 기능 브랜치보다 로컬 참조 스택 호환성이 좋은 `3.6.x` 최신 패치 `3.6.10`을 사용한다.

현재 로컬 참조 스택의 데이터 흐름은 아래와 같다.

```text
Codex CLI
  -> OTel Collector
      -> Loki
      -> Prometheus
      -> Tempo

Loki response.completed log
  -> normalize_usage_events.py
  -> PostgreSQL
  -> Grafana SQL datasource

Cost Pipeline (향후)
  -> PostgreSQL aggregate / policy table
  -> Grafana SQL datasource
```

## 5. 실행 방법

### 5.1 환경 변수 준비

```bash
cp .env.example .env
```

### 5.2 스택 기동

```bash
docker compose up -d
```

### 5.3 접속 주소

- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- Alertmanager: `http://localhost:9093`
- Loki: `http://localhost:3100`
- Tempo: `http://localhost:3200`
- OTel Collector health: `http://localhost:13133`

## 6. Codex 설정 예시

공식 문서의 `[otel]` 설정과 Config Reference를 기준으로, 이 저장소에서는 아래와 같은 구성을 권장한다.

```toml
[otel]
environment = "production"
log_user_prompt = false

exporter = { otlp-http = {
  endpoint = "http://localhost:4318/v1/logs",
  protocol = "binary",
  headers = { "x-otlp-api-key" = "${OTLP_TOKEN}" }
}}

metrics_exporter = { otlp-http = {
  endpoint = "http://localhost:4318/v1/metrics",
  protocol = "binary",
  headers = { "x-otlp-api-key" = "${OTLP_TOKEN}" }
}}

trace_exporter = { otlp-http = {
  endpoint = "http://localhost:4318/v1/traces",
  protocol = "binary",
  headers = { "x-otlp-api-key" = "${OTLP_TOKEN}" }
}}
```

추가로, OpenAI로 전송되는 익명 usage/health metrics까지 끄고 싶다면 별도 analytics 설정을 사용할 수 있다.

```toml
[analytics]
enabled = false
```

## 7. Retention 정책

이 저장소 초안은 “무엇을 얼마나 오래 보관할지”를 저장소별로 분리해서 본다.

| 데이터 | 저장소 | 기본 보관 기간 | 현재 상태 |
|--------|--------|---------------|----------|
| Raw OTel 로그 | Loki | 14일 | 설정 반영 완료 |
| Metrics | Prometheus | 180일 | 설정 반영 완료 |
| Traces | Tempo | 7일 | 설정 반영 완료 |
| 정규화 usage row | PostgreSQL | 365일 | 문서화 완료, purge job 미구현 |
| `raw_event` JSON | PostgreSQL | 30일 | 문서화 완료, purge job 미구현 |
| 비용 집계 | PostgreSQL | 365일 | 문서화 완료, 집계 job 미구현 |

추가 운영 기준은 아래와 같다.

- 디스크 사용률 70%에서 경고, 85%에서 긴급 알림
- `raw_event`는 redaction 이후에만 저장
- `raw_event`와 정규화 row는 서로 다른 retention을 적용
- PostgreSQL은 월 단위 파티션 기반 운영 권장

## 8. 현재 포함된 설정 파일

- `configs/otel-collector/config.yaml`
  - OTLP gRPC/HTTP receiver
  - Loki OTLP ingest / Prometheus Remote Write / Tempo OTLP gRPC fan-out
  - Collector self-metrics (`:8888`)
  - health endpoint (`:13133`)
- `configs/loki/config.yml`
  - filesystem storage
  - 14일 retention
- `configs/prometheus/prometheus.yml`
  - Collector/Loki/Tempo/Prometheus self-scrape
  - remote write receiver 사용
  - Alertmanager 연동
- `configs/prometheus/rules/task-2-alerts.yml`
  - `OTelCollectorDown`
  - `OTelExporterSendFailures`
- `configs/tempo/config.yml`
  - local backend
  - 7일 retention
- `configs/grafana/provisioning/datasources/datasources.yml`
  - Prometheus / Loki / Tempo / PostgreSQL / Alertmanager datasource 자동 연결
- `configs/grafana/dashboards`
  - `Codex MVP Overview`
  - `Collector Health`
  - `Codex Token Usage - Models`
  - `Codex Token Usage - Teams`
  - `Codex Token Usage - Users`
  - `Codex Tool Usage`
- `configs/postgres/init/001-task3-schema.sql`
  - `codex_usage_events`, `codex_usage_sync_state`, `codex_usage_events_dashboard` 생성
- `configs/postgres/init/002-task4-schema.sql`
  - `codex_tool_events`, `codex_tool_sync_state`, `codex_tool_results_dashboard` 생성
- `scripts/send_sample_otel.py`
  - 로컬 샘플 OTLP 로그/메트릭/트레이스 전송
- `scripts/normalize_usage_events.py`
  - Loki `response.completed` usage payload를 PostgreSQL로 정규화
- `scripts/normalize_tool_events.py`
  - Loki `codex.tool_decision`, `codex.tool_result` payload를 PostgreSQL로 정규화
  - 실제 Codex `codex_cli_rs` label-only `tool_result`도 파싱하고 `arguments`/`output`는 redaction 처리
- `docs/RUNBOOK-TASK-2.md`
  - 로컬 검증 절차
- `docs/RUNBOOK-TASK-3.md`
  - token usage 정규화 및 SQL 대시보드 검증 절차
- `docs/RUNBOOK-TASK-4.md`
  - tool usage 정규화 및 SQL 대시보드 검증 절차

## 9. 2026-04-28 검증 결과

- `docker compose up -d`로 전체 스택 기동 확인
- Grafana `13.0.1` 기동 및 provisioning 호환성 확인
- `python3 scripts/send_sample_otel.py`로 샘플 OTLP 로그/메트릭/트레이스 주입 확인
- Prometheus에서 `codex_api_request_total`, `codex_tool_call_total` 조회 확인
- Loki에서 `event_name=codex.sse_event`, `event_name=codex.tool_result` 로그 검색 확인
- Tempo Search API에서 `service.name=codex-cli` trace 조회 확인
- Alertmanager에서 `OTelCollectorDown` firing 및 collector 재기동 후 복구 확인
- `make task3-schema`, `make task3-sample-mixed`, `make task3-normalize` 경로 검증
- PostgreSQL `codex_usage_events`에 breakdown 유무가 다른 2개 usage row 정규화 적재 확인
- Grafana에서 모델/팀/사용자 SQL 대시보드 3종 자동 프로비저닝 확인
- `make task4-schema`, `make task4-sample-mixed`, `make task4-normalize` 경로 검증
- PostgreSQL `codex_tool_events`에 success/failure, duration, error metadata가 다른 tool event 정규화 적재 확인
- Grafana에서 `Codex Tool Usage` SQL 대시보드 자동 프로비저닝 확인
- 실제 Codex 세션 `conversation_id=019dd1e4-1635-75b0-a34f-584e814c2137`의 `codex.tool_decision`, `codex.tool_result`, `codex.websocket_event` 수집 확인
- 실제 Codex `tool_result`는 `service_name=codex_cli_rs`, `tool_name`, `call_id`, `duration_ms`, `success` label 중심 포맷임을 확인

## 10. 아직 남아 있는 작업

- OTLP 토큰을 `user_id`, `team`으로 변환하는 gateway 또는 collector enrichment
- PostgreSQL 파티션 생성/삭제 및 `raw_event` purge job
- tool failure/p95 alert rule 구현 및 운영 임계치 보정
- tool output snippet에 대한 추가 redaction 규칙
- 비용 계산 파이프라인 및 일별 집계 테이블 구현

## 11. TASK-2 로컬 검증 절차

```bash
cp .env.example .env
docker compose up -d
python3 scripts/send_sample_otel.py
```

확인 포인트:

- Grafana `Codex MVP Overview`에서 모델별 요청 수와 Tool별 호출 수 확인
- Grafana Explore 또는 Loki에서 raw event 검색
- Grafana `Collector Health` 또는 Alertmanager에서 collector 상태/alert 확인

상세 절차는 [docs/RUNBOOK-TASK-2.md](./docs/RUNBOOK-TASK-2.md)를 참고한다.

## 12. TASK-3 로컬 검증 절차

```bash
make task3-schema
make task3-sample-mixed
make task3-normalize
```

확인 포인트:

- PostgreSQL `codex_usage_events`에 `response.completed` usage row가 중복 없이 적재된다.
- `cached_input_tokens_available`, `reasoning_tokens_available`로 breakdown 제공 여부를 구분할 수 있다.
- Grafana `Codex Token Usage - Models`, `Codex Token Usage - Teams`, `Codex Token Usage - Users`에서 기간/변수 필터가 동작한다.

상세 절차는 [docs/RUNBOOK-TASK-3.md](./docs/RUNBOOK-TASK-3.md)를 참고한다.

## 13. TASK-4 로컬 검증 절차

```bash
make task4-schema
make task4-sample-mixed
make task4-normalize
```

확인 포인트:

- PostgreSQL `codex_tool_events`에 `codex.tool_decision`, `codex.tool_result` row가 중복 없이 적재된다.
- Grafana `Codex Tool Usage`에서 tool별 호출 수, 실패율, p95 duration을 확인할 수 있다.
- 실패한 tool call과 느린 tool call을 테이블 패널에서 바로 조회할 수 있다.

상세 절차는 [docs/RUNBOOK-TASK-4.md](./docs/RUNBOOK-TASK-4.md)를 참고한다.

## 14. 참고 문서

- OpenAI Codex Advanced Configuration
  - https://developers.openai.com/codex/config-advanced#observability-and-telemetry
- OpenAI Codex Configuration Reference
  - https://developers.openai.com/codex/config-reference
