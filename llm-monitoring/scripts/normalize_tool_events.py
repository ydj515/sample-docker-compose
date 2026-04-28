#!/usr/bin/env python3
"""Loki의 Codex tool 이벤트 로그를 PostgreSQL에 정규화한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize Codex tool events from Loki into PostgreSQL."
    )
    parser.add_argument("--loki-url", default="http://localhost:3100", help="Loki base URL")
    parser.add_argument(
        "--loki-query",
        default='{service_name=~"codex-cli|codex_cli_rs"}',
        help="Loki LogQL query",
    )
    parser.add_argument(
        "--postgres-db",
        default="codex_observability",
        help="PostgreSQL database name",
    )
    parser.add_argument("--postgres-user", default="codex", help="PostgreSQL user")
    parser.add_argument(
        "--pipeline-name",
        default="task4-loki-tool-events",
        help="State tracking key",
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
    parser.add_argument("--limit", type=int, default=5000, help="Loki query limit")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to PostgreSQL")
    return parser.parse_args()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_command(command: list[str], *, input_text: str | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        details = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"command failed: {' '.join(command)}: {details}")
    return result.stdout


def resolve_postgres_container() -> str:
    container_id = run_command(["docker", "compose", "ps", "-q", "postgres"]).strip()
    if not container_id:
        raise RuntimeError("postgres container not found. Run `docker compose up -d` first.")
    return container_id


def psql_query(container: str, user: str, database: str, sql: str, *, tuples_only: bool = False) -> str:
    command = [
        "docker",
        "exec",
        "-i",
        container,
        "psql",
        "-U",
        user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
    ]
    if tuples_only:
        command.extend(["-At"])
    command.extend(["-f", "-"])
    return run_command(command, input_text=sql)


def http_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def load_loki_entries(args: argparse.Namespace, start_ns: int, end_ns: int) -> list[tuple[int, dict[str, str], str]]:
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


def deep_get(node: Any, *path: str) -> Any | None:
    current = node
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


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


def sanitized_raw_event(stream: dict[str, str], event_payload: Any, line: str) -> dict[str, Any]:
    sanitized_stream = dict(stream)
    if "arguments" in sanitized_stream:
        sanitized_stream["arguments"] = "[REDACTED]"
    if "output" in sanitized_stream:
        sanitized_stream["output"] = "[REDACTED]"
    return {
        "stream": sanitized_stream,
        "body": event_payload,
        "line_present": bool(line),
    }


def parse_entry(timestamp_ns: int, stream: dict[str, str], line: str) -> dict[str, Any] | None:
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

    event_name = stream.get("event_name") or attributes.get("event.name")
    if event_name not in {"codex.tool_decision", "codex.tool_result"}:
        return None

    payload_tool = deep_get(event_payload, "tool")
    if not isinstance(payload_tool, dict):
        payload_tool = {}

    payload_metadata = deep_get(event_payload, "metadata")
    if not isinstance(payload_metadata, dict):
        payload_metadata = {}

    error_obj = payload_tool.get("error")
    if not isinstance(error_obj, dict):
        error_obj = {}

    tool_name = (
        stream.get("tool")
        or stream.get("tool_name")
        or attributes.get("tool")
        or payload_tool.get("name")
        or payload_tool.get("tool")
    )
    if not tool_name:
        return None

    tool_success = normalize_bool(
        stream.get("tool_success")
        or stream.get("success")
        or attributes.get("tool_success")
        or payload_tool.get("success")
    )
    tool_duration_ms = normalize_int(
        stream.get("tool_duration_ms")
        or stream.get("duration_ms")
        or attributes.get("tool_duration_ms")
        or payload_tool.get("duration_ms")
    )
    tool_output_size = normalize_int(
        stream.get("tool_output_size")
        or attributes.get("tool_output_size")
        or payload_tool.get("output_size")
    )
    if tool_output_size is None and stream.get("output") is not None:
        tool_output_size = len(stream.get("output", ""))
    tool_error_code = (
        stream.get("tool_error_code")
        or attributes.get("tool_error_code")
        or error_obj.get("code")
    )
    tool_error_message = (
        stream.get("tool_error_message")
        or attributes.get("tool_error_message")
        or error_obj.get("message")
    )
    if event_name == "codex.tool_result" and tool_success is None and (tool_error_code or tool_error_message):
        tool_success = False

    if isinstance(event_payload, (dict, list)):
        raw_event = sanitized_raw_event(stream, event_payload, line)
    else:
        raw_event = sanitized_raw_event(stream, None, line)
    source_fingerprint = hashlib.sha256(
        (
            f"{timestamp_ns}\n"
            f"{json.dumps(stream, sort_keys=True, ensure_ascii=True)}\n"
            f"{line}"
        ).encode("utf-8")
    ).hexdigest()

    return {
        "source_fingerprint": source_fingerprint,
        "source_timestamp_ns": timestamp_ns,
        "event_time_epoch_ms": timestamp_ns // 1_000_000,
        "event_name": event_name,
        "environment": stream.get("deployment_environment") or resources.get("deployment.environment"),
        "service_name": stream.get("service_name") or resources.get("service.name"),
        "service_namespace": stream.get("service_namespace") or resources.get("service.namespace"),
        "codex_version": stream.get("app_version") or resources.get("app.version"),
        "user_id": (
            stream.get("user_id")
            or stream.get("user_email")
            or stream.get("user_account_id")
            or resources.get("user_id")
            or payload_metadata.get("user_id")
        ),
        "team": stream.get("team") or resources.get("team") or payload_metadata.get("team"),
        "repository": stream.get("repository") or resources.get("repository") or payload_metadata.get("repository"),
        "project": stream.get("project") or resources.get("project") or payload_metadata.get("project"),
        "session_id": stream.get("session_id") or resources.get("session_id") or payload_metadata.get("session_id"),
        "conversation_id": stream.get("conversation_id") or resources.get("conversation_id") or payload_metadata.get("conversation_id"),
        "model": stream.get("model") or payload_metadata.get("model"),
        "tool_name": str(tool_name),
        "tool_call_id": (
            stream.get("tool_call_id")
            or stream.get("call_id")
            or attributes.get("tool_call_id")
            or payload_tool.get("call_id")
            or payload_tool.get("id")
        ),
        "tool_decision": (
            stream.get("tool_decision")
            or stream.get("decision")
            or attributes.get("tool_decision")
            or payload_tool.get("decision")
        ),
        "tool_success": tool_success,
        "tool_duration_ms": tool_duration_ms,
        "tool_error_code": tool_error_code,
        "tool_error_message": tool_error_message,
        "tool_output_size": tool_output_size,
        "raw_event": raw_event,
    }


def get_last_synced_ns(container: str, args: argparse.Namespace) -> int:
    output = psql_query(
        container,
        args.postgres_user,
        args.postgres_db,
        f"""
