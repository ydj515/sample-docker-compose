alter table if exists codex_usage_events
    add column if not exists trace_id text,
    add column if not exists span_id text;

create index if not exists idx_codex_usage_events_trace_event_time
    on codex_usage_events (trace_id, event_time desc);

create index if not exists idx_codex_usage_events_span_event_time
    on codex_usage_events (span_id, event_time desc);

alter table if exists codex_tool_events
    add column if not exists trace_id text,
    add column if not exists span_id text;

create index if not exists idx_codex_tool_events_trace_event_time
    on codex_tool_events (trace_id, event_time desc);

create index if not exists idx_codex_tool_events_span_event_time
    on codex_tool_events (span_id, event_time desc);

alter table if exists codex_api_request_events
    add column if not exists trace_id text,
    add column if not exists span_id text;

create index if not exists idx_codex_api_request_events_trace_event_time
    on codex_api_request_events (trace_id, event_time desc);

create index if not exists idx_codex_api_request_events_span_event_time
    on codex_api_request_events (span_id, event_time desc);

alter table if exists codex_fn_call_events
    add column if not exists trace_id text,
    add column if not exists span_id text;

create index if not exists idx_codex_fn_call_events_trace_event_time
    on codex_fn_call_events (trace_id, event_time desc);

create index if not exists idx_codex_fn_call_events_span_event_time
    on codex_fn_call_events (span_id, event_time desc);

drop view if exists codex_trace_sessions_dashboard;
drop view if exists codex_trace_approval_spans_dashboard;
drop view if exists codex_trace_log_correlation_dashboard;
drop view if exists codex_trace_events_union;
drop view if exists codex_trace_spans_dashboard;
drop view if exists codex_usage_events_enriched;
drop view if exists codex_tool_events_enriched;
drop view if exists codex_fn_call_events_enriched;
drop view if exists codex_usage_events_dashboard;
drop view if exists codex_tool_results_dashboard;
drop view if exists codex_tool_events_dashboard;
drop view if exists codex_api_request_events_dashboard;
drop view if exists codex_fn_call_events_dashboard;

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
    coalesce(resolved_team, team, '(unknown)') as team,
    repository,
    project,
    session_id,
    conversation_id,
    trace_id,
    span_id,
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
    coalesce(resolved_team, team, '(unknown)') as team,
    repository,
    project,
    session_id,
    conversation_id,
    trace_id,
    span_id,
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
    coalesce(resolved_team, team, '(unknown)') as team,
    repository,
    project,
    session_id,
    conversation_id,
    trace_id,
    span_id,
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

create view codex_fn_call_events_dashboard as
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
    user_id,
    team,
    repository,
    project,
    session_id,
    conversation_id,
    trace_id,
    span_id,
    model,
    response_id,
    item_id,
    output_index,
    call_index,
    delta_size,
    arguments_size,
    is_done,
    raw_event,
    created_at
from codex_fn_call_events;

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
    e.trace_id,
    e.span_id,
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
    e.trace_id,
    e.span_id,
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

