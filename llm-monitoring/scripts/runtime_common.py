#!/usr/bin/env python3
"""스크립트 런타임 공통 유틸."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class PostgresTarget:
    database: str
    user: str
    host: str | None
    port: int
    container_id: str | None

    @property
    def is_direct(self) -> bool:
        return bool(self.host)


@dataclass
class IdentityMaps:
    canonical_users: dict[str, dict[str, str | None]]
    email_aliases: dict[str, dict[str, str | None]]
    token_mappings: dict[str, dict[str, str | None]]
    token_hash_mappings: dict[str, dict[str, str | None]]


@dataclass
class ResolvedIdentity:
    observed_user_email: str | None
    resolved_user_id: str | None
    resolved_team: str | None
    ingest_token_id: str | None


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_key(value: Any) -> str | None:
    text = normalize_text(value)
    if text is None:
        return None
    return text.lower()


def normalize_email(value: Any) -> str | None:
    text = normalize_key(value)
    if text is None or "@" not in text:
        return None
    return text


def run_command(command: list[str], *, input_text: str | None = None) -> str:
    env = os.environ.copy()
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        details = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"command failed: {' '.join(command)}: {details}")
    return result.stdout


def add_postgres_args(parser, *, default_db: str = "codex_observability", default_user: str = "codex") -> None:
    parser.add_argument(
        "--postgres-db",
        default=os.getenv("POSTGRES_DB", default_db),
        help="PostgreSQL database name",
    )
    parser.add_argument(
        "--postgres-user",
        default=os.getenv("POSTGRES_USER", default_user),
        help="PostgreSQL user",
    )
    parser.add_argument(
        "--postgres-host",
        default=os.getenv("POSTGRES_HOST"),
        help="Direct PostgreSQL host. When omitted, docker exec is used on the host.",
    )
    parser.add_argument(
        "--postgres-port",
        type=int,
        default=int(os.getenv("POSTGRES_PORT", "5432")),
        help="Direct PostgreSQL port",
    )


def resolve_postgres_target(args) -> PostgresTarget:
    host = getattr(args, "postgres_host", None)
    if host:
        return PostgresTarget(
            database=args.postgres_db,
            user=args.postgres_user,
            host=host,
            port=args.postgres_port,
            container_id=None,
        )

    container_id = run_command(["docker", "compose", "ps", "-q", "postgres"]).strip()
    if not container_id:
        raise RuntimeError("postgres container not found. Run `docker compose up -d` first.")
    return PostgresTarget(
        database=args.postgres_db,
        user=args.postgres_user,
        host=None,
        port=5432,
        container_id=container_id,
    )


def psql_query(target: PostgresTarget, sql: str, *, tuples_only: bool = False) -> str:
    if target.is_direct:
        command = [
            "psql",
            "-h",
            target.host or "localhost",
            "-p",
            str(target.port),
            "-U",
            target.user,
            "-d",
            target.database,
            "-v",
            "ON_ERROR_STOP=1",
        ]
    else:
        command = [
            "docker",
            "exec",
            "-i",
            target.container_id or "",
            "psql",
            "-U",
            target.user,
            "-d",
            target.database,
            "-v",
            "ON_ERROR_STOP=1",
        ]

    if tuples_only:
        command.extend(["-At"])
    command.extend(["-f", "-"])
    return run_command(command, input_text=sql)


def load_identity_maps(target: PostgresTarget) -> IdentityMaps:
    registry_sql = """
select
    to_regclass('public.codex_user_mapping') is not null,
    to_regclass('public.codex_user_email_mapping') is not null,
    to_regclass('public.codex_ingest_token_mapping') is not null;
"""
    output = psql_query(target, registry_sql, tuples_only=True).strip()
    has_user_mapping, has_email_mapping, has_token_mapping = (
        output.split("|") if output else ["f", "f", "f"]
    )

    canonical_users: dict[str, dict[str, str | None]] = {}
    email_aliases: dict[str, dict[str, str | None]] = {}
    token_mappings: dict[str, dict[str, str | None]] = {}
    token_hash_mappings: dict[str, dict[str, str | None]] = {}

    if has_user_mapping == "t":
        rows = psql_query(
            target,
            """
select
    lower(user_id) as user_key,
    user_id,
    nullif(team, '') as team,
    nullif(display_name, '') as display_name
from codex_user_mapping
where active = true;
""",
            tuples_only=True,
        ).strip()
        for line in rows.splitlines():
            if not line:
                continue
            user_key, user_id, team, display_name = (line.split("|") + ["", "", "", ""])[:4]
            canonical_users[user_key] = {
                "user_id": normalize_text(user_id),
                "team": normalize_text(team),
                "display_name": normalize_text(display_name),
            }

    if has_email_mapping == "t":
        rows = psql_query(
            target,
            """
select
    lower(user_email) as email_key,
    nullif(resolved_user_id, '') as resolved_user_id,
    nullif(team, '') as team,
    nullif(display_name, '') as display_name
