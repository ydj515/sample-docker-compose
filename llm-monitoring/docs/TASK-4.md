# TASK-4: Phase 3 - Tool Usage 및 병목 분석

## 목표

Codex tool 사용량, 실패율, duration을 분석하여 어떤 tool이 많이 사용되고 어디서 병목이 발생하는지 확인한다.

2026-04-28 기준 구현 방식은 Loki의 `codex.tool_decision`, `codex.tool_result` 로그를 PostgreSQL에 정규화한 뒤, Grafana SQL 대시보드에서 호출 수, 실패율, p95/p99 duration과 실패/지연 사례를 함께 보는 구조다.

실제 Codex `0.125.0` 세션 검증 결과, 본세션 로그는 `service_name=codex_cli_rs`로 들어오며 body가 비어 있고 주요 정보가 label에 실리는 경우가 있었다. 현재 parser는 이 실제 형식도 지원하도록 `tool_name`, `call_id`, `duration_ms`, `success`, `conversation_id`, `user_email` label을 우선적으로 해석한다.

---

## 구현 범위

- `codex.tool_decision`, `codex.tool_result` 파서 구현
- PostgreSQL `codex_tool_events`, `codex_tool_results_dashboard` 구성
- tool별 호출 수, 성공률, 실패율, p50/p95/p99 duration 대시보드 구성
- 실패한 tool call, 느린 tool call 조회 테이블 구성
- mixed sample telemetry 및 로컬 runbook 추가

알림 룰은 운영 안정화 단계 성격이 강하므로 실제 구현 우선순위는 `TASK-6`에서 이어간다.

---

## 수집 필드

| 필드 | 설명 |
|------|------|
| `tool_name` | tool 이름 |
| `tool_call_id` | tool 호출 ID |
| `tool_decision` | 실행 승인/거부 등 decision 결과 |
| `tool_success` | 성공/실패 여부 |
| `tool_duration_ms` | 실행 시간 (ms) |
| `tool_error_code` | 에러 코드 |
| `tool_error_message` | 에러 메시지 |
| `tool_output_size` | output 크기 |

> 실제 Codex 세션에서는 `arguments`, `output`가 label에 직접 포함될 수 있다. 현재 normalizer는 PostgreSQL `raw_event` 저장 시 이 필드를 `[REDACTED]`로 치환하고, 길이만 `tool_output_size`로 남긴다.

### 실제 Codex 이벤트 이름 기준

- `codex.tool_decision`: tool 실행 승인/거부 이벤트
- `codex.tool_result`: tool 실행 결과 이벤트
- Prometheus 적재 시 공식 metric `codex.tool.call`은 일반적으로 `codex_tool_call_total` 형태로 변환된다.

---

## 정규화 파이프라인

```text
Loki
  -> query_range({service_name=~"codex-cli|codex_cli_rs"})
  -> normalize_tool_events.py
      -> event_name in (codex.tool_decision, codex.tool_result)
      -> tool payload / attributes 파싱
      -> source_fingerprint dedupe
      -> codex_tool_sync_state checkpoint 저장
  -> PostgreSQL codex_tool_events
  -> codex_tool_results_dashboard
  -> Grafana PostgreSQL datasource
```

Loki OTLP 적재 시 attribute가 항상 index label로 유지된다고 가정하지 않는다. 그래서 normalizer는 `service_name` 기준으로 넓게 조회한 뒤, 실제 event 판별은 payload와 attribute를 함께 사용한다. body가 비어 있는 label-only 로그도 현재 지원 범위에 포함한다.

---

## 데이터 모델

### `codex_tool_events`

```sql
create table if not exists codex_tool_events (
    id bigserial primary key,
    source_fingerprint text not null unique,
    source_timestamp_ns bigint not null,
    event_time timestamptz not null,
    event_name text not null,
    environment text,
    service_name text,
    service_namespace text,
    codex_version text,
    user_id text,
    team text,
    repository text,
    project text,
    session_id text,
    conversation_id text,
    model text,
    tool_name text not null,
    tool_call_id text,
    tool_decision text,
    tool_success boolean,
    tool_duration_ms bigint,
    tool_error_code text,
    tool_error_message text,
    tool_output_size bigint,
    raw_event jsonb not null,
    created_at timestamptz not null default now()
);
```

