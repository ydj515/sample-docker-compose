-- ─────────────────────────────────────────────────────────────
-- TASK-5: Cost 계산 및 정산용 데이터 모델
-- ─────────────────────────────────────────────────────────────

-- 모델 가격 정책 (버전별, 유효 기간 관리)
create table if not exists codex_model_price_policy (
    id bigserial primary key,
    model text not null,
    input_price_per_1m numeric(18, 8) not null,
    cached_input_price_per_1m numeric(18, 8) not null default 0,
    output_price_per_1m numeric(18, 8) not null,
    reasoning_price_per_1m numeric(18, 8) not null default 0,
    currency text not null default 'USD',
    version text not null,
    effective_from timestamptz not null,
    effective_to timestamptz,
    created_at timestamptz not null default now()
);

create unique index if not exists uq_model_price_policy_model_version
    on codex_model_price_policy (model, version);

create index if not exists idx_model_price_policy_model_from
    on codex_model_price_policy (model, effective_from desc);

-- 초기 가격 정책 데이터
-- OpenAI 가격은 2026-04-29 기준 https://openai.com/api/pricing 확인
insert into codex_model_price_policy
    (model, input_price_per_1m, cached_input_price_per_1m, output_price_per_1m, reasoning_price_per_1m, currency, version, effective_from)
values
    -- OpenAI 모델
    ('gpt-5.4',              2.50, 0.25,  15.00,  0.00, 'USD', 'openai-api-pricing-2026-04-29', '2025-01-01'),
    ('gpt-4o',               2.50, 1.25,  10.00,  0.00, 'USD', 'v1-2025-04', '2025-01-01'),
    ('gpt-4o-mini',          0.15, 0.075,  0.60,  0.00, 'USD', 'v1-2025-04', '2025-01-01'),
    ('o1',                  15.00, 7.50,  60.00, 60.00, 'USD', 'v1-2025-04', '2025-01-01'),
    ('o1-mini',              3.00, 1.50,  12.00, 12.00, 'USD', 'v1-2025-04', '2025-01-01'),
    ('o3',                  10.00, 2.50,  40.00, 40.00, 'USD', 'v1-2025-04', '2025-01-01'),
    ('o3-mini',              1.10, 0.55,   4.40,  4.40, 'USD', 'v1-2025-04', '2025-01-01'),
    -- Anthropic 모델
    ('claude-opus-4-7',     15.00, 7.50,  75.00,  0.00, 'USD', 'v1-2025-04', '2025-01-01'),
    ('claude-sonnet-4-6',    3.00, 1.50,  15.00,  0.00, 'USD', 'v1-2025-04', '2025-01-01'),
    ('claude-haiku-4-5-20251001', 0.80, 0.08, 4.00, 0.00, 'USD', 'v1-2025-04', '2025-01-01')
on conflict (model, version) do nothing;

