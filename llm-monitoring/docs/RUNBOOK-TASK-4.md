# TASK-4 로컬 운영 Runbook

## 목표

Loki에 적재된 `codex.tool_decision`, `codex.tool_result` 로그를 PostgreSQL에 정규화하고, Grafana SQL 대시보드에서 tool별 호출 수, 실패율, p95 duration을 확인한다.

---

## 사전 준비

1. 스택 기동

```bash
docker compose up -d
```

2. PostgreSQL 스키마 적용

신규 볼륨이면 자동 적용된다. 기존 `postgres17-data`를 계속 쓰는 경우 아래 명령으로 수동 적용한다.

```bash
make task4-schema
```

---

## 샘플 데이터 주입

성공/실패와 duration이 섞인 tool 이벤트를 보낸다.

```bash
make task4-sample-mixed
```

이 타깃은 아래 성격의 샘플을 전송한다.

- `web.search` 성공 2건
- `web.search` 실패 1건
- `shell.exec` 성공 1건

---

## 정규화 실행

```bash
python3 scripts/normalize_tool_events.py
```

또는:

```bash
make task4-normalize
```

---

## 검증 절차

### 1. PostgreSQL 적재 확인

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c 'select event_time, event_name, team, user_id, tool_name, tool_call_id, tool_success, tool_duration_ms, tool_error_code, tool_output_size from codex_tool_events order by event_time desc limit 20;'
```

### 2. Tool별 실패율 / p95 확인

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c "select tool_name, count(*) as total_calls, round(100.0 * avg(case when tool_success = false then 1.0 when tool_success = true then 0.0 else null end), 2) as failure_rate_pct, round((percentile_cont(0.95) within group (order by tool_duration_ms))::numeric, 2) as p95_duration_ms from codex_tool_results_dashboard group by tool_name order by total_calls desc, tool_name;"
```

### 3. Grafana 대시보드 확인

- `Codex Tool Usage`

Grafana 접속 주소:

- `http://localhost:3000`

### 4. Grafana 프로비저닝 확인

```bash
curl -sS -u admin:admin http://localhost:3000/api/search | jq '.[] | {title, uid}'
```

---

## 완료 기준 해석

로컬 기준으로는 아래가 확인되면 TASK-4의 기술적 구성이 준비된 것으로 본다.

- `codex.tool_decision`, `codex.tool_result` 로그가 PostgreSQL에 중복 없이 적재된다.
- tool별 호출 수, 성공률, 실패율, p95 duration을 SQL 대시보드에서 확인할 수 있다.
- 실패한 tool call과 느린 tool call을 테이블로 바로 조회할 수 있다.
- 기간 필터와 team/user/repository/model/tool 필터가 동작한다.
