# TASK-5: Phase 4 - Cost 계산 및 정산용 데이터 모델 구축

## 목표

token usage와 모델 가격 정책을 기반으로 팀별/사용자별/repository별 추정 비용을 계산한다.

---

## 비용 계산 방식

### 기본 공식

```text
input_cost =
  uncached_input_tokens / 1,000,000 * input_price_per_1m
cached_input_cost =
  cached_input_tokens / 1,000,000 * cached_input_price_per_1m
output_cost =
  visible_output_tokens / 1,000,000 * output_price_per_1m
reasoning_cost =
  reasoning_tokens / 1,000,000 * reasoning_price_per_1m
total_estimated_cost =
  input_cost
  + cached_input_cost
  + output_cost
  + reasoning_cost
```

### cached token 처리

cached token이 별도 필드로 제공되는 경우:

```text
input_tokens = 전체 input token
cached_input_tokens = 전체 input 내부의 cache hit token
uncached_input_tokens = input_tokens - cached_input_tokens
```

cached token이 별도 필드로 제공되지 않는 경우:

```text
input_cost = input_tokens / 1,000,000 * input_price_per_1m
cached_input_tokens = null
cached_input_cost = 0
```

또는 별도 계산 불가 상태로 표시한다.

`cache_status = unknown`

### reasoning token 처리

reasoning token이 별도 필드로 제공되는 경우:

```text
output_tokens = 전체 output token
reasoning_tokens = 전체 output 내부의 reasoning token
visible_output_tokens = output_tokens - reasoning_tokens
```

reasoning token이 별도 필드로 제공되지 않거나 별도 과금 정책이 없는 경우:

```text
output_cost = output_tokens / 1,000,000 * output_price_per_1m
reasoning_tokens = null
reasoning_cost = 0
```

또는 별도 계산 불가 상태로 표시한다.

`reasoning_status = unknown`

### 비용 정확도 레벨

| 레벨 | 설명 |
|------|------|
| Estimated | telemetry token x 내부 가격표 기반 추정 |
| Reconciled | OpenAI usage/billing 데이터와 대조 완료 |
| Final | 회계/정산 기준 확정 |

MVP에서는 Estimated만 제공한다.

---

## 수집 필드

| 필드 | 설명 |
|------|------|
| input_cost | uncached input token 비용 |
| cached_input_cost | cached input breakdown 비용 |
| output_cost | visible output token 비용 |
| reasoning_cost | reasoning output breakdown 비용 |
| total_estimated_cost | 총 추정 비용 |
| currency | 통화 (기본: USD) |
| price_policy_version | 적용된 가격 정책 버전 |

---

## 데이터 모델

### codex_model_price_policy

```sql
create table codex_model_price_policy (
    id bigserial primary key,
    model text not null,
    input_price_per_1m numeric(18, 8) not null,
    cached_input_price_per_1m numeric(18, 8) default 0,
    output_price_per_1m numeric(18, 8) not null,
    reasoning_price_per_1m numeric(18, 8) default 0,
    currency text default 'USD',
    version text not null,
    effective_from timestamp not null,
    effective_to timestamp,
    created_at timestamp default now()
);
```

### codex_user_mapping

```sql
create table codex_user_mapping (
    id bigserial primary key,
    user_id text not null,
    display_name text,
    email text,
    team text,
    department text,
    active boolean default true,
    created_at timestamp default now(),
    updated_at timestamp default now()
);
```

- canonical user master 테이블이다.
- `user_id`는 비용 집계와 대시보드의 최종 사용자 식별자다.
- `email`은 대표 이메일일 뿐이며, 실제 Codex telemetry에서 매번 그대로 들어오는 값을 뜻하지는 않는다.

### codex_user_email_mapping

`codex_user_email_mapping`은 관찰된 이메일 alias를 canonical user에 연결하는 테이블이다.

