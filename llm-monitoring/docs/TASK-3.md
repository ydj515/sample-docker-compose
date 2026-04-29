# TASK-3: Phase 2 - Token Usage 정규화 및 Dashboard 구축

## 목표

Codex OTel 로그에서 token usage를 추출해 PostgreSQL에 정규화하고, Grafana SQL 대시보드에서 모델별/팀별/사용자별 사용량을 안정적으로 조회한다.

공식 Codex telemetry 문서는 token count가 `codex.sse_event`의 `kind=response.completed`에 포함될 수 있음을 설명하지만, 전용 Prometheus token metric 이름을 보장하지 않는다. 따라서 이 Phase의 핵심은 Prometheus 직접 집계가 아니라 `response.completed` payload를 파싱해 정규화 테이블을 만드는 것이다.

---

## 구현 범위

2026-04-28 기준으로 아래 항목을 구현했다.

- Loki `response.completed` usage payload를 PostgreSQL로 적재하는 정규화 스크립트
- 중복 적재 방지를 위한 `source_fingerprint` 기반 upsert
- 재실행 이어받기를 위한 `codex_usage_sync_state`
- 모델/팀/사용자 단위 Grafana SQL 대시보드 3종
- breakdown 제공 여부를 구분하는 availability flag와 파생 컬럼

---

## Token Usage 해석 원칙

| 필드 | 의미 |
|------|------|
| `input_tokens` | 전체 input token 수 |
| `cached_input_tokens` | 전체 input 내부의 cache hit breakdown |
| `uncached_input_tokens` | `input_tokens - cached_input_tokens` |
| `output_tokens` | 전체 output token 수 |
| `reasoning_tokens` | 전체 output 내부의 reasoning breakdown |
| `visible_output_tokens` | `output_tokens - reasoning_tokens` |
| `total_tokens` | 전체 token 수 |

> `cached_input_tokens`와 `reasoning_tokens`는 `input_tokens`, `output_tokens`에 더하는 별도 총계가 아니라 내부 breakdown으로 해석한다.

breakdown이 항상 제공된다고 가정하지 않는다. 따라서 스키마에는 아래 상태 컬럼을 둔다.

- `cached_input_tokens_available`
- `reasoning_tokens_available`

---

## 정규화 파이프라인

```text
Loki
  -> query_range({service_name="codex-cli"})
  -> normalize_usage_events.py
      -> event_name=codex.sse_event 필터
      -> event_kind=response.completed 필터
      -> usage payload 파싱
      -> source_fingerprint dedupe
      -> codex_usage_sync_state checkpoint 저장
  -> PostgreSQL codex_usage_events
  -> Grafana PostgreSQL datasource
```

Loki OTLP 적재 시 모든 attribute가 항상 index label로 유지된다고 가정하지 않는다. 그래서 정규화 스크립트는 기본적으로 `service_name` 범위만 넓게 조회하고, 실제 `event_name`과 `event_kind` 판별은 payload/attribute 기준으로 애플리케이션 레벨에서 다시 수행한다.

---

## 데이터 모델

### `codex_usage_events`

```sql
create table if not exists codex_usage_events (
    id bigserial primary key,
    source_fingerprint text not null unique,
    source_timestamp_ns bigint not null,
    event_time timestamptz not null,
    event_name text not null,
    event_kind text,
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
    response_id text,
    input_tokens bigint not null default 0,
    cached_input_tokens bigint,
    cached_input_tokens_available boolean not null default false,
    uncached_input_tokens bigint generated always as (
        greatest(input_tokens - coalesce(cached_input_tokens, 0), 0)
    ) stored,
    output_tokens bigint not null default 0,
    reasoning_tokens bigint,
    reasoning_tokens_available boolean not null default false,
    visible_output_tokens bigint generated always as (
        greatest(output_tokens - coalesce(reasoning_tokens, 0), 0)
    ) stored,
    total_tokens bigint not null default 0,
    usage_payload jsonb,
    raw_event jsonb not null,
    created_at timestamptz not null default now()
);
```

### 보조 객체

- `codex_usage_sync_state`
  - pipeline별 마지막 `source_timestamp_ns` 저장
- `codex_usage_events_dashboard`
  - Grafana SQL datasource용 조회 view

---

## Dashboard 구성

### `Codex Token Usage - Models`