select coalesce(last_source_timestamp_ns, 0)
from codex_tool_sync_state
where pipeline_name = {sql_literal(args.pipeline_name)};
""",
        tuples_only=True,
    ).strip()
    if not output:
        return 0
    return int(output)


def upsert_records(container: str, args: argparse.Namespace, records: list[dict[str, Any]], latest_ns: int) -> None:
    payload = json.dumps(records, ensure_ascii=True)
    sql = f"""
with rows as (
    select *
    from jsonb_to_recordset($json${payload}$json$::jsonb) as x(
        source_fingerprint text,
        source_timestamp_ns bigint,
        event_time_epoch_ms bigint,
        event_name text,
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
        tool_name text,
        tool_call_id text,
        tool_decision text,
        tool_success boolean,
        tool_duration_ms bigint,
        tool_error_code text,
        tool_error_message text,
        tool_output_size bigint,
        raw_event jsonb
    )
)
insert into codex_tool_events (
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
    raw_event
)
select
    source_fingerprint,
    source_timestamp_ns,
    to_timestamp(event_time_epoch_ms / 1000.0),
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
    raw_event
from rows
on conflict (source_fingerprint) do nothing;

insert into codex_tool_sync_state (pipeline_name, last_source_timestamp_ns, updated_at)
values ({sql_literal(args.pipeline_name)}, {latest_ns}, now())
on conflict (pipeline_name) do update
set last_source_timestamp_ns = excluded.last_source_timestamp_ns,
    updated_at = excluded.updated_at;
"""
    psql_query(container, args.postgres_user, args.postgres_db, sql)


def main() -> int:
    args = parse_args()
    container = resolve_postgres_container()
    last_synced_ns = get_last_synced_ns(container, args)
    now_ns = time.time_ns()
    if last_synced_ns > 0:
        start_ns = max(0, last_synced_ns - args.overlap_seconds * 1_000_000_000)
    else:
        start_ns = now_ns - args.lookback_seconds * 1_000_000_000

    entries = load_loki_entries(args, start_ns, now_ns)
    records = []
    for timestamp_ns, stream, line in entries:
        record = parse_entry(timestamp_ns, stream, line)
        if record:
            records.append(record)

    latest_ns = max((timestamp_ns for timestamp_ns, _, _ in entries), default=last_synced_ns)

    if args.dry_run:
        print(json.dumps({"entries": len(entries), "normalized_records": len(records)}, ensure_ascii=False))
        for record in records[:5]:
            print(json.dumps(record, ensure_ascii=False))
        return 0

    if records:
        upsert_records(container, args, records, latest_ns)
    elif latest_ns > last_synced_ns:
        upsert_records(container, args, [], latest_ns)

    print(
        f"normalized {len(records)} tool events from {len(entries)} Loki entries "
        f"(last_source_timestamp_ns={latest_ns})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
