# RUNBOOK: TASK-7 Trace 기반 병목 분석

## 목적

`TASK-7`에서 추가한 trace span 정규화, 세션 집계, log-trace correlation, Grafana trace 대시보드가 로컬 스택에서 정상 동작하는지 검증한다.

---

## 구성 요소

- Trace 스키마: `configs/postgres/init/010-task7-trace-schema.sql`
- Trace normalizer: `scripts/normalize_trace_spans.py`
- Scheduler 통합: `scripts/run_scheduler.py`
- Approval view: `codex_trace_approval_spans_dashboard`
- Grafana 대시보드: `configs/grafana/dashboards/trace-analysis.json`

---

## 사전 조건

1. `docker compose up -d`로 기본 스택이 올라와 있어야 한다.
2. PostgreSQL에 TASK-3 ~ TASK-7 스키마가 적용되어 있어야 한다.

```bash
make task3-schema
make task4-schema
make task5-schema
make task6-schema
make task7-schema
```

기존 volume을 재사용 중이면 init script가 자동 재실행되지 않으므로 `make task7-schema`를 반드시 한 번 실행한다.

---

## 검증 절차

### 1. trace normalizer 수동 실행

최근 trace를 PostgreSQL로 한 번 강제로 적재한다.

```bash
python3 scripts/normalize_trace_spans.py
```

필요하면 더 짧은 윈도우로 다시 읽을 수 있다.

```bash
python3 scripts/normalize_trace_spans.py \
  --lookback-seconds 900 \
  --search-limit 500
```

### 2. usage/tool/api trace key backfill

기존 로그 정규화 row에도 `trace_id`, `span_id`가 채워져 있어야 correlation view가 의미가 있다.

```bash
python3 scripts/normalize_usage_events.py
python3 scripts/normalize_tool_events.py
python3 scripts/normalize_api_request_events.py
python3 scripts/normalize_fn_call_events.py
```

### 3. span 적재 확인

```sql
select count(*), max(event_time)
from codex_trace_spans;
```

최소 1건 이상 적재되어 있어야 한다.

### 4. 세션 집계 확인

```sql
select
  trace_id,
  user_id,
  team,
  conversation_id,
  root_span_name,
  slowest_span_name,
  slowest_span_duration_ms,
  session_duration_ms
from codex_trace_sessions_dashboard
order by session_started_at desc
limit 10;
```

확인 포인트:

- `trace_id`
- `user_id`
- `team`
- `conversation_id`
- `root_span_name`
- `slowest_span_name`

### 5. log-trace correlation 확인

tool correlation:

```sql
select
  event_time,
  trace_id,
  tool_name,
  correlated_span_name,
  correlated_span_duration_ms,
  user_id,
  team
from codex_trace_log_correlation_dashboard
where event_source = 'tool'
order by event_time desc
limit 20;
```

api correlation:

```sql
select
  event_time,
  trace_id,
  request_type,
  correlated_span_name,
  correlated_span_duration_ms,
  user_id,
  team
from codex_trace_log_correlation_dashboard
where event_source = 'api'
order by event_time desc
limit 20;
```

fn_call correlation:

```sql
select
  event_time,
  trace_id,
  event_kind,
  item_id,
  arguments_size,
  correlated_span_name,
  correlated_span_duration_ms,
  user_id,
  team
from codex_trace_log_correlation_dashboard
where event_source = 'fn_call'
order by event_time desc
limit 20;
```

현재 실제 Codex 세션에서는 `response.function_call_arguments.*` 이벤트가 항상 관찰되지 않을 수 있으므로, 결과가 `0건`이면 대시보드나 SQL이 깨진 것이 아니라 원본 이벤트가 없는 상태일 수 있다.

### 6. approval span 확인

현재 Phase 6에서 approval 분석은 `op.dispatch.*_approval` span을 기준으로 한다.

```sql
select
  event_time,
  trace_id,
  approval_type,
  approval_duration_ms,
  user_id,
  team,
  conversation_id,
  root_span_name,
  slowest_span_name
from codex_trace_approval_spans_dashboard
order by event_time desc
limit 20;
```

해석 원칙:

- 여기서 보이는 `approval_duration_ms`는 human wait time이 아니라 runtime approval dispatch overhead다.
- 실제 사람 승인 대기 시간은 explicit approval lifecycle event가 없으면 계산할 수 없다.

### 7. Grafana 대시보드 확인

- Grafana: `http://localhost:3000`
- Dashboard: `Codex Trace Analysis`

확인할 패널:

- `Trace 세션 수`
- `세션 p95 Duration`
- `느린 Trace 세션 Top 50`
- `느린 Span Top 100`
- `최근 API Request Correlation`
- `최근 Tool Call Correlation`
- `최근 fn_call Correlation`
- `최근 Approval Span`

### 8. 실제 Trace Explore 확인

세션 테이블에서 `trace_id`를 하나 복사한 뒤 Grafana Explore에서 Tempo datasource로 검색한다.

확인 포인트:

- root span 이름
- 느린 span 이름
- `resolved_user_id`
- `resolved_team`
- `ingest_token_id`

---

## 현재 구현 메모

- actual Codex trace에는 `conversation_id`가 span attribute에 항상 직접 들어오지 않을 수 있다.
- 그래서 세션 view는 trace span과 usage/tool/api/fn_call 이벤트를 `trace_id` 기준으로 묶어 `conversation_id`를 보강한다.
- exact `span_id` match가 없으면 correlation view는 같은 `trace_id` 안에서 가장 가까운 span을 fallback으로 사용한다.
- 현재 실제 trace에서는 `op.dispatch.patch_approval`, `op.dispatch.exec_approval` span이 관찰된다.
- 다만 현재 검증 데이터에서 approval span duration은 `0~3ms` 수준이라 human wait time으로 해석하면 안 된다.
- Trace sampling은 현재 미적용이며, 운영 정책은 `100% 수집`을 기본으로 둔다.
- 샘플링 완화는 span/day, Tempo 저장소 사용률, trace normalizer 실행 시간 임계치가 동시에 아니라도 어느 하나라도 넘으면 검토한다.

---

## 알려진 제한

- `normalize_fn_call_events.py`는 아직 direct PostgreSQL 인자를 받지 않고 host에서 `docker exec` 경로를 사용한다.
- sample trace와 실제 Codex trace의 span 이름 구조는 다를 수 있다.
- 일부 event는 `trace_id`는 있지만 span이 log-only인 경우가 있어 exact span correlation이 100%는 아닐 수 있다.
- human approval wait time은 아직 직접 계산할 수 없다.
