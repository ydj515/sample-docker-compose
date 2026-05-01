# TASK-5 로컬 운영 Runbook

## 목표

모델 가격 정책과 token usage를 join해 팀/사용자/모델/repository별 추정 비용을 계산하고, 일별 집계 테이블과 Grafana `Cost Analysis` 대시보드에서 조회한다. 아울러 `raw_event` 30일 purge와 usage row 365일 retention job을 검증한다.

---

## 사전 준비

### 1. 스택 기동

```bash
docker compose up -d
```

### 2. TASK-3 스키마가 먼저 적용돼 있어야 한다

`codex_usage_events` 테이블이 없으면 비용 뷰가 생성되지 않는다.

```bash
make task3-schema
```

### 3. TASK-5 스키마 적용

신규 볼륨이면 자동 적용된다. 기존 `postgres17-data`를 계속 쓰는 경우 아래 명령으로 수동 적용한다.

```bash
make task5-schema
```

적용 대상:

| 객체 | 종류 | 비고 |
|------|------|------|
| `codex_model_price_policy` | 테이블 | 11개 모델 초기 데이터 포함 |
| `codex_user_mapping` | 테이블 | canonical user 매핑 저장 |
| `codex_team_budget` | 테이블 | 5개 팀 초기 예산 포함 |
| `codex_daily_cost_agg` | 테이블 | 일별 비용 집계 |
| `codex_usage_events_with_cost` | VIEW | usage + 가격 정책 LATERAL join |
| `codex_team_budget_usage` | VIEW | 이번달 예산 대비 사용액 + 월말 forecast |
| `codex_user_cost_summary` | VIEW | 사용자별 누적 비용 |
| `codex_repo_cost_summary` | VIEW | repository별 누적 비용 |

---

## 샘플 데이터 주입

usage 이벤트(cached/reasoning breakdown 포함)와 breakdown이 없는 이벤트를 혼합해서 보낸다.

```bash
make task5-sample-mixed
```

이 타깃은 아래 성격의 샘플을 전송한다.

- `sample-team / sample-user@example.com / gpt-5.4`: input 2400, cached 800, output 680, reasoning 120
- `sample-team / sample-user@example.com / gpt-5.4`: input 1800, output 450 (breakdown 없음)

---

## 정규화 및 비용 계산 실행

### 1. usage 이벤트 정규화 (TASK-3 파이프라인)

```bash
python3 scripts/normalize_usage_events.py
```

또는:

```bash
make task3-normalize
```

### 2. 비용 집계 실행

```bash
python3 scripts/calculate_costs.py compute-daily --date $(date +%Y-%m-%d)
```

> `--date` 를 생략하면 어제 날짜로 집계한다. 방금 주입한 샘플을 즉시 집계하려면 오늘 날짜를 명시해야 한다.

또는 전체 한 번에:

```bash
make task5-verify
```

`task5-verify`는 스키마 적용 → 샘플 주입 → 정규화 → 오늘 날짜 비용 집계 순으로 실행한다.

---

## 검증 절차

### 1. 초기 데이터 확인

**모델 가격 정책:**

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c 'select model, input_price_per_1m, cached_input_price_per_1m, output_price_per_1m, reasoning_price_per_1m, version from codex_model_price_policy order by model;'
```

**팀 예산:**

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c 'select team, monthly_budget, currency, effective_from from codex_team_budget order by team;'
```

**user 매핑:**

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c 'select user_id, display_name, team, department from codex_user_mapping;'
```

### 2. usage event 적재 확인

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c 'select event_time, team, user_id, model, input_tokens, cached_input_tokens, cached_input_tokens_available, output_tokens, reasoning_tokens, reasoning_tokens_available, total_tokens from codex_usage_events order by event_time desc limit 10;'
```

### 3. 비용 뷰(codex_usage_events_with_cost) 확인