- `observed_user_email` 또는 raw `user_id`가 이메일 형식일 때 먼저 이 테이블을 본다.
- 한 사람이 여러 계정을 쓸 수 있으므로 `codex_user_mapping`과 별도로 둔다.
- canonical master의 대표 이메일은 `codex_user_mapping.email`에 두고, 실제 Codex 사용 alias만 이 테이블에 둔다.
- 예:
  - `example.1@example.com -> example`
  - `example.2@example.com -> example`

즉 `codex_user_mapping`은 사람 기준 master이고, `codex_user_email_mapping`은 이메일 alias 기준 매핑이다.

### codex_team_budget

```sql
create table codex_team_budget (
    id bigserial primary key,
    team text not null,
    monthly_budget numeric(18, 4) not null,
    currency text default 'USD',
    effective_from date not null,
    effective_to date,
    created_at timestamp default now()
);
```

---

## DB 기반 비용 계산 구조

Prometheus만으로 cost 계산을 처리하면 가격표 join, 재계산, 월별 정산이 어렵다. 따라서 비용 분석은 DB 기반으로 구성한다.

```text
Raw OTel Event
  -> Parser
  -> codex_usage_events
  -> model_price_policy join
  -> estimated_cost
  -> Grafana
```

DB는 초기에는 PostgreSQL로 충분하고, 데이터가 많아지면 ClickHouse를 검토한다.

---

## 보관/파티셔닝 정책

### `codex_usage_events`

- 파티션 기준: `event_time` 월 단위 RANGE partition
- row 보관 기간: 365일
- `raw_event` 보관 기간: 30일
- 30일이 지난 `raw_event`는 컬럼 null 처리 또는 별도 raw table 삭제
- 365일이 지난 파티션은 drop

### 비용 집계 테이블 추가

원본 이벤트 테이블만으로 대시보드를 직접 구성하면 쿼리 비용이 커질 수 있으므로 집계 테이블을 추가한다.

```sql
create table codex_daily_cost_agg (
    usage_date date not null,
    team text not null,
    user_id text,
    repository text,
    model text,
    total_requests bigint not null default 0,
    total_tokens bigint not null default 0,
    total_estimated_cost numeric(18, 8) not null default 0,
    currency text default 'USD',
    price_policy_version text not null,
    created_at timestamp default now(),
    primary key (usage_date, team, user_id, repository, model)
);
```

### 집계/백업 기준

| 대상 | 보관 기간 | 생성 주기 | 백업 |
|------|----------|----------|------|
| `codex_usage_events` 정규화 row | 365일 | 실시간 적재 | 일 1회 |
| `codex_usage_events.raw_event` | 30일 | 실시간 적재 | 백업 제외 권장 |
| `codex_daily_cost_agg` | 365일 | 일 1회 집계 | 일 1회 |
| 가격 정책 테이블 | 만료 전까지 | 변경 시 | 변경 시 스냅샷 |

---

## Dashboard 요구사항

### Cost Dashboard

비용 관점에서 팀/사용자/모델/repository별 사용량을 분석한다.

**패널**

- 일별 estimated cost
- 주별 estimated cost
- 월별 estimated cost
- 팀별 estimated cost
- 사용자별 estimated cost
- repository별 estimated cost
- 모델별 estimated cost
- 팀별 월 예산 대비 사용률
- 예상 월말 비용 forecast

---

## Grafana SQL 쿼리 예시 (SQL datasource)

### 팀별 추정 비용

```sql
select
    date_trunc('day', event_time) as time,
    team,
    sum(total_estimated_cost) as estimated_cost
from codex_usage_events
where event_time between $__timeFrom() and $__timeTo()
group by 1, 2
order by 1;
```

### 모델별 추정 비용

```sql
select
    model,
    sum(total_estimated_cost) as estimated_cost
from codex_usage_events
where event_time between $__timeFrom() and $__timeTo()
group by model
order by estimated_cost desc;
```

### 사용자별 추정 비용 Top 10

```sql
select
    user_id,
    team,
    sum(total_estimated_cost) as estimated_cost
from codex_usage_events
where event_time between $__timeFrom() and $__timeTo()
group by user_id, team
order by estimated_cost desc
limit 10;
```

---

## 주요 Task

