#!/usr/bin/env python3
"""Loki의 Codex local helper 이벤트를 PostgreSQL에 정규화한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

from runtime_common import (
    add_postgres_args,
    load_identity_maps,
    mark_job_finished,
    mark_job_started,
    psql_query,
    resolve_identity,
    resolve_postgres_target,
    sql_literal,
)


EVENT_NAMES = {"codex.local_helper_context"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize Codex local helper context events from Loki into PostgreSQL."
    )
    parser.add_argument("--loki-url", default="http://localhost:3100", help="Loki base URL")
    parser.add_argument(
        "--loki-query",
        default='{service_name="codex-local-helper"}',
        help="Loki LogQL query",
    )
    add_postgres_args(parser)
    parser.add_argument(
        "--pipeline-name",
        default="task8-loki-local-helper-events",
        help="State tracking key",
    )
    parser.add_argument(
        "--job-name",
        default="normalize-local-helper-events",
        help="Job status key",
    )
    parser.add_argument(
        "--job-group",
        default="normalization",
        help="Job status group",
    )
    parser.add_argument(
        "--lookback-seconds",
        type=int,
        default=21600,
        help="Initial lookback when no sync state exists",
    )
    parser.add_argument(
        "--overlap-seconds",
        type=int,
        default=5,
        help="Re-read overlap window to tolerate out-of-order delivery",
    )
    parser.add_argument(
        "--chunk-seconds",
        type=int,
        default=900,
        help="Split large Loki queries into smaller time windows",
    )
    parser.add_argument("--limit", type=int, default=5000, help="Loki query limit")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to PostgreSQL")
    return parser.parse_args()


def http_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_loki_entries(
    args: argparse.Namespace, start_ns: int, end_ns: int
) -> list[tuple[int, dict[str, str], str]]:
    params = urllib.parse.urlencode(
        {
            "query": args.loki_query,
            "start": str(start_ns),
            "end": str(end_ns),
            "limit": str(args.limit),
            "direction": "backward",
        }
    )
    payload = http_get_json(f"{args.loki_url.rstrip('/')}/loki/api/v1/query_range?{params}")
    results = payload.get("data", {}).get("result", [])
    entries: list[tuple[int, dict[str, str], str]] = []
    for stream_entry in results:
        stream = {str(key): str(value) for key, value in stream_entry.get("stream", {}).items()}
        for timestamp_ns, line in stream_entry.get("values", []):
            entries.append((int(timestamp_ns), stream, line))
    entries.sort(key=lambda item: item[0])
    return entries


def load_loki_entries(
    args: argparse.Namespace, start_ns: int, end_ns: int
) -> list[tuple[int, dict[str, str], str]]:
    chunk_ns = max(args.chunk_seconds, 1) * 1_000_000_000
    entries: list[tuple[int, dict[str, str], str]] = []
    cursor = start_ns
    while cursor < end_ns:
        window_end = min(cursor + chunk_ns, end_ns)
        entries.extend(fetch_loki_entries(args, cursor, window_end))
        cursor = window_end
    entries.sort(key=lambda item: item[0])
    return entries


def try_json(value: Any) -> Any | None:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or value[0] not in "[{":
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        return int(value.strip())
    return None


def normalize_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def parse_entry(
    timestamp_ns: int,
    stream: dict[str, str],
    line: str,
    identity_maps,
) -> dict[str, Any] | None:
    outer = try_json(line)
    event_payload: Any | None = None
    attributes: dict[str, Any] = {}
    resources: dict[str, Any] = {}

    if isinstance(outer, dict) and any(key in outer for key in ("body", "attributes", "resources")):
        attributes = outer.get("attributes", {}) if isinstance(outer.get("attributes"), dict) else {}
        resources = outer.get("resources", {}) if isinstance(outer.get("resources"), dict) else {}
        event_payload = try_json(outer.get("body")) or outer.get("body")
    elif isinstance(outer, dict):
        event_payload = outer

    if not isinstance(event_payload, dict):
        event_payload = {}

    event_name = stream.get("event_name") or attributes.get("event.name") or event_payload.get(
        "helper_event_name"
    )
    if event_name not in EVENT_NAMES:
        return None

    raw_user_id = (
        stream.get("user_id")
        or stream.get("user_email")
        or resources.get("user_id")
        or event_payload.get("user_id")
    )
    raw_team = stream.get("team") or resources.get("team") or event_payload.get("team")
    identity = resolve_identity(
        identity_maps,
        raw_user_id=raw_user_id,
        raw_team=raw_team,
        observed_user_email=(
            stream.get("observed_user_email")
            or stream.get("user_email")
            or resources.get("observed_user_email")
            or resources.get("user_email")
            or event_payload.get("observed_user_email")
            or event_payload.get("user_email")
        ),
        ingest_token_id=(
            stream.get("ingest_token_id")
            or resources.get("ingest_token_id")
            or attributes.get("ingest_token_id")
            or event_payload.get("ingest_token_id")
        ),
        direct_resolved_user_id=(
            stream.get("resolved_user_id")
            or resources.get("resolved_user_id")
            or event_payload.get("resolved_user_id")
        ),
        direct_resolved_team=(
            stream.get("resolved_team")
            or resources.get("resolved_team")
            or event_payload.get("resolved_team")
        ),
    )

    notification_type = (
        stream.get("notification_type")
        or stream.get("notification_type_extracted")
        or event_payload.get("notification_type")
    )
    thread_id = stream.get("thread_id") or event_payload.get("thread_id")
    turn_id = stream.get("turn_id") or event_payload.get("turn_id")

    fingerprint_source = json.dumps(
        {
            "ts": timestamp_ns,
            "event": event_name,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "body": event_payload,
        },
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")

    return {
        "source_fingerprint": hashlib.sha256(fingerprint_source).hexdigest(),
        "source_timestamp_ns": timestamp_ns,
        "event_time_epoch_ms": timestamp_ns / 1_000_000,
        "event_name": event_name,
        "notification_type": notification_type,
        "environment": (
            stream.get("deployment_environment")
            or stream.get("deployment_environment_extracted")
            or resources.get("deployment.environment")
            or event_payload.get("environment")
        ),
        "service_name": stream.get("service_name") or resources.get("service.name"),
        "service_namespace": stream.get("service_namespace") or resources.get("service.namespace"),
        "helper_version": stream.get("helper_version") or event_payload.get("helper_version"),
        "user_id": raw_user_id,
        "team": raw_team,
        "observed_user_email": identity.observed_user_email,
        "resolved_user_id": identity.resolved_user_id,
        "resolved_team": identity.resolved_team,
        "ingest_token_id": identity.ingest_token_id,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "cwd": stream.get("cwd") or event_payload.get("cwd"),
        "is_git": normalize_bool(stream.get("is_git")) or bool(event_payload.get("is_git")),
        "repo_root": stream.get("repo_root") or event_payload.get("repo_root"),
        "repo_name": stream.get("repo_name") or event_payload.get("repo_name"),
        "git_branch": stream.get("git_branch") or event_payload.get("git_branch"),
        "git_remote_slug": stream.get("git_remote_slug") or event_payload.get("git_remote_slug"),
        "host_name": stream.get("host_name") or event_payload.get("host_name"),
        "input_message_count": normalize_int(
            stream.get("input_message_count") or event_payload.get("input_message_count")
        ),
        "input_message_char_count": normalize_int(
            stream.get("input_message_char_count") or event_payload.get("input_message_char_count")
        ),
        "last_assistant_message_char_count": normalize_int(
            stream.get("last_assistant_message_char_count")
            or event_payload.get("last_assistant_message_char_count")
        ),
        "raw_event": {
            "stream": stream,
            "body": event_payload,
            "line_present": bool(line),
        },
    }


def get_last_synced_ns(target, args: argparse.Namespace) -> int:
    sql = f"""