from codex_user_email_mapping
where is_active = true;
""",
            tuples_only=True,
        ).strip()
        for line in rows.splitlines():
            if not line:
                continue
            email_key, resolved_user_id, team, display_name = (line.split("|") + ["", "", "", ""])[:4]
            email_aliases[email_key] = {
                "resolved_user_id": normalize_text(resolved_user_id),
                "team": normalize_text(team),
                "display_name": normalize_text(display_name),
            }

    if has_token_mapping == "t":
        rows = psql_query(
            target,
            """
select
    ingest_token_id,
    nullif(token_hash, '') as token_hash,
    nullif(resolved_user_id, '') as resolved_user_id,
    nullif(resolved_team, '') as resolved_team
from codex_ingest_token_mapping
where is_active = true;
""",
            tuples_only=True,
        ).strip()
        for line in rows.splitlines():
            if not line:
                continue
            ingest_token_id, token_hash, resolved_user_id, resolved_team = (
                line.split("|") + ["", "", "", ""]
            )[:4]
            token_key = normalize_text(ingest_token_id)
            if token_key is None:
                continue
            token_entry = {
                "resolved_user_id": normalize_text(resolved_user_id),
                "resolved_team": normalize_text(resolved_team),
                "ingest_token_id": token_key,
            }
            token_mappings[token_key] = token_entry
            token_hash_key = normalize_key(token_hash)
            if token_hash_key is not None:
                token_hash_mappings[token_hash_key] = token_entry

    return IdentityMaps(
        canonical_users=canonical_users,
        email_aliases=email_aliases,
        token_mappings=token_mappings,
        token_hash_mappings=token_hash_mappings,
    )


def resolve_identity(
    maps: IdentityMaps,
    *,
    raw_user_id: Any,
    raw_team: Any,
    observed_user_email: Any = None,
    ingest_token_id: Any = None,
    direct_resolved_user_id: Any = None,
    direct_resolved_team: Any = None,
) -> ResolvedIdentity:
    raw_user_key = normalize_key(raw_user_id)
    observed_email = normalize_email(observed_user_email) or normalize_email(raw_user_id)
    token_key = normalize_text(ingest_token_id)
    resolved_user_id = normalize_text(direct_resolved_user_id)
    resolved_team = normalize_text(direct_resolved_team)

    token_entry = maps.token_mappings.get(token_key or "")
    email_entry = maps.email_aliases.get(observed_email or "")
    canonical_entry = maps.canonical_users.get(raw_user_key or "")

    if resolved_user_id is None and token_entry is not None:
        resolved_user_id = normalize_text(token_entry.get("resolved_user_id"))
    if resolved_user_id is None and email_entry is not None:
        resolved_user_id = normalize_text(email_entry.get("resolved_user_id"))
    if resolved_user_id is None and canonical_entry is not None:
        resolved_user_id = normalize_text(canonical_entry.get("user_id"))

    if resolved_team is None and token_entry is not None:
        resolved_team = normalize_text(token_entry.get("resolved_team"))
    if resolved_team is None and email_entry is not None:
        resolved_team = normalize_text(email_entry.get("team"))
    if resolved_team is None and canonical_entry is not None:
        resolved_team = normalize_text(canonical_entry.get("team"))
    if resolved_team is None:
        resolved_team = normalize_text(raw_team)

    return ResolvedIdentity(
        observed_user_email=observed_email,
        resolved_user_id=resolved_user_id,
        resolved_team=resolved_team,
        ingest_token_id=token_key,
    )


def mark_job_started(target: PostgresTarget, job_name: str, job_group: str) -> None:
    sql = f"""
insert into codex_job_run_status (
    job_name,
    job_group,
    last_status,
    last_started_at,
    updated_at
)
values (
    {sql_literal(job_name)},
    {sql_literal(job_group)},
    'running',
    now(),
    now()
)
on conflict (job_name) do update set
    job_group = excluded.job_group,
    last_status = 'running',
    last_started_at = now(),
    updated_at = now();
"""
    psql_query(target, sql)


def mark_job_finished(
    target: PostgresTarget,
    job_name: str,
    job_group: str,
    *,
    success: bool,
    error_message: str | None = None,
) -> None:
    status = "success" if success else "failure"
    error_sql = "null" if error_message is None else sql_literal(error_message)
    success_timestamp = "now()" if success else "null"
    failure_timestamp = "null" if success else "now()"
    sql = f"""
insert into codex_job_run_status (
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
)
values (
    {sql_literal(job_name)},
    {sql_literal(job_group)},
    {sql_literal(status)},
    now(),
    now(),
    {success_timestamp},
    {failure_timestamp},
    0,
    {error_sql},
    now()
)
on conflict (job_name) do update set
    job_group = excluded.job_group,
    last_status = excluded.last_status,
    last_finished_at = now(),
    last_success_at = case when excluded.last_status = 'success' then now() else codex_job_run_status.last_success_at end,
    last_failure_at = case when excluded.last_status = 'failure' then now() else codex_job_run_status.last_failure_at end,
    last_duration_seconds = round(extract(epoch from (now() - coalesce(codex_job_run_status.last_started_at, now())))::numeric, 3),
    last_error_message = excluded.last_error_message,
    updated_at = now();
"""
    psql_query(target, sql)