| Task ID | Task | 담당 | 우선순위 |
|---------|------|------|----------|
| P4-T01 | 모델 가격 정책 테이블 설계 | Backend | P0 | 완료 |
| P4-T02 | 모델 가격 정책 초기 데이터 입력 | Platform/Finance | P0 | 완료 |
| P4-T03 | usage event 정규화 테이블 생성 | Backend | P0 | 완료 (TASK-3) |
| P4-T04 | token usage event 저장 파이프라인 구현 | Backend/Platform | P0 | 완료 (TASK-3) |
| P4-T05 | 비용 계산 batch 구현 | Backend | P0 | 완료 |
| P4-T06 | 비용 재계산 기능 구현 | Backend | P1 | 완료 |
| P4-T07 | cached token 비용 계산 구현 | Backend | P1 | 완료 |
| P4-T08 | reasoning token 비용 계산 구현 | Backend | P1 | 완료 |
| P4-T09 | 팀별 일/주/월 비용 query 작성 | Backend | P0 | 완료 |
| P4-T10 | 사용자별 비용 query 작성 | Backend | P1 | 완료 |
| P4-T11 | repository별 비용 query 작성 | Backend | P1 | 완료 |
| P4-T12 | cost dashboard 생성 | Platform | P0 | 완료 |
| P4-T13 | 팀별 budget 테이블 생성 | Backend | P1 | 완료 |
| P4-T14 | 예산 대비 사용률 dashboard 생성 | Platform | P1 | 완료 |
| P4-T15 | 월 파티션 생성/삭제 job 구현 | Backend | P0 | 완료 (drop-old-rows) |
| P4-T16 | `raw_event` 30일 purge 또는 null 처리 job 구현 | Backend | P0 | 완료 |
| P4-T17 | 일별 비용 집계 테이블 생성 | Backend | P0 | 완료 |
| P4-T18 | backup 대상/제외 대상 정의 | Platform | P1 | 완료 (TODO.md 정책 참조) |

---

## 산출물

- `configs/postgres/init/004-cost-schema.sql`
  - `codex_model_price_policy` 테이블 + 초기 가격 데이터 (11개 모델)
  - `codex_user_mapping` 테이블 + 초기 user 데이터
  - `codex_team_budget` 테이블 + 초기 예산 데이터 (5개 팀)
  - `codex_daily_cost_agg` 테이블 (일별 집계)
  - `codex_usage_events_with_cost` VIEW (usage + price LATERAL join)
  - `codex_team_budget_usage` VIEW (이번달 예산 대비 사용률 + forecast)
  - `codex_repo_cost_summary` / `codex_user_cost_summary` VIEW
- `scripts/calculate_costs.py`
  - `compute-daily`: 일별 비용 집계 upsert
  - `compute-range`: 날짜 범위 재계산 (가격 정책 변경 후 재산출)
  - `purge-raw-events`: 30일 이상 raw_event → `{"_purged":true}` 치환
  - `drop-old-rows`: 365일 이상 usage row 삭제
- `configs/grafana/dashboards/cost-analysis.json`
  - 20개 패널: 팀/사용자/모델/repository별 비용, 예산 대비 사용률, 월말 forecast

---

## 완료 기준

- [x] 모델별 추정 비용을 확인할 수 있다.
- [x] 팀별 일/주/월 추정 비용을 확인할 수 있다.
- [x] 사용자별 추정 비용을 확인할 수 있다.
- [x] repository별 추정 비용을 확인할 수 있다.
- [x] 모델 가격 변경 시 과거 usage 비용을 재계산할 수 있다.
- [x] `raw_event` 30일 보관 정책이 구현되어 있다.
- [x] 월 파티션 기준 365일 retention이 구현되어 있다.

로컬 기술 검증 기준으로 TASK-5를 완료한 상태로 본다.

---

이전 단계: [TASK-4.md](./TASK-4.md) - Phase 3: Tool Usage 및 병목 분석

다음 단계: [TASK-6.md](./TASK-6.md) - Phase 5: 운영 안정화 및 알림