가격 정책이 매칭되어 비용이 계산되는지 확인한다. `price_policy_version`이 `unknown`이면 해당 모델의 가격 정책이 없는 것이다.

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c "select event_time, team, user_id, model, total_tokens, round(input_cost::numeric,8) as input_cost, round(cached_input_cost::numeric,8) as cached_cost, round(output_cost::numeric,8) as output_cost, round(total_estimated_cost::numeric,8) as total_cost, price_policy_version, cost_accuracy from codex_usage_events_with_cost order by event_time desc limit 10;"
```

확인 포인트:

- `total_estimated_cost > 0` 인지 확인 (0이면 가격 정책 미매칭)
- `price_policy_version = 'v1-2025-04'` 인지 확인
- `cost_accuracy = 'Estimated'` 인지 확인
- cached/reasoning breakdown이 없는 이벤트는 해당 항목이 0인지 확인

### 4. 일별 집계 테이블 확인

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c "select usage_date, team, user_id, model, total_requests, total_tokens, round(total_estimated_cost::numeric,8) as total_cost, price_policy_version from codex_daily_cost_agg order by usage_date desc, total_cost desc;"
```

### 5. 팀별 비용 집계 확인

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c "select team, sum(total_requests) as requests, sum(total_tokens) as tokens, round(sum(total_estimated_cost)::numeric,8) as estimated_cost_usd from codex_daily_cost_agg group by team order by estimated_cost_usd desc;"
```

### 6. 모델별 비용 확인

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c "select model, sum(total_requests) as requests, round(sum(total_input_cost)::numeric,8) as input, round(sum(total_cached_input_cost)::numeric,8) as cached, round(sum(total_output_cost)::numeric,8) as output, round(sum(total_estimated_cost)::numeric,8) as total from codex_daily_cost_agg group by model order by total desc;"
```

### 7. 예산 대비 사용률 확인

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c "select team, monthly_budget, round(current_month_cost::numeric,6) as used, round(remaining_budget::numeric,6) as remaining, budget_usage_pct, round(forecast_month_end_cost::numeric,6) as forecast from codex_team_budget_usage order by budget_usage_pct desc nulls last;"
```

### 8. Grafana 대시보드 확인

Grafana 접속 주소: `http://localhost:3000`

확인 대시보드: **Cost Analysis** (`/d/codex-cost-analysis`)

확인 패널:

| 패널 | 확인 내용 |
|------|----------|
| 기간 내 총 추정 비용 | 0보다 큰 값이어야 한다 |
| 팀별 추정 비용 | `sample-team` 또는 실제 팀 행이 보여야 한다 |
| 모델별 추정 비용 | `gpt-5.4` 행이 보여야 한다 |
| 사용자별 추정 비용 Top 30 | `sample-user@example.com` 또는 실제 canonical user가 표시돼야 한다 |
| 팀별 이번달 예산 대비 사용액 | bar gauge가 렌더링돼야 한다 |
| 비용 유형별 추이 | input/output 라인이 보여야 한다 |

시간 범위를 `Last 1 hour` 또는 `Today`로 설정해야 방금 주입한 데이터가 보인다.

### 9. Grafana 프로비저닝 확인

```bash
curl -sS -u admin:admin http://localhost:3000/api/search | jq '.[] | {title, uid}'
```

`cost-analysis` uid가 목록에 보이면 정상이다.

---

## 운영 관리 작업

### 비용 재계산 (가격 정책 변경 후)

`codex_model_price_policy`에 새 버전을 추가한 뒤 대상 기간을 재산출한다.

```bash
# 예: 2025-04-01 ~ 2025-04-30 재계산
python3 scripts/calculate_costs.py compute-range \
  --from 2025-04-01 \
  --to 2025-04-30
```

또는:

```bash
make cost-recompute FROM=2025-04-01 TO=2025-04-30
```

재계산은 `codex_daily_cost_agg`에 upsert되므로 기존 집계를 덮어쓴다.

### 가격 정책 버전 추가

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability << 'SQL'
insert into codex_model_price_policy
    (model, input_price_per_1m, cached_input_price_per_1m, output_price_per_1m, reasoning_price_per_1m, currency, version, effective_from, effective_to)
values
    ('gpt-5.4', 2.50, 0.25, 15.00, 0, 'USD', 'openai-api-pricing-2026-04-29', '2025-01-01', null);
