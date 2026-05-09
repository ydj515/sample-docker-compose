# TASK-2 로컬 운영 Runbook

## 목표

로컬 환경에서 Codex telemetry 수집 스택을 띄우고, 샘플 OTLP 데이터를 주입해 수집/조회/알림 경로를 검증한다.

---

## 사전 준비

1. `.env` 파일 생성

```bash
cp .env.example .env
```

2. 스택 설정 검증

```bash
docker compose config
```

---

## 기동 절차

```bash
docker compose up -d
```

접속 주소:

- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- Alertmanager: `http://localhost:9093`
- Loki: `http://localhost:3100`
- Tempo: `http://localhost:3200`
- Collector health: `http://localhost:13133`
- PostgreSQL: `localhost:5432`

---

## 샘플 데이터 주입

실제 Codex CLI 없이도 아래 명령으로 로컬 수집 경로를 검증할 수 있다.

```bash
python3 scripts/send_sample_otel.py
```

옵션 예시:

```bash
python3 scripts/send_sample_otel.py \
  --team sample-team \
  --user-id sample-user@example.com \
  --model gpt-5.4 \
  --tool shell.exec \
  --api-requests 5 \
  --tool-calls 3
```

---

## 검증 절차

### 1. Collector 상태 확인

- `http://localhost:13133` 응답 확인
- Grafana `Collector Health` 대시보드에서 `OTel Collector 상태`가 `UP`인지 확인

### 2. Prometheus 메트릭 확인

Prometheus에서 아래 쿼리를 확인한다.

```promql
sum(last_over_time(codex_api_request_total[1h]))
```

```promql
sum by (model) (last_over_time(codex_api_request_total[1h]))
```

```promql
sum by (tool) (last_over_time(codex_tool_call_total[1h]))
```

### 3. Grafana 대시보드 확인

- `Codex Token Usage - Models`
  - 모델별 요청 수
- `Codex Tool Usage`
  - Tool별 호출 수
- `Collector Health`
  - 수신 로그 속도
  - 수신 메트릭 속도
  - Exporter 실패 속도

### 4. Loki raw event 검색

Grafana Explore에서 Loki datasource를 선택한 뒤 예시 쿼리를 사용한다.

```logql
{service_name="codex-cli"}
```

```logql
{event_name="codex.sse_event"}
```

```logql
{event_name="codex.tool_result", tool="web.search"}
```

직접 API로 확인하려면 아래와 같이 range query를 사용할 수 있다.

```bash
curl -g -sS 'http://localhost:3100/loki/api/v1/query_range?query={service_name="codex-cli"}&limit=20'
```

### 5. Tempo trace 검색

Grafana Explore에서 Tempo datasource를 선택해 `service.name=codex-cli` 기준으로 search할 수 있다.

직접 API로 확인하려면 아래 예시를 사용한다.

```bash
curl -G -sS http://localhost:3200/api/search \
  --data-urlencode 'tags=service.name=codex-cli'
```

### 6. Alert 확인

- Alertmanager UI에서 활성 alert 확인
- Prometheus Rules 화면에서 `OTelCollectorDown`, `OTelExporterSendFailures` rule 확인

Collector down을 로컬에서 시험하려면 `otel-collector` 컨테이너를 잠시 중지한 뒤 2분 이상 대기한다.

```bash
docker compose stop otel-collector
```

복구:

```bash
docker compose start otel-collector
```

---

## 완료 기준 해석

로컬 기준으로는 아래가 확인되면 TASK-2의 기술적 구성이 준비된 것으로 본다.

- compose로 전체 스택이 올라온다.
- 샘플 OTLP 로그/메트릭/트레이스가 수집된다.
- Grafana에서 모델별 요청 수와 tool 호출 수가 조회된다.
- Loki에서 raw event를 검색할 수 있다.
- Collector down alert rule이 firing 상태로 전환된다.

문서의 `최소 3명 이상의 개발자 PC` 조건은 로컬 구성 완료 이후 운영 rollout 단계에서 별도로 검증해야 한다.
