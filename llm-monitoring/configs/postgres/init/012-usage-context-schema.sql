create index if not exists idx_codex_usage_events_conversation_event_time
    on codex_usage_events (conversation_id, event_time desc);

create or replace view codex_local_helper_turn_windows as
with ordered_helper as (
    select
        e.id as helper_event_id,
        e.source_fingerprint,
        e.source_timestamp_ns,
        e.event_time as helper_event_time,
        lag(e.event_time) over (
            partition by e.thread_id
            order by e.event_time, e.id
        ) as prev_helper_event_time,
        row_number() over (
            partition by e.thread_id
            order by e.event_time, e.id
        ) as turn_sequence,
        e.user_id,
        e.team,
        e.thread_id,
        e.turn_id,
        e.cwd,
        e.is_git,
        e.repo_root,
        e.repo_name,
        e.git_branch,
        e.git_remote_slug,
        e.host_name
    from codex_local_helper_events_dashboard e
    where e.notification_type = 'agent-turn-complete'
      and e.thread_id is not null
)
select
    helper_event_id,
    source_fingerprint,
    source_timestamp_ns,
    helper_event_time,
    coalesce(prev_helper_event_time, helper_event_time - interval '30 minutes') as window_started_at,
    helper_event_time as window_ended_at,
    turn_sequence,
    user_id,
    team,
    thread_id,
    turn_id,
    cwd,
    is_git,
    repo_root,
    repo_name,
    git_branch,
    git_remote_slug,
    host_name
from ordered_helper;

create or replace view codex_usage_events_dashboard as
select
    u.id,
    u.source_fingerprint,
    u.source_timestamp_ns,
    u.event_time,
    u.event_name,
    u.event_kind,
    u.environment,
    u.service_name,
    u.service_namespace,
    u.codex_version,
    u.user_id as observed_user_id,
    u.team as observed_team,
    u.observed_user_email,
    u.resolved_user_id,
    u.resolved_team,
    u.ingest_token_id,
    coalesce(u.resolved_user_id, u.observed_user_email, u.user_id) as user_id,
    coalesce(u.resolved_team, u.team, '(unknown)') as team,
    coalesce(nullif(u.repository, ''), nullif(hw.repo_name, ''), '(unknown)') as repository,
    u.project,
    u.session_id,
    u.conversation_id,
    u.trace_id,
    u.span_id,
    u.model,
    u.response_id,
    u.input_tokens,
    u.cached_input_tokens,
    u.cached_input_tokens_available,
    u.uncached_input_tokens,
    u.output_tokens,
    u.reasoning_tokens,
    u.reasoning_tokens_available,
    u.visible_output_tokens,
    u.total_tokens,
    u.usage_payload,
    u.raw_event,
    u.created_at,
    nullif(u.repository, '') as raw_repository,
    case
        when nullif(u.repository, '') is not null then 'usage_event'
        when nullif(hw.repo_name, '') is not null then 'local_helper'
        else 'unknown'
    end as repository_source,
    hw.repo_name as helper_repo_name,
    hw.repo_root as helper_repo_root,
    hw.git_branch as helper_git_branch,
    hw.git_remote_slug as helper_git_remote_slug,
    hw.turn_id as helper_turn_id,
    hw.window_started_at as helper_window_started_at,
    hw.window_ended_at as helper_window_ended_at
from codex_usage_events u
left join lateral (
    select
        w.repo_name,
        w.repo_root,
        w.git_branch,
        w.git_remote_slug,
        w.turn_id,
        w.window_started_at,
        w.window_ended_at
    from codex_local_helper_turn_windows w
    where w.thread_id = u.conversation_id
      and u.event_time > w.window_started_at
      and u.event_time <= w.window_ended_at
    order by w.window_ended_at, w.helper_event_id
    limit 1
) hw on true;

create or replace view codex_usage_events_enriched as
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
    (em.user_email is not null or um.user_id is not null) as has_mapping,
    e.raw_repository,
    e.repository_source,
    e.helper_repo_name,
    e.helper_repo_root,
    e.helper_git_branch,
    e.helper_git_remote_slug,
    e.helper_turn_id,
    e.helper_window_started_at,
    e.helper_window_ended_at
from codex_usage_events_dashboard e
left join codex_user_email_mapping em
    on e.observed_user_email = em.user_email
left join codex_user_mapping um
    on lower(coalesce(e.resolved_user_id, e.user_id)) = lower(um.user_id);

create or replace view codex_usage_events_with_cost as
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
    e.observed_user_id as user_id,
    e.observed_team as team,
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
    e.observed_user_email,
    e.resolved_user_id,
    e.resolved_team,
    e.ingest_token_id,
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
    'Estimated'::text as cost_accuracy,
    e.trace_id,
    e.span_id,
    e.raw_repository,
    e.repository_source,
    e.helper_repo_name,
    e.helper_repo_root,
    e.helper_git_branch,
    e.helper_git_remote_slug,
    e.helper_turn_id,
    e.helper_window_started_at,
    e.helper_window_ended_at
from codex_usage_events_dashboard e
left join lateral (
    select *
    from codex_model_price_policy pp
    where lower(pp.model) = lower(e.model)
      and pp.effective_from <= e.event_time
      and (pp.effective_to is null or pp.effective_to > e.event_time)
    order by pp.effective_from desc
    limit 1
) p on true;
