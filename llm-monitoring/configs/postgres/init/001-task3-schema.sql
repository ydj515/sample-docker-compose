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

create index if not exists idx_codex_usage_events_event_time
    on codex_usage_events (event_time desc);

create index if not exists idx_codex_usage_events_model_event_time
    on codex_usage_events (model, event_time desc);

create index if not exists idx_codex_usage_events_team_event_time
    on codex_usage_events (team, event_time desc);

create index if not exists idx_codex_usage_events_user_event_time
    on codex_usage_events (user_id, event_time desc);

create index if not exists idx_codex_usage_events_repository_event_time
    on codex_usage_events (repository, event_time desc);

create table if not exists codex_usage_sync_state (
    pipeline_name text primary key,
    last_source_timestamp_ns bigint not null default 0,
    updated_at timestamptz not null default now()
);

create or replace view codex_usage_events_dashboard as
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