-- user_id -> team/department 매핑 (TASK-5 스펙)
create table if not exists codex_user_mapping (
    id bigserial primary key,
    user_id text not null unique,
    display_name text,
    email text,
    team text,
    department text,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_codex_user_mapping_team
    on codex_user_mapping (team);

-- 팀별 월 예산
create table if not exists codex_team_budget (
    id bigserial primary key,
    team text not null,
    monthly_budget numeric(18, 4) not null,
    currency text not null default 'USD',
    effective_from date not null,
    effective_to date,
    created_at timestamptz not null default now()
);

create index if not exists idx_codex_team_budget_team_from
    on codex_team_budget (team, effective_from desc);

-- (team, effective_from) 쌍이 unique: 스키마 재적용 시 중복 삽입 방지
create unique index if not exists uq_codex_team_budget_team_from
    on codex_team_budget (team, effective_from);

-- 초기 예산 데이터
insert into codex_team_budget (team, monthly_budget, currency, effective_from)
values
    ('platform', 500.00, 'USD', '2025-01-01'),
    ('backend',  300.00, 'USD', '2025-01-01'),
    ('frontend', 200.00, 'USD', '2025-01-01'),
    ('data',     400.00, 'USD', '2025-01-01'),
    ('security', 100.00, 'USD', '2025-01-01')
on conflict (team, effective_from) do nothing;

-- 일별 비용 집계 테이블 (쿼리 성능용)
create table if not exists codex_daily_cost_agg (
    usage_date date not null,
    team text not null default '(unknown)',
    user_id text not null default '(unknown)',
    repository text not null default '(unknown)',
    model text not null default '(unknown)',
    price_policy_version text not null default 'unknown',
    currency text not null default 'USD',
    total_requests bigint not null default 0,
    total_input_tokens bigint not null default 0,
    total_cached_input_tokens bigint not null default 0,
    total_output_tokens bigint not null default 0,
    total_reasoning_tokens bigint not null default 0,
    total_tokens bigint not null default 0,
    total_input_cost numeric(18, 8) not null default 0,
    total_cached_input_cost numeric(18, 8) not null default 0,
    total_output_cost numeric(18, 8) not null default 0,
    total_reasoning_cost numeric(18, 8) not null default 0,
    total_estimated_cost numeric(18, 8) not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (usage_date, team, user_id, repository, model)
);

create index if not exists idx_codex_daily_cost_agg_date_team
    on codex_daily_cost_agg (usage_date desc, team);

create index if not exists idx_codex_daily_cost_agg_date_user
    on codex_daily_cost_agg (usage_date desc, user_id);

create index if not exists idx_codex_daily_cost_agg_date_model
    on codex_daily_cost_agg (usage_date desc, model);

-- ─────────────────────────────────────────────────────────────
-- Views
-- ─────────────────────────────────────────────────────────────

-- usage_events + 가격 정책 LATERAL join → 비용 on-the-fly 계산
-- 이 view를 calculate_costs.py 집계 기반 소스로 사용한다.
create or replace view codex_usage_events_with_cost as
select
    e.*,
    coalesce(p.version, 'unknown')  as price_policy_version,
    coalesce(p.currency, 'USD')     as currency,
    -- uncached input token 비용
    round(
        (e.uncached_input_tokens::numeric / 1000000.0)
        * coalesce(p.input_price_per_1m, 0),
        8
    ) as input_cost,
    -- cached input token 비용
    case
        when e.cached_input_tokens_available and e.cached_input_tokens is not null
        then round(
            (e.cached_input_tokens::numeric / 1000000.0)
            * coalesce(p.cached_input_price_per_1m, 0),
            8
        )
        else 0::numeric
    end as cached_input_cost,
    -- visible output token 비용
    round(
        (e.visible_output_tokens::numeric / 1000000.0)
        * coalesce(p.output_price_per_1m, 0),
        8
    ) as output_cost,
    -- reasoning token 비용
    case
        when e.reasoning_tokens_available and e.reasoning_tokens is not null
        then round(
            (e.reasoning_tokens::numeric / 1000000.0)
            * coalesce(p.reasoning_price_per_1m, 0),
            8
        )
        else 0::numeric
    end as reasoning_cost,
    -- 총 추정 비용
    round(
        (e.uncached_input_tokens::numeric / 1000000.0)
        * coalesce(p.input_price_per_1m, 0)
        + case
            when e.cached_input_tokens_available and e.cached_input_tokens is not null
            then (e.cached_input_tokens::numeric / 1000000.0)
                 * coalesce(p.cached_input_price_per_1m, 0)
            else 0
          end
        + (e.visible_output_tokens::numeric / 1000000.0)
          * coalesce(p.output_price_per_1m, 0)
        + case
            when e.reasoning_tokens_available and e.reasoning_tokens is not null
            then (e.reasoning_tokens::numeric / 1000000.0)
                 * coalesce(p.reasoning_price_per_1m, 0)
            else 0
          end,
        8
    ) as total_estimated_cost,
    'Estimated'::text as cost_accuracy
from codex_usage_events e
left join lateral (
    select *
    from codex_model_price_policy pp
    where lower(pp.model) = lower(e.model)
      and pp.effective_from <= e.event_time
      and (pp.effective_to is null or pp.effective_to > e.event_time)
    order by pp.effective_from desc
    limit 1
) p on true;

-- 팀별 현재 월 비용 vs 예산 비교 뷰
create or replace view codex_team_budget_usage as
with current_budget as (
    select team, monthly_budget, currency
    from codex_team_budget
    where effective_from <= current_date
      and (effective_to is null or effective_to > current_date)
),
month_cost as (
    select
        team,
        sum(total_estimated_cost) as month_cost,
        sum(total_requests)       as month_requests,
        sum(total_tokens)         as month_tokens
    from codex_daily_cost_agg
    where usage_date >= date_trunc('month', current_date)::date
    group by team
),
days as (
    select
        extract(day from current_date)::numeric                                    as elapsed_days,
        extract(days from
            (date_trunc('month', current_date + interval '1 month')
             - date_trunc('month', current_date))
        )::numeric                                                                 as total_days
)
select
    b.team,
    b.monthly_budget,
    b.currency,
    coalesce(m.month_cost, 0)         as current_month_cost,
    coalesce(m.month_requests, 0)     as current_month_requests,
    coalesce(m.month_tokens, 0)       as current_month_tokens,
    round(
        100.0 * coalesce(m.month_cost, 0) / nullif(b.monthly_budget, 0),
        2
    )                                  as budget_usage_pct,
    -- 월말 선형 외삽 forecast
    round(
        coalesce(m.month_cost, 0)
        * d.total_days / nullif(d.elapsed_days, 0),
        4
    )                                  as forecast_month_end_cost,
    b.monthly_budget
    - coalesce(m.month_cost, 0)       as remaining_budget
from current_budget b
cross join days d
left join month_cost m on b.team = m.team;

-- repository별 비용 요약 뷰
create or replace view codex_repo_cost_summary as
select
    repository,
    team,
    sum(total_requests)       as total_requests,
    sum(total_tokens)         as total_tokens,
    sum(total_estimated_cost) as total_estimated_cost,
    currency,
    min(usage_date)           as first_seen,
    max(usage_date)           as last_seen
from codex_daily_cost_agg
group by repository, team, currency;

-- 사용자별 비용 요약 뷰
create or replace view codex_user_cost_summary as
select
    a.user_id,
    coalesce(m.display_name, a.user_id) as display_name,
    coalesce(a.team, m.team, '(unknown)') as team,
    m.department,
    sum(a.total_requests)       as total_requests,
    sum(a.total_tokens)         as total_tokens,
    sum(a.total_estimated_cost) as total_estimated_cost,
    a.currency
from codex_daily_cost_agg a
left join codex_user_mapping m on lower(a.user_id) = lower(m.user_id)
group by a.user_id, m.display_name, a.team, m.team, m.department, a.currency;
