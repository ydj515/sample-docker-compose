# RUNBOOK: TASK-6 운영 안정화 및 알림

## 목적

`TASK-6`의 alert rule, 운영 대시보드, retention job 상태 노출이 로컬 스택에서 정상 동작하는지 검증한다.

---

## 구성 요소

- Prometheus rule: `configs/prometheus/rules/task-6-alerts.yml`
- 운영 메트릭 exporter: `scripts/task6_ops_exporter.sh`
- 운영 스키마: `configs/postgres/init/005-task6-ops-schema.sql`
- 운영 대시보드: `configs/grafana/dashboards/operations-alerting.json`

---

## 사전 조건

1. `docker compose up -d`로 기본 스택이 올라와 있어야 한다.
2. PostgreSQL에 TASK-3 ~ TASK-6 스키마가 적용되어 있어야 한다.

```bash
make task3-schema
make task4-schema
make task5-schema
make task6-schema
```

기존 volume을 재사용 중이면 init script가 자동 재실행되지 않으므로 `make task6-schema`를 반드시 한 번 실행한다.

---

## 검증 절차

### 1. 운영 exporter 확인

```bash
curl http://localhost:9107/metrics
```

아래 메트릭이 보이면 정상이다.

- `codex_team_budget_usage_ratio`
- `codex_company_daily_estimated_cost_usd`
- `codex_job_last_run_success`
- `codex_store_usage_ratio`

### 2. Prometheus target 확인

```bash
curl 'http://localhost:9090/api/v1/targets'
```

`job="codex-ops-exporter"` target이 `health="up"` 이어야 한다.

### 3. Prometheus rule group 확인

```bash
curl 'http://localhost:9090/api/v1/rules'
```

`codex-task-6` group이 로드되어 있어야 한다.

### 4. retention job 상태 seed

`codex_job_run_status`는 scheduler가 없으면 초기에는 비어 있을 수 있으므로 아래 커맨드를 한 번 실행한다.

```bash
python3 scripts/calculate_costs.py compute-daily --date $(date +%Y-%m-%d)
python3 scripts/calculate_costs.py purge-raw-events --older-than-days 30
python3 scripts/calculate_costs.py drop-old-rows --older-than-days 365
```

이후 `/metrics`에서 아래 메트릭이 보여야 한다.

- `codex_job_last_run_success{job_name="compute-daily"}`
- `codex_job_last_run_success{job_name="purge-raw-events"}`
- `codex_job_last_run_success{job_name="drop-old-rows"}`

### 5. Grafana 대시보드 확인

- Grafana: `http://localhost:3000`
- Dashboard: `Codex Operations Alerting`

확인할 패널:

- 현재 firing alert 수
- usage 마지막 이벤트 경과
- 팀별 예산 사용률
- 저장소 사용률
- retention job 마지막 성공 경과

---

## 현재 기대되는 alert 상태

로컬 기본 상태에서는 아래가 일반적이다.

- `OTelCollectorDown`: inactive
- `CodexTeamBudgetWarning`, `CodexTeamBudgetCritical`: inactive
- `CodexStoreUsageWarning`, `CodexStoreUsageCritical`: inactive
- `CodexRetentionJobFailed`: inactive
- `CodexUsageDataGapDetected`, `CodexToolDataGapDetected`: pending 또는 firing 가능

마지막 항목은 현재 스택에 normalizer scheduler가 없어서 생기는 정상적인 경보 신호다.

---

## 선택 검증

### Collector down alert

```bash
docker stop llm-monitoring-otel-collector-1
```

약 2분 뒤 `OTelCollectorDown`이 firing으로 전환된다.

복구:

```bash
docker start llm-monitoring-otel-collector-1
```

### data gap alert 해소

normalizer를 수동 실행해서 최신 데이터를 다시 적재하면 gap alert가 해소될 수 있다.

```bash
python3 scripts/normalize_usage_events.py
python3 scripts/normalize_tool_events.py
```

---

## 알려진 제한

- API 요청 실패율 alert는 현재 source metric 부재로 미구현 상태다.
- Grafana folder/team RBAC는 로컬 admin 계정만 제공하므로 후속 작업이다.
- retention job과 normalizer는 scheduler에 아직 연결되지 않았다.
