create table if not exists codex_job_run_status (
    job_name text primary key,
    job_group text not null,
    last_status text not null default 'never'
        check (last_status in ('never', 'running', 'success', 'failure')),
    last_started_at timestamptz,
    last_finished_at timestamptz,
    last_success_at timestamptz,
    last_failure_at timestamptz,
    last_duration_seconds numeric(18, 3),
    last_error_message text,
    updated_at timestamptz not null default now()
);

create index if not exists idx_codex_job_run_status_group
    on codex_job_run_status (job_group, job_name);

create or replace view codex_job_run_status_dashboard as
select
    job_name,
    job_group,
    last_status,
    last_started_at,
    last_finished_at,
    last_success_at,
    last_failure_at,
    last_duration_seconds,
    last_error_message,
    updated_at
from codex_job_run_status;