### 보조 객체

- `codex_tool_sync_state`
  - pipeline별 마지막 `source_timestamp_ns` 저장
- `codex_tool_events_dashboard`
  - 전체 tool 이벤트 조회 view
- `codex_tool_results_dashboard`
  - `codex.tool_result` 전용 조회 view

---

## Dashboard 구성

### `Codex Tool Usage`

- 전체 tool call
- 성공률
- 실패율
- p95 duration
- tool별 usage 집계
- tool별 호출 추이
- 실패한 tool call
- 느린 tool call

필터:

- team
- user
- repository
- model
- tool
- date range

---

## Grafana SQL 쿼리 예시

### tool별 호출 수

```sql
select
    tool_name,
    count(*) as total_calls
from codex_tool_results_dashboard
where event_time between $__timeFrom() and $__timeTo()
group by tool_name
order by total_calls desc;
```

### tool별 실패율

```sql
select
    tool_name,
    round(100.0 * avg(case when tool_success = false then 1.0 when tool_success = true then 0.0 else null end), 2) as failure_rate_pct
from codex_tool_results_dashboard
where event_time between $__timeFrom() and $__timeTo()
group by tool_name
order by failure_rate_pct desc, tool_name;
```

### tool별 p95 duration

```sql
select
    tool_name,
    round((percentile_cont(0.95) within group (order by tool_duration_ms))::numeric, 2) as p95_duration_ms
from codex_tool_results_dashboard
where event_time between $__timeFrom() and $__timeTo()
  and tool_duration_ms is not null
group by tool_name
order by p95_duration_ms desc, tool_name;
```

Prometheus의 `codex_tool_call_total`은 대안적인 집계 경로로 계속 남겨 두되, 로컬 참조 스택의 `TASK-4` 완료 기준은 SQL 정규화 대시보드로 본다.

---

## 주요 Task

| Task ID | Task | 상태 |
|---------|------|------|
| P3-T01 | tool 이벤트 parser 구현 | 완료 |
| P3-T02 | tool name / call id 정규화 | 완료 |
| P3-T03 | tool success/failure 추출 | 완료 |
| P3-T04 | tool duration 추출 | 완료 |
| P3-T05 | tool error message 추출 | 완료 |
| P3-T06 | tool output size 추출 | 완료 |
| P3-T07 | PostgreSQL 정규화 스키마 구성 | 완료 |
| P3-T08 | tool usage dashboard 생성 | 완료 |
| P3-T09 | 실패/지연 사례 테이블 패널 구성 | 완료 |
| P3-T10 | mixed sample telemetry 및 runbook 구성 | 완료 |
| P3-T11 | tool failure alert 구성 | 후속 |
| P3-T12 | tool p95 latency alert 구성 | 후속 |

---

## 산출물

- `configs/postgres/init/002-task4-schema.sql`
- `scripts/normalize_tool_events.py`
- `scripts/send_sample_otel.py`
- `configs/grafana/dashboards/tool-usage-overview.json`
- `docs/RUNBOOK-TASK-4.md`

---

## 완료 기준

- [x] tool별 호출 수를 확인할 수 있다.
- [x] tool별 실패율을 확인할 수 있다.
- [x] tool별 p95 duration을 확인할 수 있다.
- [x] 실패한 tool call 로그를 검색할 수 있다.
- [x] 느린 tool call 로그를 검색할 수 있다.

로컬 기술 검증 기준으로는 TASK-4를 완료한 상태로 본다. 다만 운영 alert는 `TASK-6`에서 별도로 구현한다.

---

이전 단계: [TASK-3.md](./TASK-3.md) - Phase 2: Token Usage 정규화 및 Dashboard 구축

다음 단계: [TASK-5.md](./TASK-5.md) - Phase 4: Cost 계산 및 정산용 데이터 모델 구축
