create table if not exists codex_local_helper_events (
    id bigserial primary key,
    source_fingerprint text not null unique,
    source_timestamp_ns bigint not null,
    event_time timestamptz not null,
    event_name text not null,
    notification_type text,
    environment text,
    service_name text,
    service_namespace text,
    helper_version text,
    user_id text,
    team text,
    observed_user_email text,
    resolved_user_id text,
    resolved_team text,
    ingest_token_id text,
    thread_id text,
    turn_id text,
    cwd text,
    is_git boolean,
    repo_root text,
    repo_name text,
    git_branch text,
    git_remote_slug text,
    host_name text,
    input_message_count integer,
    input_message_char_count integer,
    last_assistant_message_char_count integer,
    raw_event jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_codex_local_helper_events_event_time
    on codex_local_helper_events (event_time desc);

create index if not exists idx_codex_local_helper_events_thread_event_time
    on codex_local_helper_events (thread_id, event_time desc);

create index if not exists idx_codex_local_helper_events_user_event_time
    on codex_local_helper_events (resolved_user_id, event_time desc);

create index if not exists idx_codex_local_helper_events_team_event_time
    on codex_local_helper_events (resolved_team, event_time desc);

create table if not exists codex_local_helper_sync_state (
    pipeline_name text primary key,
    last_source_timestamp_ns bigint not null default 0,
    updated_at timestamptz not null default now()
);

create or replace view codex_local_helper_events_dashboard as
select
    id,
    source_fingerprint,
    source_timestamp_ns,
    event_time,
    event_name,
    notification_type,
    environment,
    service_name,
    service_namespace,
    helper_version,
    user_id as observed_user_id,
    team as observed_team,
    observed_user_email,
    resolved_user_id,
    resolved_team,
    ingest_token_id,
    coalesce(resolved_user_id, observed_user_email, user_id, '(unknown)') as user_id,
    coalesce(resolved_team, team, '(unknown)') as team,
    thread_id,
    turn_id,
    cwd,
    is_git,
    repo_root,
    repo_name,
    git_branch,
    git_remote_slug,
    host_name,
    input_message_count,
    input_message_char_count,
    last_assistant_message_char_count,
    raw_event,
    created_at
from codex_local_helper_events;

create or replace view codex_prompt_turns_dashboard as
with ordered_helper as (
    select
        e.*,
        lag(e.event_time) over (
            partition by e.thread_id
            order by e.event_time, e.id
        ) as prev_helper_event_time,
        row_number() over (
            partition by e.thread_id
            order by e.event_time, e.id
        ) as turn_sequence
    from codex_local_helper_events_dashboard e
    where e.notification_type = 'agent-turn-complete'
      and e.thread_id is not null
),
usage_rollup as (
    select
        h.id as helper_event_id,
        count(u.id)::bigint as usage_event_count,
        count(distinct u.response_id) filter (where u.response_id is not null)::bigint as response_count,
        string_agg(distinct u.model, ', ' order by u.model)
            filter (where u.model is not null) as models,
        max(u.model) as primary_model,
        coalesce(sum(u.input_tokens), 0)::bigint as input_tokens,
        coalesce(sum(u.output_tokens), 0)::bigint as output_tokens,
        coalesce(sum(u.total_tokens), 0)::bigint as total_tokens,
        round(coalesce(sum(u.total_estimated_cost), 0)::numeric, 8) as estimated_cost_usd
    from ordered_helper h
    left join codex_usage_events_with_cost u
        on u.conversation_id = h.thread_id
       and u.event_time > coalesce(h.prev_helper_event_time, h.event_time - interval '30 minutes')
       and u.event_time <= h.event_time
    group by h.id
),
tool_rollup as (
    select
        h.id as helper_event_id,
        count(t.id) filter (where t.event_name = 'codex.tool_result')::bigint as tool_result_count,
        count(t.id) filter (
            where t.event_name = 'codex.tool_result'
              and t.tool_success = false
        )::bigint as failed_tool_call_count,
        string_agg(distinct t.tool_name, ', ' order by t.tool_name)
            filter (where t.tool_name is not null) as tool_names,
        string_agg(distinct t.tool_name, ', ' order by t.tool_name)
            filter (
                where t.tool_name is not null
                  and t.tool_success = false
            ) as failed_tool_names,
        coalesce(max(t.tool_duration_ms), 0)::bigint as slowest_tool_duration_ms,
        coalesce(
            round(
                (percentile_cont(0.95) within group (order by t.tool_duration_ms))::numeric,
                2
            ),
            0::numeric
        ) as tool_p95_duration_ms
    from ordered_helper h
    left join codex_tool_events_dashboard t
        on t.conversation_id = h.thread_id
       and t.event_name = 'codex.tool_result'
       and t.event_time > coalesce(h.prev_helper_event_time, h.event_time - interval '30 minutes')
       and t.event_time <= h.event_time
    group by h.id
),
api_group as (
    select
        h.id as helper_event_id,
        coalesce(a.request_type, '(unknown)') as request_type,
        count(a.id)::bigint as request_count,
        count(a.id) filter (where a.request_success = false)::bigint as failed_request_count
    from ordered_helper h
    left join codex_api_request_events_dashboard a
        on a.conversation_id = h.thread_id
       and a.event_time > coalesce(h.prev_helper_event_time, h.event_time - interval '30 minutes')
       and a.event_time <= h.event_time
    group by h.id, coalesce(a.request_type, '(unknown)')
),
api_rollup as (
    select
        helper_event_id,
        coalesce(sum(request_count), 0)::bigint as api_request_count,
        coalesce(sum(failed_request_count), 0)::bigint as failed_api_request_count,
        coalesce(sum(greatest(request_count - 1, 0)), 0)::bigint as estimated_retry_count,
        string_agg(
            request_type || ':' || request_count,
            ', '
            order by request_type
        ) filter (where request_count > 0) as request_type_counts
    from api_group
    group by helper_event_id
),
trace_rollup as (
    select
        h.id as helper_event_id,
        coalesce(max(t.session_duration_ms), 0)::bigint as max_trace_session_duration_ms,
        coalesce(max(t.slowest_span_duration_ms), 0)::bigint as slowest_span_duration_ms
    from ordered_helper h
    left join codex_trace_sessions_dashboard t
        on t.conversation_id = h.thread_id
       and t.session_started_at > coalesce(h.prev_helper_event_time, h.event_time - interval '30 minutes')
       and t.session_started_at <= h.event_time
    group by h.id
)
select
    h.id,
    h.source_fingerprint,
    h.source_timestamp_ns,
    h.event_time as helper_event_time,
    coalesce(h.prev_helper_event_time, h.event_time - interval '30 minutes') as window_started_at,
    h.event_time as window_ended_at,
    h.turn_sequence,
    h.notification_type,
    h.environment,
    h.service_name,
    h.service_namespace,
    h.helper_version,
    h.user_id,
    h.team,
    h.thread_id,
    h.turn_id,
    h.cwd,
    h.is_git,
    h.repo_root,
    h.repo_name,
    h.git_branch,
    h.git_remote_slug,
    h.host_name,
    h.input_message_count,
    h.input_message_char_count,
    h.last_assistant_message_char_count,
    coalesce(u.primary_model, '(unknown)') as primary_model,
    coalesce(u.models, '(unknown)') as models,
    coalesce(u.usage_event_count, 0)::bigint as usage_event_count,
    coalesce(u.response_count, 0)::bigint as response_count,
    coalesce(u.input_tokens, 0)::bigint as input_tokens,
    coalesce(u.output_tokens, 0)::bigint as output_tokens,
    coalesce(u.total_tokens, 0)::bigint as total_tokens,
    round(coalesce(u.estimated_cost_usd, 0)::numeric, 8) as estimated_cost_usd,
    coalesce(t.tool_result_count, 0)::bigint as tool_result_count,
    coalesce(t.failed_tool_call_count, 0)::bigint as failed_tool_call_count,
    coalesce(t.tool_names, '') as tool_names,
    coalesce(t.failed_tool_names, '') as failed_tool_names,
    coalesce(t.slowest_tool_duration_ms, 0)::bigint as slowest_tool_duration_ms,
    coalesce(t.tool_p95_duration_ms, 0)::numeric as tool_p95_duration_ms,
    coalesce(a.api_request_count, 0)::bigint as api_request_count,
    coalesce(a.failed_api_request_count, 0)::bigint as failed_api_request_count,
    coalesce(a.estimated_retry_count, 0)::bigint as estimated_retry_count,
    coalesce(a.request_type_counts, '') as request_type_counts,
    coalesce(tr.max_trace_session_duration_ms, 0)::bigint as max_trace_session_duration_ms,
    coalesce(tr.slowest_span_duration_ms, 0)::bigint as slowest_span_duration_ms,
    case
        when coalesce(h.input_message_char_count, 0) < 100 then '<100'
        when coalesce(h.input_message_char_count, 0) < 300 then '100-299'
        when coalesce(h.input_message_char_count, 0) < 600 then '300-599'
        when coalesce(h.input_message_char_count, 0) < 1000 then '600-999'
        when coalesce(h.input_message_char_count, 0) < 2000 then '1000-1999'
        else '2000+'
    end as prompt_char_bucket,
    case
        when coalesce(h.input_message_char_count, 0) < 100 then 1
        when coalesce(h.input_message_char_count, 0) < 300 then 2
        when coalesce(h.input_message_char_count, 0) < 600 then 3
        when coalesce(h.input_message_char_count, 0) < 1000 then 4
        when coalesce(h.input_message_char_count, 0) < 2000 then 5
        else 6
    end as prompt_char_bucket_order,
    round(
        1000.0 * coalesce(u.output_tokens, 0)::numeric
        / nullif(coalesce(h.input_message_char_count, 0), 0),
        2
    ) as output_tokens_per_1k_prompt_chars,
    round(
        1000.0 * coalesce(u.estimated_cost_usd, 0)::numeric
        / nullif(coalesce(h.input_message_char_count, 0), 0),
        8
    ) as cost_per_1k_prompt_chars,
    round(
        100.0 * coalesce(t.failed_tool_call_count, 0)::numeric
        / nullif(coalesce(t.tool_result_count, 0), 0),
        2
    ) as tool_failure_rate_pct,
    round(
        100.0 * coalesce(a.failed_api_request_count, 0)::numeric
        / nullif(coalesce(a.api_request_count, 0), 0),
        2
    ) as api_failure_rate_pct,
    (
        coalesce(t.failed_tool_call_count, 0) > 0
        or coalesce(a.failed_api_request_count, 0) > 0
    ) as has_failure,
    (
        coalesce(u.usage_event_count, 0) > 0
        or coalesce(t.tool_result_count, 0) > 0
        or coalesce(a.api_request_count, 0) > 0
    ) as has_correlated_runtime_events,
    h.raw_event,
    h.created_at
from ordered_helper h
left join usage_rollup u on h.id = u.helper_event_id
left join tool_rollup t on h.id = t.helper_event_id
left join api_rollup a on h.id = a.helper_event_id
left join trace_rollup tr on h.id = tr.helper_event_id;

create or replace view codex_prompt_sessions_dashboard as
select
    min(helper_event_time) as session_started_at,
    max(helper_event_time) as session_last_event_time,
    thread_id,
    max(user_id) as user_id,
    max(team) as team,
    max(repo_name) as repo_name,
    max(git_branch) as git_branch,
    max(git_remote_slug) as git_remote_slug,
    string_agg(distinct primary_model, ', ' order by primary_model)
        filter (where primary_model is not null and primary_model <> '(unknown)') as models,
    count(*)::bigint as turn_count,
    coalesce(sum(input_message_count), 0)::bigint as total_input_message_count,
    coalesce(sum(input_message_char_count), 0)::bigint as total_prompt_chars,
    round(avg(input_message_char_count)::numeric, 2) as avg_prompt_chars_per_turn,
    coalesce(max(input_message_char_count), 0)::bigint as max_prompt_chars_per_turn,
    coalesce(sum(output_tokens), 0)::bigint as total_output_tokens,
    coalesce(sum(total_tokens), 0)::bigint as total_tokens,
    round(coalesce(sum(estimated_cost_usd), 0)::numeric, 8) as total_estimated_cost_usd,
    coalesce(sum(tool_result_count), 0)::bigint as total_tool_result_count,
    coalesce(sum(failed_tool_call_count), 0)::bigint as total_failed_tool_calls,
    coalesce(sum(api_request_count), 0)::bigint as total_api_requests,
    coalesce(sum(failed_api_request_count), 0)::bigint as total_failed_api_requests,
    coalesce(sum(estimated_retry_count), 0)::bigint as total_estimated_retries,
    count(*) filter (where has_failure) as failed_turn_count,
    count(*) filter (where has_correlated_runtime_events) as correlated_turn_count,
    round(
        100.0 * (count(*) filter (where has_failure))::numeric
        / nullif(count(*), 0),
        2
    ) as failed_turn_ratio_pct,
    round(
        1000.0 * coalesce(sum(output_tokens), 0)::numeric
        / nullif(coalesce(sum(input_message_char_count), 0), 0),
        2
    ) as output_tokens_per_1k_prompt_chars,
    round(
        1000.0 * coalesce(sum(estimated_cost_usd), 0)::numeric
        / nullif(coalesce(sum(input_message_char_count), 0), 0),
        8
    ) as cost_per_1k_prompt_chars,
    coalesce(max(max_trace_session_duration_ms), 0)::bigint as session_max_trace_duration_ms,
    coalesce(max(slowest_span_duration_ms), 0)::bigint as session_slowest_span_duration_ms
from codex_prompt_turns_dashboard
group by thread_id;

create or replace view codex_prompt_optimization_candidates_dashboard as
with scored as (
    select
        helper_event_time,
        thread_id,
        turn_id,
        user_id,
        team,
        repo_name,
        git_branch,
        models,
        input_message_count,
        input_message_char_count,
        last_assistant_message_char_count,
        output_tokens,
        total_tokens,
        estimated_cost_usd,
        tool_result_count,
        failed_tool_call_count,
        api_request_count,
        failed_api_request_count,
        estimated_retry_count,
        output_tokens_per_1k_prompt_chars,
        cost_per_1k_prompt_chars,
        case
            when input_message_char_count >= 1200
             and output_tokens < 250
             and failed_tool_call_count = 0
             and failed_api_request_count = 0
             and estimated_retry_count = 0
            then '프롬프트가 길지만 산출이 짧음: 목표와 출력 형식을 더 압축해보세요.'
            when input_message_char_count < 200
             and estimated_retry_count >= 2
            then '프롬프트가 짧고 재시도가 많음: 제약, 기대 산출 형식, 필요한 컨텍스트를 보강해보세요.'
            when input_message_char_count >= 800
             and failed_tool_call_count >= 1
            then '긴 프롬프트와 tool 실패가 함께 나타남: 한 턴에 여러 작업을 몰아넣지 말고 단계별로 분리해보세요.'
            when estimated_cost_usd >= 0.05
             and output_tokens_per_1k_prompt_chars < 150
            then '비용 대비 산출 밀도가 낮음: 배경 설명을 줄이고 필수 제약만 남겨보세요.'
            when failed_api_request_count >= 1
             and estimated_retry_count >= 2
            then 'API 재시도가 잦음: 한 번에 처리할 범위를 줄이고 요청 목적을 더 명확히 적어보세요.'
            else null
        end as recommendation
    from codex_prompt_turns_dashboard
)
select *
from scored
where recommendation is not null;
