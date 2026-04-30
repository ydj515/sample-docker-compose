create table if not exists codex_api_request_events (
    id bigserial primary key,
    source_fingerprint text not null unique,
    source_timestamp_ns bigint not null,
    event_time timestamptz not null,
    event_name text not null,
    request_type text not null,
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
    auth_mode text,
    request_success boolean,
    request_duration_ms bigint,
    status_code integer,
    error_code text,
    error_message text,
    raw_event jsonb not null,
    created_at timestamptz not null default now()
);

create index if not exists idx_codex_api_request_events_event_time
    on codex_api_request_events (event_time desc);

create index if not exists idx_codex_api_request_events_type_event_time
    on codex_api_request_events (request_type, event_time desc);

create index if not exists idx_codex_api_request_events_success_event_time
    on codex_api_request_events (request_success, event_time desc);

create index if not exists idx_codex_api_request_events_user_event_time
    on codex_api_request_events (user_id, event_time desc);

create table if not exists codex_api_request_sync_state (
    pipeline_name text primary key,
    last_source_timestamp_ns bigint not null default 0,
    updated_at timestamptz not null default now()
);

create or replace view codex_api_request_events_dashboard as
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
    user_id,
    team,
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