select coalesce(last_source_timestamp_ns, 0)
from codex_local_helper_sync_state
where pipeline_name = {sql_literal(args.pipeline_name)};
"""
    result = psql_query(target, sql, tuples_only=True).strip()
    return int(result or "0")


def upsert_records(target, args: argparse.Namespace, records: list[dict[str, Any]], latest_ns: int) -> None:
    rows_sql = []
    for record in records:
        raw_event_json = json.dumps(record["raw_event"], ensure_ascii=False).replace("'", "''")
        rows_sql.append(
            "("
            f"{sql_literal(record['source_fingerprint'])},"
            f"{record['source_timestamp_ns']},"
            f"{record['event_time_epoch_ms']},"
            f"{sql_literal(record['event_name'])},"
            f"{sql_literal(record['notification_type'] or '')},"
            f"{sql_literal(record['environment'] or '')},"
            f"{sql_literal(record['service_name'] or '')},"
            f"{sql_literal(record['service_namespace'] or '')},"
            f"{sql_literal(record['helper_version'] or '')},"
            f"{sql_literal(record['user_id'] or '')},"
            f"{sql_literal(record['team'] or '')},"
            f"{sql_literal(record['observed_user_email'] or '')},"
            f"{sql_literal(record['resolved_user_id'] or '')},"
            f"{sql_literal(record['resolved_team'] or '')},"
            f"{sql_literal(record['ingest_token_id'] or '')},"
            f"{sql_literal(record['thread_id'] or '')},"
            f"{sql_literal(record['turn_id'] or '')},"
            f"{sql_literal(record['cwd'] or '')},"
            f"{'true' if record['is_git'] else 'false'},"
            f"{sql_literal(record['repo_root'] or '')},"
            f"{sql_literal(record['repo_name'] or '')},"
            f"{sql_literal(record['git_branch'] or '')},"
            f"{sql_literal(record['git_remote_slug'] or '')},"
            f"{sql_literal(record['host_name'] or '')},"
            f"{record['input_message_count'] if record['input_message_count'] is not None else 'null'},"
            f"{record['input_message_char_count'] if record['input_message_char_count'] is not None else 'null'},"
            f"{record['last_assistant_message_char_count'] if record['last_assistant_message_char_count'] is not None else 'null'},"
            f"'{raw_event_json}'::jsonb"
            ")"
        )

    values_clause = ",\n".join(rows_sql) if rows_sql else "(null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,false,null,null,null,null,null,null,null,null,'{}'::jsonb)"
    where_clause = "" if rows_sql else "where source_fingerprint is not null"

    sql = f"""