- 모델별 요청 수
- 모델별 total token
- 모델별 uncached input token
- 모델별 cached input token
- 모델별 output token
- 모델별 reasoning token

### `Codex Token Usage - Teams`

- 팀별 total token
- 팀별 요청 수
- 팀별 모델 사용량
- 팀별 repository 사용량

### `Codex Token Usage - Users`

- 사용자별 total token
- 사용자별 요청 수
- 사용자별 모델 사용량
- 사용자별 breakdown 제공 여부 점검

모든 대시보드는 PostgreSQL datasource를 사용하고, 시간 범위 및 변수 필터를 적용할 수 있게 구성한다.

---

## Grafana SQL 쿼리 예시

### 모델별 total token

```sql
select
    model,
    sum(total_tokens) as total_tokens
from codex_usage_events_dashboard
where event_time between $__timeFrom() and $__timeTo()
group by model
order by total_tokens desc;
```

### 팀별 token 사용량

```sql
select
    team,
    sum(total_tokens) as total_tokens,
    sum(uncached_input_tokens) as uncached_input_tokens,
    sum(coalesce(cached_input_tokens, 0)) as cached_input_tokens
from codex_usage_events_dashboard
where event_time between $__timeFrom() and $__timeTo()
group by team
order by total_tokens desc;
```

### 사용자별 reasoning breakdown 제공 여부

```sql
select
    user_id,
    count(*) as requests,
    sum(case when reasoning_tokens_available then 1 else 0 end) as reasoning_breakdown_present
from codex_usage_events_dashboard
where event_time between $__timeFrom() and $__timeTo()
group by user_id
order by requests desc;
```

---

## 주요 Task

| Task ID | Task | 상태 |
|---------|------|------|
| P2-T01 | token usage parser 구현 | 완료 |
| P2-T02 | `input_tokens`, `output_tokens`, `total_tokens` 추출 | 완료 |
| P2-T03 | `cached_input_tokens`, `reasoning_tokens` 조건부 추출 | 완료 |
| P2-T04 | model/team/user/repository metadata 정규화 | 완료 |
| P2-T05 | PostgreSQL 정규화 스키마 및 sync state 구성 | 완료 |
| P2-T06 | 모델별 SQL dashboard 생성 | 완료 |
| P2-T07 | 팀별 SQL dashboard 생성 | 완료 |
| P2-T08 | 사용자별 SQL dashboard 생성 | 완료 |
| P2-T09 | 로컬 runbook 및 샘플 데이터 경로 구성 | 완료 |

---

## 산출물

- `configs/postgres/init/001-task3-schema.sql`
- `scripts/normalize_usage_events.py`
- `scripts/send_sample_otel.py`
- `configs/grafana/dashboards/token-usage-models.json`
- `configs/grafana/dashboards/token-usage-teams.json`
- `configs/grafana/dashboards/token-usage-users.json`
- `docs/RUNBOOK-TASK-3.md`

---

## 완료 기준

- [x] 모델별 input/output/total token을 확인할 수 있다.
- [x] 팀별 token 사용량을 확인할 수 있다.
- [x] 사용자별 token 사용량을 확인할 수 있다.
- [x] 기간 필터를 적용할 수 있다.
- [x] cached/reasoning breakdown 제공 여부가 dashboard와 DB에서 명확히 표시된다.
- [x] `response.completed` usage payload가 중복 없이 PostgreSQL에 정규화된다.

실서비스 rollout 관점에서는 실제 Codex 사용자의 telemetry를 붙여 추가 검증이 더 필요하지만, 로컬 기술 검증 기준으로는 TASK-3를 완료한 상태로 본다.

---

## 2026-04-28 로컬 검증 결과

- breakdown이 포함된 샘플 1건과 breakdown이 없는 샘플 1건을 전송했다.
- `normalize_usage_events.py` 실행 후 PostgreSQL `codex_usage_events`에 2건이 정규화 적재됐다.
- `cached_input_tokens_available`, `reasoning_tokens_available`가 모델별로 다르게 기록되는 것을 확인했다.
- Grafana에서 `Codex Token Usage - Models`, `Teams`, `Users` 대시보드가 자동 프로비저닝되는 것을 확인했다.

---

이전 단계: [TASK-2.md](./TASK-2.md) - Phase 1: MVP 수집 파이프라인 구축

다음 단계: [TASK-4.md](./TASK-4.md) - Phase 3: Tool Usage 및 병목 분석
