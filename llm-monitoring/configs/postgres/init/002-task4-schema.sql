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

create index if not exists idx_codex_tool_events_event_time
    on codex_tool_events (event_time desc);

create index if not exists idx_codex_tool_events_tool_event_time
    on codex_tool_events (tool_name, event_time desc);

create index if not exists idx_codex_tool_events_team_event_time
    on codex_tool_events (team, event_time desc);

create index if not exists idx_codex_tool_events_user_event_time
    on codex_tool_events (user_id, event_time desc);

create index if not exists idx_codex_tool_events_repository_event_time
    on codex_tool_events (repository, event_time desc);

create index if not exists idx_codex_tool_events_success_event_time
    on codex_tool_events (tool_success, event_time desc);

create index if not exists idx_codex_tool_events_duration_event_time
    on codex_tool_events (tool_duration_ms desc, event_time desc);

create table if not exists codex_tool_sync_state (
    pipeline_name text primary key,
    last_source_timestamp_ns bigint not null default 0,
    updated_at timestamptz not null default now()
);

create or replace view codex_tool_events_dashboard as
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
    user_id,
    team,
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

create or replace view codex_tool_results_dashboard as
select *
from codex_tool_events_dashboard
where event_name = 'codex.tool_result';