create table if not exists codex_trace_spans (
    id bigserial primary key,
    source_fingerprint text not null unique,
    trace_id text not null,
    span_id text not null,
    parent_span_id text,
    root_trace_name text,
    root_service_name text,
    event_time timestamptz not null,
    end_time timestamptz not null,
    duration_ms bigint not null,
    span_name text not null,
    span_kind text,
    service_name text,
    service_namespace text,
    service_version text,
    scope_name text,
    scope_version text,
    environment text,
    user_id text,
    team text,
    resolved_user_id text,
    resolved_team text,
    ingest_token_id text,
    session_id text,
    conversation_id text,
    turn_id text,
    model text,
    rpc_system text,
    rpc_method text,
    transport text,
    provider text,
    api_path text,
    tool_name text,
    tool_call_id text,
    tool_success boolean,
    busy_ns bigint,
    idle_ns bigint,
    resource_attributes jsonb not null default '{}'::jsonb,
    span_attributes jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create unique index if not exists uq_codex_trace_spans_trace_span
    on codex_trace_spans (trace_id, span_id);

create index if not exists idx_codex_trace_spans_event_time
    on codex_trace_spans (event_time desc);

create index if not exists idx_codex_trace_spans_duration
    on codex_trace_spans (duration_ms desc, event_time desc);

create index if not exists idx_codex_trace_spans_user_event_time
    on codex_trace_spans (resolved_user_id, event_time desc);

create index if not exists idx_codex_trace_spans_team_event_time
    on codex_trace_spans (resolved_team, event_time desc);

create index if not exists idx_codex_trace_spans_conversation_event_time
    on codex_trace_spans (conversation_id, event_time desc);

create index if not exists idx_codex_trace_spans_name_event_time
    on codex_trace_spans (span_name, event_time desc);

create table if not exists codex_trace_sync_state (
    pipeline_name text primary key,
    last_source_timestamp_ns bigint not null default 0,
    updated_at timestamptz not null default now()
);

create or replace view codex_trace_spans_dashboard as
select
    id,
    source_fingerprint,
    trace_id,
    span_id,
    parent_span_id,
    root_trace_name,
    root_service_name,
    event_time,
    end_time,
    duration_ms,
    span_name,
    span_kind,
    service_name,
    service_namespace,
    service_version,
    scope_name,
    scope_version,
    environment,
    user_id as observed_user_id,
    team as observed_team,
    resolved_user_id,
    resolved_team,
    ingest_token_id,
    coalesce(resolved_user_id, user_id, '(unknown)') as user_id,
    coalesce(resolved_team, team, '(unknown)') as team,
    session_id,
    conversation_id,
    turn_id,
    model,
    rpc_system,
    rpc_method,
    transport,
    provider,
    api_path,
    tool_name,
    tool_call_id,
    tool_success,
    busy_ns,
    idle_ns,
    (parent_span_id is null or parent_span_id = '') as is_root_span,
    resource_attributes,
    span_attributes,
    created_at
from codex_trace_spans;

create or replace view codex_trace_events_union as
select
    'usage'::text as event_source,
    event_time,
    trace_id,
    span_id,
    conversation_id,
    session_id,
    user_id,
    team,
    resolved_user_id,
    resolved_team,
    model,
    event_name,
    event_kind,
    null::text as request_type,
    null::text as tool_name,
    null::boolean as tool_success,
    null::bigint as tool_duration_ms,
    response_id,
    null::text as item_id,
    null::integer as arguments_size,
    total_tokens,
    raw_event
from codex_usage_events_dashboard
where trace_id is not null

union all

select
    'tool'::text as event_source,
    event_time,
    trace_id,
    span_id,
    conversation_id,
    session_id,
    user_id,
    team,
    resolved_user_id,
    resolved_team,
    model,
    event_name,
    null::text as event_kind,
    null::text as request_type,
    tool_name,
    tool_success,
    tool_duration_ms,
    null::text as response_id,
    tool_call_id as item_id,
    null::integer as arguments_size,
    null::bigint as total_tokens,
    raw_event
from codex_tool_events_dashboard
where trace_id is not null

union all

select
    'api'::text as event_source,
    event_time,
    trace_id,
    span_id,
    conversation_id,
    session_id,
    user_id,
    team,
    resolved_user_id,
    resolved_team,
    model,
    event_name,
    null::text as event_kind,
    request_type,
    null::text as tool_name,
    null::boolean as tool_success,
    request_duration_ms as tool_duration_ms,
    null::text as response_id,
    null::text as item_id,
    null::integer as arguments_size,
    null::bigint as total_tokens,
    raw_event
from codex_api_request_events_dashboard
where trace_id is not null

union all

select
    'fn_call'::text as event_source,
    event_time,
    trace_id,
    span_id,
    conversation_id,
    session_id,
    coalesce(resolved_user_id, user_id) as user_id,
    coalesce(resolved_team, team, '(unknown)') as team,
    resolved_user_id,
    resolved_team,
    model,
    event_name,
    event_kind,
    null::text as request_type,
    null::text as tool_name,
    null::boolean as tool_success,
    null::bigint as tool_duration_ms,
    response_id,
    item_id,
    arguments_size,
    null::bigint as total_tokens,
    raw_event
from codex_fn_call_events_enriched
where trace_id is not null;

create or replace view codex_trace_log_correlation_dashboard as
select
    e.event_source,
    e.event_time,
    e.trace_id,
    e.span_id,
    e.conversation_id,
    e.session_id,
    coalesce(e.resolved_user_id, e.user_id, s.resolved_user_id, s.user_id, '(unknown)') as user_id,
    coalesce(e.resolved_team, e.team, s.resolved_team, s.team, '(unknown)') as team,
    e.resolved_user_id,
    coalesce(e.resolved_team, s.resolved_team, e.team, s.team) as resolved_team,
    e.model,
    e.event_name,
    e.event_kind,
    e.request_type,
    e.tool_name,
    e.tool_success,
    e.tool_duration_ms,
    e.response_id,
    e.item_id,
    e.arguments_size,
    e.total_tokens,
    s.span_name as correlated_span_name,
    s.duration_ms as correlated_span_duration_ms,
    s.span_kind as correlated_span_kind,
    s.service_name as trace_service_name,
    s.scope_name as trace_scope_name,
    s.root_trace_name,
    s.root_service_name
from codex_trace_events_union e
left join lateral (
    select
        s1.user_id,
        s1.team,
        s1.resolved_user_id,
        s1.resolved_team,
        s1.span_name,
        s1.duration_ms,
        s1.span_kind,
        s1.service_name,
        s1.scope_name,
        s1.root_trace_name,
        s1.root_service_name
    from codex_trace_spans s1
    where s1.trace_id = e.trace_id
    order by
        case
            when coalesce(e.span_id, '') <> '' and s1.span_id = e.span_id then 0
            else 1
        end,
        abs(extract(epoch from (s1.event_time - e.event_time))) asc,
        s1.duration_ms desc
    limit 1
) s on true;

create or replace view codex_trace_sessions_dashboard as
with trace_events as (
    select
        trace_id,
        max(conversation_id) filter (where conversation_id is not null) as conversation_id,
        max(session_id) filter (where session_id is not null) as session_id,
        max(user_id) filter (where user_id is not null) as user_id,
        max(team) filter (where team is not null) as team,
        max(resolved_user_id) filter (where resolved_user_id is not null) as resolved_user_id,
        max(resolved_team) filter (where resolved_team is not null) as resolved_team,
        max(model) filter (where model is not null) as model,
        count(*) as log_event_count,
        count(*) filter (where event_source = 'usage') as usage_event_count,
        count(*) filter (where event_source = 'tool') as tool_event_count,
        count(*) filter (where event_source = 'api') as api_event_count,
        count(*) filter (where event_source = 'fn_call') as fn_call_event_count
    from codex_trace_log_correlation_dashboard
    group by trace_id
),
slowest as (
    select distinct on (trace_id)
        trace_id,
        span_id as slowest_span_id,
        span_name as slowest_span_name,
        duration_ms as slowest_span_duration_ms
    from codex_trace_spans
    order by trace_id, duration_ms desc, event_time asc
),
roots as (
    select distinct on (trace_id)
        trace_id,
        span_name as root_span_name,
        service_name as root_service_name,
        duration_ms as root_span_duration_ms
    from codex_trace_spans
    where parent_span_id is null or parent_span_id = ''
    order by trace_id, event_time asc
)
select
    s.trace_id,
    min(s.event_time) as session_started_at,
    max(s.end_time) as session_finished_at,
    greatest(
        round(extract(epoch from (max(s.end_time) - min(s.event_time))) * 1000.0)::bigint,
        max(s.duration_ms)
    ) as session_duration_ms,
    count(*) as span_count,
    coalesce(r.root_span_name, max(s.root_trace_name), max(s.span_name)) as root_span_name,
    coalesce(r.root_service_name, max(s.root_service_name), max(s.service_name)) as root_service_name,
    max(s.service_name) as service_name,
    max(s.environment) as environment,
    coalesce(max(te.user_id), max(s.resolved_user_id), max(s.user_id), '(unknown)') as user_id,
    coalesce(max(te.team), max(s.resolved_team), max(s.team), '(unknown)') as team,
    max(s.resolved_user_id) as resolved_user_id,
    max(s.resolved_team) as resolved_team,
    max(s.ingest_token_id) as ingest_token_id,
    coalesce(max(te.conversation_id), max(s.conversation_id)) as conversation_id,
    coalesce(max(te.session_id), max(s.session_id)) as session_id,
    max(s.turn_id) as turn_id,
    coalesce(max(te.model), max(s.model)) as model,
    coalesce(max(te.log_event_count), 0) as log_event_count,
    coalesce(max(te.usage_event_count), 0) as usage_event_count,
    coalesce(max(te.tool_event_count), 0) as tool_event_count,
    coalesce(max(te.api_event_count), 0) as api_event_count,
    coalesce(max(te.fn_call_event_count), 0) as fn_call_event_count,
    round(sum(coalesce(s.busy_ns, 0)) / 1000000.0)::bigint as total_busy_ms,
    round(sum(coalesce(s.idle_ns, 0)) / 1000000.0)::bigint as total_idle_ms,
    slow.slowest_span_id,
    slow.slowest_span_name,
    slow.slowest_span_duration_ms
from codex_trace_spans s
left join trace_events te on s.trace_id = te.trace_id
left join roots r on s.trace_id = r.trace_id
left join slowest slow on s.trace_id = slow.trace_id
group by
    s.trace_id,
    r.root_span_name,
    r.root_service_name,
    slow.slowest_span_id,
    slow.slowest_span_name,
    slow.slowest_span_duration_ms;

create or replace view codex_trace_approval_spans_dashboard as
select
    s.trace_id,
    s.span_id,
    s.event_time,
    s.end_time,
    s.duration_ms as approval_duration_ms,
    case
        when s.span_name = 'op.dispatch.exec_approval' then 'exec'
        when s.span_name = 'op.dispatch.patch_approval' then 'patch'
        when s.span_name like 'op.dispatch.%_approval'
            then replace(replace(s.span_name, 'op.dispatch.', ''), '_approval', '')
        else 'unknown'
    end as approval_type,
    s.span_name,
    coalesce(ts.user_id, s.resolved_user_id, s.user_id, '(unknown)') as user_id,
    coalesce(ts.team, s.resolved_team, s.team, '(unknown)') as team,
    ts.resolved_user_id,
    coalesce(ts.resolved_team, s.resolved_team, ts.team, s.team) as resolved_team,
    ts.conversation_id,
    ts.session_id,
    ts.model,
    ts.root_span_name,
    ts.slowest_span_name,
    ts.slowest_span_duration_ms,
    s.service_name,
    s.scope_name,
    s.ingest_token_id
from codex_trace_spans s
left join codex_trace_sessions_dashboard ts on s.trace_id = ts.trace_id
where s.span_name like 'op.dispatch.%_approval';