SQL
```

> 신규 버전이 적용된 날짜 이후의 이벤트에는 자동으로 새 가격이 적용된다 (`effective_from` 기준 최신 정책 선택).  
> 이전 기간의 집계는 위 `compute-range`로 재산출해야 한다.

### raw_event 30일 purge

```bash
python3 scripts/calculate_costs.py purge-raw-events --dry-run
# 확인 후 실행
python3 scripts/calculate_costs.py purge-raw-events
```

또는:

```bash
make cost-purge-raw
```

purge 대상 행의 `raw_event`는 `{"_purged": true}`로 치환된다. `NOT NULL` 제약을 유지하면서 원본 payload만 제거한다.

### usage event 365일 retention

```bash
python3 scripts/calculate_costs.py drop-old-rows --dry-run
# 확인 후 실행
python3 scripts/calculate_costs.py drop-old-rows
```

또는:

```bash
make cost-purge-old
```

> retention 실행 전 `codex_daily_cost_agg`에 해당 기간 집계가 완료되어 있어야 한다. 집계 없이 row를 삭제하면 과거 비용 데이터가 소실된다.

### 팀 예산 변경

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability << 'SQL'
-- 기존 예산 종료 처리
update codex_team_budget
set effective_to = '2025-06-30'
where team = 'backend' and effective_to is null;

-- 새 예산 삽입
insert into codex_team_budget (team, monthly_budget, currency, effective_from)
values ('backend', 450.00, 'USD', '2025-07-01')
on conflict (team, effective_from) do nothing;
SQL
```

### user 매핑 추가/수정

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability << 'SQL'
insert into codex_user_mapping (user_id, display_name, email, team, department)
values ('alice.kim', 'Alice Kim', 'alice@example.com', 'platform', 'Engineering')
on conflict (user_id) do update set
    display_name = excluded.display_name,
    email = excluded.email,
    team = excluded.team,
    department = excluded.department,
    updated_at = now();
SQL
```

---

## 트러블슈팅

### total_estimated_cost가 0인 경우

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c "select distinct lower(model) as model from codex_usage_events where model is not null;"
```

위 결과 모델명이 `codex_model_price_policy.model`과 일치하는지 확인한다. 불일치하면 해당 모델을 가격 정책에 추가해야 한다.

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c "select model from codex_model_price_policy order by model;"
```

### codex_daily_cost_agg가 비어 있는 경우

`compute-daily`의 기본 날짜가 **어제**임을 주의한다. 샘플을 오늘 주입했으면 오늘 날짜를 명시한다.

```bash
python3 scripts/calculate_costs.py compute-daily --date $(date +%Y-%m-%d)
```

### codex_team_budget_usage에 팀이 안 보이는 경우

`codex_team_budget`의 `effective_from <= current_date` 조건을 확인한다.

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c "select team, effective_from, effective_to from codex_team_budget;"
```

`effective_from`이 미래 날짜로 잘못 입력된 경우 `codex_team_budget_usage`에 나타나지 않는다.

---

## 완료 기준 해석

로컬 기준으로는 아래가 확인되면 TASK-5의 기술적 구성이 준비된 것으로 본다.

- `codex_usage_events_with_cost`에서 `total_estimated_cost > 0`이고 `price_policy_version`이 정책 버전과 일치한다.
- `codex_daily_cost_agg`에 팀/사용자/모델별 집계가 적재된다.
- 모델별/팀별/사용자별/repository별 추정 비용을 SQL로 조회할 수 있다.
- `codex_team_budget_usage` 뷰에서 예산 대비 사용률과 월말 forecast가 계산된다.
- `compute-range`로 날짜 범위 재계산이 가능하다 (가격 정책 변경 후 검증).
- `purge-raw-events`가 `raw_event`를 `{"_purged": true}`로 치환한다.
- `drop-old-rows`가 대상 행 수를 올바르게 출력하고 삭제한다.
- Grafana `Cost Analysis` 대시보드의 모든 패널이 데이터를 표시한다.
- 기간/팀/모델/사용자/repository 필터가 동작한다.

---

이전 단계: [RUNBOOK-TASK-4.md](./RUNBOOK-TASK-4.md)

다음 단계: [TASK-6.md](./TASK-6.md) - Phase 5: 운영 안정화 및 알림
