-- ─────────────────────────────────────────────────────────────
-- Identity resolution for gateway token mapping and email aliases
-- ─────────────────────────────────────────────────────────────

create table if not exists codex_ingest_token_mapping (
    id bigserial primary key,
    ingest_token_id text not null unique,
    token_hash text,
    resolved_user_id text,
    resolved_team text,
    description text,
    is_active boolean not null default true,
    expires_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists uq_codex_ingest_token_mapping_token_hash
    on codex_ingest_token_mapping (token_hash)
    where token_hash is not null;

create index if not exists idx_codex_ingest_token_mapping_user
    on codex_ingest_token_mapping (resolved_user_id);

create index if not exists idx_codex_ingest_token_mapping_team
    on codex_ingest_token_mapping (resolved_team);

alter table codex_user_email_mapping
    add column if not exists resolved_user_id text;

create index if not exists idx_codex_user_email_mapping_resolved_user
    on codex_user_email_mapping (resolved_user_id);

alter table codex_usage_events
    add column if not exists observed_user_email text,
    add column if not exists resolved_user_id text,
    add column if not exists resolved_team text,
    add column if not exists ingest_token_id text;

create index if not exists idx_codex_usage_events_resolved_user_event_time
    on codex_usage_events (resolved_user_id, event_time desc);

create index if not exists idx_codex_usage_events_resolved_team_event_time
    on codex_usage_events (resolved_team, event_time desc);

create index if not exists idx_codex_usage_events_observed_email_event_time
    on codex_usage_events (observed_user_email, event_time desc);

alter table codex_tool_events
    add column if not exists observed_user_email text,
    add column if not exists resolved_user_id text,
    add column if not exists resolved_team text,
    add column if not exists ingest_token_id text;

create index if not exists idx_codex_tool_events_resolved_user_event_time
    on codex_tool_events (resolved_user_id, event_time desc);

create index if not exists idx_codex_tool_events_resolved_team_event_time
    on codex_tool_events (resolved_team, event_time desc);

create index if not exists idx_codex_tool_events_observed_email_event_time
    on codex_tool_events (observed_user_email, event_time desc);

alter table codex_api_request_events
    add column if not exists observed_user_email text,
    add column if not exists resolved_user_id text,
    add column if not exists resolved_team text,
    add column if not exists ingest_token_id text;

create index if not exists idx_codex_api_request_events_resolved_user_event_time
    on codex_api_request_events (resolved_user_id, event_time desc);

create index if not exists idx_codex_api_request_events_resolved_team_event_time
    on codex_api_request_events (resolved_team, event_time desc);

create index if not exists idx_codex_api_request_events_observed_email_event_time
    on codex_api_request_events (observed_user_email, event_time desc);

-- 배포용 초기화에서는 사용자 seed와 historical backfill을 별도 파일/도구로 분리한다.

drop view if exists codex_usage_events_enriched;
drop view if exists codex_tool_events_enriched;
drop view if exists codex_fn_call_events_enriched;
drop view if exists codex_user_mapping_coverage;
drop view if exists codex_tool_results_dashboard;
drop view if exists codex_usage_events_dashboard;
drop view if exists codex_tool_events_dashboard;
drop view if exists codex_api_request_events_dashboard;

create view codex_usage_events_dashboard as
select
    id,
    source_fingerprint,
    source_timestamp_ns,
    event_time,
    event_name,
    event_kind,
    environment,
    service_name,
    service_namespace,
    codex_version,
    user_id as observed_user_id,
    team as observed_team,
    observed_user_email,
    resolved_user_id,
    resolved_team,
    ingest_token_id,
    coalesce(resolved_user_id, observed_user_email, user_id) as user_id,
    coalesce(resolved_team, team) as team,
    repository,
    project,
    session_id,
    conversation_id,
    model,
    response_id,
    input_tokens,
    cached_input_tokens,
    cached_input_tokens_available,
    uncached_input_tokens,
    output_tokens,
    reasoning_tokens,
    reasoning_tokens_available,
    visible_output_tokens,
    total_tokens,
    usage_payload,
    raw_event,
    created_at
from codex_usage_events;

create view codex_tool_events_dashboard as
select
    id,
    source_fingerprint,
    source_timestamp_ns,
    event_time,
    event_name,
    environment,
    service_name,
    service_namespace,
    codex_version,
    user_id as observed_user_id,
    team as observed_team,
    observed_user_email,
    resolved_user_id,
    resolved_team,
    ingest_token_id,
    coalesce(resolved_user_id, observed_user_email, user_id) as user_id,
    coalesce(resolved_team, team) as team,
    repository,
    project,
    session_id,
    conversation_id,
    model,
    tool_name,
    tool_call_id,
    tool_decision,
    tool_success,
    tool_duration_ms,
    tool_error_code,
    tool_error_message,
    tool_output_size,
    raw_event,
    created_at
from codex_tool_events;

create view codex_tool_results_dashboard as
select *
from codex_tool_events_dashboard
where event_name = 'codex.tool_result';

create view codex_api_request_events_dashboard as
select
    id,
    source_fingerprint,
    source_timestamp_ns,
    event_time,
    event_name,
    request_type,
    environment,
    service_name,
    service_namespace,
    codex_version,
    user_id as observed_user_id,
    team as observed_team,
    observed_user_email,
    resolved_user_id,
    resolved_team,
    ingest_token_id,
    coalesce(resolved_user_id, observed_user_email, user_id) as user_id,
    coalesce(resolved_team, team) as team,
    repository,
    project,
    session_id,
    conversation_id,
    model,
    auth_mode,
    request_success,
    request_duration_ms,
    status_code,
    error_code,
    error_message,
    raw_event,
    created_at
from codex_api_request_events;

create view codex_usage_events_enriched as
select
    e.id,
    e.source_fingerprint,
    e.source_timestamp_ns,
    e.event_time,
    e.event_name,
    e.event_kind,
    e.environment,
    e.service_name,
    e.service_namespace,
    e.codex_version,
    e.observed_user_id,
    e.observed_team,
    e.observed_user_email,
    e.resolved_user_id,
    coalesce(e.resolved_team, em.team, um.team, e.observed_team) as resolved_team,
    e.ingest_token_id,
    e.user_id,
    e.team,
    e.repository,
    e.project,
    e.session_id,
    e.conversation_id,
    e.model,
    e.response_id,
    e.input_tokens,
    e.cached_input_tokens,
    e.cached_input_tokens_available,
    e.uncached_input_tokens,
    e.output_tokens,
    e.reasoning_tokens,
    e.reasoning_tokens_available,
    e.visible_output_tokens,
    e.total_tokens,
    e.usage_payload,
    e.raw_event,
    e.created_at,
    coalesce(um.display_name, em.display_name)     as resolved_display_name,
    coalesce(um.department, em.department)         as resolved_department,
    em.cost_center                                 as resolved_cost_center,
    em.github_handle                               as resolved_github_handle,
    coalesce(um.active, em.is_active, true)        as user_is_active,
    (em.user_email is not null or um.user_id is not null) as has_mapping
from codex_usage_events_dashboard e
left join codex_user_email_mapping em
    on e.observed_user_email = em.user_email
left join codex_user_mapping um
    on lower(coalesce(e.resolved_user_id, e.user_id)) = lower(um.user_id);

create view codex_tool_events_enriched as
select
    e.id,
    e.source_fingerprint,
    e.source_timestamp_ns,
    e.event_time,
    e.event_name,
    e.environment,
    e.service_name,
    e.service_namespace,
    e.codex_version,
    e.observed_user_id,
    e.observed_team,
    e.observed_user_email,
    e.resolved_user_id,
    coalesce(e.resolved_team, em.team, um.team, e.observed_team) as resolved_team,
    e.ingest_token_id,
    e.user_id,
    e.team,
    e.repository,
    e.project,
    e.session_id,
    e.conversation_id,
    e.model,
    e.tool_name,
    e.tool_call_id,
    e.tool_decision,
    e.tool_success,
    e.tool_duration_ms,
    e.tool_error_code,
    e.tool_error_message,
    e.tool_output_size,
    e.raw_event,
    e.created_at,
    coalesce(um.display_name, em.display_name)     as resolved_display_name,
    coalesce(um.department, em.department)         as resolved_department,
    em.cost_center                                 as resolved_cost_center,
    em.github_handle                               as resolved_github_handle,
    coalesce(um.active, em.is_active, true)        as user_is_active,
    (em.user_email is not null or um.user_id is not null) as has_mapping
from codex_tool_events_dashboard e
left join codex_user_email_mapping em
    on e.observed_user_email = em.user_email
left join codex_user_mapping um
    on lower(coalesce(e.resolved_user_id, e.user_id)) = lower(um.user_id);

create view codex_fn_call_events_enriched as
select
    e.*,
    m.resolved_user_id                              as resolved_user_id,
    m.display_name                                  as resolved_display_name,
    coalesce(m.team, um.team, e.team)              as resolved_team,
    coalesce(um.department, m.department)          as resolved_department,
    m.cost_center                                   as resolved_cost_center,
    m.github_handle                                 as resolved_github_handle,
    coalesce(um.active, m.is_active, true)         as user_is_active,
    (m.user_email is not null or um.user_id is not null) as has_mapping
from codex_fn_call_events e
left join codex_user_email_mapping m
    on lower(e.user_id) = m.user_email
left join codex_user_mapping um
    on lower(coalesce(m.resolved_user_id, e.user_id)) = lower(um.user_id);

create view codex_user_mapping_coverage as
with all_users as (
    select distinct
        coalesce(
            lower(nullif(observed_user_email, '')),
            case
                when position('@' in coalesce(user_id, '')) > 0 then lower(user_id)
                else null
            end
        ) as user_email,
        nullif(resolved_user_id, '') as resolved_user_id
    from codex_usage_events
    union
    select distinct
        coalesce(
            lower(nullif(observed_user_email, '')),
            case
                when position('@' in coalesce(user_id, '')) > 0 then lower(user_id)
                else null
            end
        ) as user_email,
        nullif(resolved_user_id, '') as resolved_user_id
    from codex_tool_events
    union
    select distinct
        case
            when position('@' in coalesce(user_id, '')) > 0 then lower(user_id)
            else null
        end as user_email,
        nullif(m.resolved_user_id, '') as resolved_user_id
    from codex_fn_call_events e
    left join codex_user_email_mapping m on lower(e.user_id) = m.user_email
)
select
    a.user_email,
    coalesce(a.resolved_user_id, m.resolved_user_id) as resolved_user_id,
    (m.user_email is not null or um.user_id is not null) as has_mapping,
    coalesce(um.display_name, m.display_name) as display_name,
    coalesce(m.team, um.team) as team,
    coalesce(um.department, m.department) as department,
    m.cost_center,
    coalesce(um.active, m.is_active, true) as is_active,
    m.source
from all_users a
left join codex_user_email_mapping m on a.user_email = m.user_email
left join codex_user_mapping um on lower(coalesce(a.resolved_user_id, m.resolved_user_id)) = lower(um.user_id)
where a.user_email is not null;

drop view if exists codex_usage_events_with_cost;

create view codex_usage_events_with_cost as
select
    e.*,
    coalesce(p.version, 'unknown')  as price_policy_version,
    coalesce(p.currency, 'USD')     as currency,
    round(
        (e.uncached_input_tokens::numeric / 1000000.0)
        * coalesce(p.input_price_per_1m, 0),
        8
    ) as input_cost,
    case
        when e.cached_input_tokens_available and e.cached_input_tokens is not null
        then round(
            (e.cached_input_tokens::numeric / 1000000.0)
            * coalesce(p.cached_input_price_per_1m, 0),
            8
        )
        else 0::numeric
    end as cached_input_cost,
    round(
        (e.visible_output_tokens::numeric / 1000000.0)
        * coalesce(p.output_price_per_1m, 0),
        8
    ) as output_cost,
    case
        when e.reasoning_tokens_available and e.reasoning_tokens is not null
        then round(
            (e.reasoning_tokens::numeric / 1000000.0)
            * coalesce(p.reasoning_price_per_1m, 0),
            8
        )
        else 0::numeric
    end as reasoning_cost,
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
