-- codex_fn_call_events: response.function_call_arguments.* 스트리밍 이벤트
create table if not exists codex_fn_call_events (
    id bigserial primary key,
    source_fingerprint text not null unique,
    source_timestamp_ns bigint not null,
    event_time timestamptz not null,
    event_name text not null default 'codex.websocket_event',
    -- response.function_call_arguments.delta | response.function_call_arguments.done
    event_kind text not null,
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
    item_id text,        -- tool call 식별자 (tool_decision.tool_call_id 와 조인 키)
    output_index int,
    call_index int,
    delta_size int,      -- delta 청크 바이트 수 (delta 이벤트만, 내용 미저장)
    arguments_size int,  -- 완성된 arguments 바이트 수 (done 이벤트만)
    is_done boolean not null default false,
    raw_event jsonb not null,
    created_at timestamptz not null default now()
);

create index if not exists idx_codex_fn_call_events_event_time
    on codex_fn_call_events (event_time desc);

create index if not exists idx_codex_fn_call_events_item_session
    on codex_fn_call_events (item_id, session_id);

create index if not exists idx_codex_fn_call_events_user_event_time
    on codex_fn_call_events (user_id, event_time desc);

create index if not exists idx_codex_fn_call_events_team_event_time
    on codex_fn_call_events (team, event_time desc);

create index if not exists idx_codex_fn_call_events_done_event_time
    on codex_fn_call_events (is_done, event_time desc);

create table if not exists codex_fn_call_sync_state (
    pipeline_name text primary key,
    last_source_timestamp_ns bigint not null default 0,
    updated_at timestamptz not null default now()
);

-- user_email -> 내부 user/team 매핑 테이블
create table if not exists codex_user_email_mapping (
    user_email text primary key,
    display_name text,
    team text,
    department text,
    cost_center text,
    github_handle text,
    slack_handle text,
    is_active boolean not null default true,
    -- manual | csv | ldap | api
    source text not null default 'manual',
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_codex_user_email_mapping_team
    on codex_user_email_mapping (team);

create index if not exists idx_codex_user_email_mapping_department
    on codex_user_email_mapping (department);

-- fn_call_events 기본 대시보드 뷰
create or replace view codex_fn_call_events_dashboard as
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

-- usage_events + user_email_mapping enriched 뷰
create or replace view codex_usage_events_enriched as
select
    e.*,
    m.display_name                     as resolved_display_name,
    coalesce(e.team, m.team)           as resolved_team,
    m.department                       as resolved_department,
    m.cost_center                      as resolved_cost_center,
    m.github_handle                    as resolved_github_handle,
    m.is_active                        as user_is_active,
    (m.user_email is not null)         as has_mapping
from codex_usage_events e
left join codex_user_email_mapping m
    on lower(e.user_id) = lower(m.user_email);

-- tool_events + user_email_mapping enriched 뷰
create or replace view codex_tool_events_enriched as
select
    e.*,
    m.display_name                     as resolved_display_name,
    coalesce(e.team, m.team)           as resolved_team,
    m.department                       as resolved_department,
    m.cost_center                      as resolved_cost_center,
    m.github_handle                    as resolved_github_handle,
    m.is_active                        as user_is_active,
    (m.user_email is not null)         as has_mapping
from codex_tool_events e
left join codex_user_email_mapping m
    on lower(e.user_id) = lower(m.user_email);

-- fn_call_events + user_email_mapping enriched 뷰
create or replace view codex_fn_call_events_enriched as
select
    e.*,
    m.display_name                     as resolved_display_name,
    coalesce(e.team, m.team)           as resolved_team,
    m.department                       as resolved_department,
    m.cost_center                      as resolved_cost_center,
    m.github_handle                    as resolved_github_handle,
    m.is_active                        as user_is_active,
    (m.user_email is not null)         as has_mapping
from codex_fn_call_events e
left join codex_user_email_mapping m
    on lower(e.user_id) = lower(m.user_email);

-- Tool Invocation Funnel 뷰:
-- fn_call_arguments.done -> tool_decision -> tool_result 단계별 연결
create or replace view codex_tool_invocation_funnel as
with fn_done as (
    select
        session_id,
        conversation_id,
        item_id,
        user_id,
        team,
        model,
        repository,
        environment,
        min(event_time)      as fn_call_done_at,
        max(arguments_size)  as arguments_size
    from codex_fn_call_events
    where is_done = true
      and item_id is not null
    group by session_id, conversation_id, item_id, user_id, team, model, repository, environment
),
decisions as (
    select
        session_id,
        conversation_id,
        tool_call_id,
        tool_name,
        tool_decision,
        min(event_time) as decision_at
    from codex_tool_events
    where event_name = 'codex.tool_decision'
      and tool_call_id is not null
    group by session_id, conversation_id, tool_call_id, tool_name, tool_decision
),
results as (
    select
        session_id,
        conversation_id,
        tool_call_id,
        tool_name,
        tool_success,
        tool_duration_ms,
        tool_error_code,
        min(event_time) as result_at
    from codex_tool_events
    where event_name = 'codex.tool_result'
      and tool_call_id is not null
    group by session_id, conversation_id, tool_call_id, tool_name, tool_success, tool_duration_ms, tool_error_code
)
select
    f.session_id,
    f.conversation_id,
    f.item_id,
    f.fn_call_done_at,
    d.tool_name,
    d.tool_decision,
    d.decision_at,
    r.tool_success,
    r.tool_duration_ms,
    r.tool_error_code,
    r.result_at,
    f.arguments_size,
    f.user_id,
    f.team,
    f.model,
    f.repository,
    f.environment,
    -- fn_call_done -> decision 준비 시간(ms)
    case
        when d.decision_at is not null
        then extract(epoch from (d.decision_at - f.fn_call_done_at)) * 1000
        else null
    end as prep_to_decision_ms
from fn_done f
left join decisions d
    on f.item_id = d.tool_call_id
    and coalesce(f.session_id, '') = coalesce(d.session_id, '')
left join results r
    on d.tool_call_id = r.tool_call_id
    and coalesce(d.session_id, '') = coalesce(r.session_id, '')
    and coalesce(d.tool_name, '') = coalesce(r.tool_name, '');

-- 매핑 커버리지 요약 뷰 (enrichment 대시보드용)
create or replace view codex_user_mapping_coverage as
with all_users as (
    select distinct lower(user_id) as user_email from codex_usage_events where user_id is not null
    union
    select distinct lower(user_id) from codex_tool_events where user_id is not null
    union
    select distinct lower(user_id) from codex_fn_call_events where user_id is not null
)
select
    a.user_email,
    (m.user_email is not null) as has_mapping,
    m.display_name,
    m.team,
    m.department,
    m.cost_center,
    m.is_active,
    m.source
from all_users a
left join codex_user_email_mapping m on a.user_email = m.user_email;
