-- ─────────────────────────────────────────────────────────────
-- Seed canonical users and email aliases from CSV
-- ─────────────────────────────────────────────────────────────

create temp table codex_user_seed_csv_raw (
    user_email text,
    resolved_user_id text,
    canonical_email text,
    display_name text,
    team text,
    department text,
    cost_center text,
    github_handle text,
    slack_handle text,
    is_active text,
    notes text
);

copy codex_user_seed_csv_raw (
    user_email,
    resolved_user_id,
    canonical_email,
    display_name,
    team,
    department,
    cost_center,
    github_handle,
    slack_handle,
    is_active,
    notes
) from '/seed-data/user-mapping-sample.csv' with (format csv, header true);

create temp table codex_user_seed_csv as
select
    lower(trim(user_email)) as user_email,
    nullif(trim(resolved_user_id), '') as resolved_user_id,
    lower(nullif(trim(canonical_email), '')) as canonical_email,
    nullif(trim(display_name), '') as display_name,
    nullif(trim(team), '') as team,
    nullif(trim(department), '') as department,
    nullif(trim(cost_center), '') as cost_center,
    nullif(trim(github_handle), '') as github_handle,
    nullif(trim(slack_handle), '') as slack_handle,
    case
        when lower(trim(coalesce(is_active, 'true'))) in ('false', '0', 'no', 'n') then false
        else true
    end as is_active,
    nullif(trim(notes), '') as notes
from codex_user_seed_csv_raw
where trim(coalesce(user_email, '')) <> '';

do $$
begin
    if exists (
        select 1
        from codex_user_seed_csv
        group by user_email
        having count(distinct coalesce(resolved_user_id, '')) > 1
    ) then
        raise exception 'configs/user-mapping-sample.csv contains conflicting resolved_user_id values for the same user_email';
    end if;

    if exists (
        select 1
        from codex_user_seed_csv
        where resolved_user_id is not null
        group by resolved_user_id
        having count(distinct canonical_email) filter (where canonical_email is not null) > 1
    ) then
        raise exception 'configs/user-mapping-sample.csv contains conflicting canonical_email values for the same resolved_user_id';
    end if;
end $$;

insert into codex_user_mapping (
    user_id,
    display_name,
    email,
    team,
    department,
    active,
    updated_at
)
select
    resolved_user_id as user_id,
    max(display_name) filter (where display_name is not null) as display_name,
    max(canonical_email) filter (where canonical_email is not null) as email,
    max(team) filter (where team is not null) as team,
    max(department) filter (where department is not null) as department,
    bool_or(is_active) as active,
    now() as updated_at
from codex_user_seed_csv
where resolved_user_id is not null
group by resolved_user_id
on conflict (user_id) do update set
    display_name = coalesce(excluded.display_name, codex_user_mapping.display_name),
    email = coalesce(excluded.email, codex_user_mapping.email),
    team = coalesce(excluded.team, codex_user_mapping.team),
    department = coalesce(excluded.department, codex_user_mapping.department),
    active = excluded.active,
    updated_at = now();

insert into codex_user_email_mapping (
    user_email,
    resolved_user_id,
    display_name,
    team,
    department,
    cost_center,
    github_handle,
    slack_handle,
    is_active,
    source,
    notes,
    updated_at
)
select
    user_email,
    resolved_user_id,
    display_name,
    team,
    department,
    cost_center,
    github_handle,
    slack_handle,
    is_active,
    'seed' as source,
    notes,
    now() as updated_at
from codex_user_seed_csv
on conflict (user_email) do update set
    resolved_user_id = coalesce(excluded.resolved_user_id, codex_user_email_mapping.resolved_user_id),
    display_name = coalesce(excluded.display_name, codex_user_email_mapping.display_name),
    team = coalesce(excluded.team, codex_user_email_mapping.team),
    department = coalesce(excluded.department, codex_user_email_mapping.department),
    cost_center = coalesce(excluded.cost_center, codex_user_email_mapping.cost_center),
    github_handle = coalesce(excluded.github_handle, codex_user_email_mapping.github_handle),
    slack_handle = coalesce(excluded.slack_handle, codex_user_email_mapping.slack_handle),
    is_active = excluded.is_active,
    source = excluded.source,
    notes = coalesce(excluded.notes, codex_user_email_mapping.notes),
    updated_at = now();