with rows (
    source_fingerprint,
    source_timestamp_ns,
    event_time_epoch_ms,
    event_name,
    notification_type,
    environment,
    service_name,
    service_namespace,
    helper_version,
    user_id,
    team,
    observed_user_email,
    resolved_user_id,
    resolved_team,
    ingest_token_id,
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
    raw_event
) as (
    values
    {values_clause}
)
insert into codex_local_helper_events (
    source_fingerprint,
    source_timestamp_ns,
    event_time,
    event_name,
    notification_type,
    environment,
    service_name,
    service_namespace,
    helper_version,
    user_id,
    team,
    observed_user_email,
    resolved_user_id,
    resolved_team,
    ingest_token_id,
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
    raw_event
)
select
    source_fingerprint,
    source_timestamp_ns,
    to_timestamp(event_time_epoch_ms / 1000.0),
    nullif(event_name, ''),
    nullif(notification_type, ''),
    nullif(environment, ''),
    nullif(service_name, ''),
    nullif(service_namespace, ''),
    nullif(helper_version, ''),
    nullif(user_id, ''),
    nullif(team, ''),
    nullif(observed_user_email, ''),
    nullif(resolved_user_id, ''),
    nullif(resolved_team, ''),
    nullif(ingest_token_id, ''),
    nullif(thread_id, ''),
    nullif(turn_id, ''),
    nullif(cwd, ''),
    is_git,
    nullif(repo_root, ''),
    nullif(repo_name, ''),
    nullif(git_branch, ''),
    nullif(git_remote_slug, ''),
    nullif(host_name, ''),
    input_message_count,
    input_message_char_count,
    last_assistant_message_char_count,
    raw_event
from rows
{where_clause}
on conflict (source_fingerprint) do nothing;

insert into codex_local_helper_sync_state (pipeline_name, last_source_timestamp_ns, updated_at)
values ({sql_literal(args.pipeline_name)}, {latest_ns}, now())
on conflict (pipeline_name) do update
set last_source_timestamp_ns = excluded.last_source_timestamp_ns,
    updated_at = excluded.updated_at;
"""
    psql_query(target, sql)


def main() -> int:
    args = parse_args()
    target = resolve_postgres_target(args)
    tracking_enabled = not args.dry_run

    if tracking_enabled:
        mark_job_started(target, args.job_name, args.job_group)

    try:
        identity_maps = load_identity_maps(target)
        last_synced_ns = get_last_synced_ns(target, args)
        now_ns = time.time_ns()
        if last_synced_ns > 0:
            start_ns = max(0, last_synced_ns - args.overlap_seconds * 1_000_000_000)
        else:
            start_ns = now_ns - args.lookback_seconds * 1_000_000_000

        entries = load_loki_entries(args, start_ns, now_ns)
        records = []
        for timestamp_ns, stream, line in entries:
            record = parse_entry(timestamp_ns, stream, line, identity_maps)
            if record:
                records.append(record)

        latest_ns = max((timestamp_ns for timestamp_ns, _, _ in entries), default=last_synced_ns)

        if args.dry_run:
            print(
                json.dumps(
                    {"entries": len(entries), "normalized_records": len(records)},
                    ensure_ascii=False,
                )
            )
            for record in records[:5]:
                print(json.dumps(record, ensure_ascii=False))
            return 0

        if records:
            upsert_records(target, args, records, latest_ns)
        elif latest_ns > last_synced_ns:
            upsert_records(target, args, [], latest_ns)

        print(
            f"normalized {len(records)} local helper events from {len(entries)} Loki entries "
            f"(last_source_timestamp_ns={latest_ns})"
        )
        if tracking_enabled:
            mark_job_finished(target, args.job_name, args.job_group, success=True)
        return 0
    except Exception as error:  # noqa: BLE001
        if tracking_enabled:
            try:
                mark_job_finished(
                    target,
                    args.job_name,
                    args.job_group,
                    success=False,
                    error_message=str(error),
                )
            except Exception:  # noqa: BLE001
                pass
        print(f"local helper normalization failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
