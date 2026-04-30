#!/usr/bin/env python3
"""Loki의 Codex tool 이벤트 로그를 PostgreSQL에 정규화한다."""

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
    add_postgres_args(parser)
    parser.add_argument(
        "--pipeline-name",
        default="task4-loki-tool-events",
        help="State tracking key",
    )
    parser.add_argument(
        "--job-name",
        default="normalize-tool-events",
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


def fetch_loki_entries(args: argparse.Namespace, start_ns: int, end_ns: int) -> list[tuple[int, dict[str, str], str]]:
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


def load_loki_entries(args: argparse.Namespace, start_ns: int, end_ns: int) -> list[tuple[int, dict[str, str], str]]:
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

    event_name = stream.get("event_name") or attributes.get("event.name")
    if event_name not in {"codex.tool_decision", "codex.tool_result"}:
        return None

    payload_tool = deep_get(event_payload, "tool")
    if not isinstance(payload_tool, dict):
        payload_tool = {}

    payload_metadata = deep_get(event_payload, "metadata")
    if not isinstance(payload_metadata, dict):
        payload_metadata = {}

    raw_user_id = (
        stream.get("user_id")
        or stream.get("user_email")
        or stream.get("user_account_id")
        or resources.get("user_id")
        or payload_metadata.get("user_id")
    )
    raw_team = stream.get("team") or resources.get("team") or payload_metadata.get("team")
    identity = resolve_identity(
        identity_maps,
        raw_user_id=raw_user_id,
        raw_team=raw_team,
        observed_user_email=(
            stream.get("observed_user_email")
            or stream.get("user_email")
            or resources.get("observed_user_email")
            or resources.get("user_email")
            or payload_metadata.get("observed_user_email")
            or payload_metadata.get("user_email")
        ),
        ingest_token_id=(
            stream.get("ingest_token_id")
            or stream.get("otlp_token_id")
            or resources.get("ingest_token_id")
            or resources.get("otlp_token_id")
            or attributes.get("ingest_token_id")
            or payload_metadata.get("ingest_token_id")
        ),
        direct_resolved_user_id=(
            stream.get("resolved_user_id")
            or stream.get("gateway_user_id")
            or resources.get("resolved_user_id")
            or resources.get("gateway_user_id")
            or payload_metadata.get("resolved_user_id")
            or payload_metadata.get("gateway_user_id")
        ),
        direct_resolved_team=(
            stream.get("resolved_team")
            or stream.get("gateway_team")
            or resources.get("resolved_team")
            or resources.get("gateway_team")
            or payload_metadata.get("resolved_team")
            or payload_metadata.get("gateway_team")
        ),
    )

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

    raw_event = (
        sanitized_raw_event(stream, event_payload, line)
        if isinstance(event_payload, (dict, list))
        else sanitized_raw_event(stream, None, line)
    )
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
        "environment": (
            stream.get("deployment_environment")
            or resources.get("deployment.environment")
            or stream.get("env")
        ),
        "service_name": stream.get("service_name") or resources.get("service.name"),
        "service_namespace": stream.get("service_namespace") or resources.get("service.namespace"),
        "codex_version": (
            stream.get("app_version")
            or stream.get("service_version")
            or resources.get("app.version")
        ),
        "user_id": raw_user_id,
        "team": raw_team,
        "observed_user_email": identity.observed_user_email,
        "resolved_user_id": identity.resolved_user_id,
        "resolved_team": identity.resolved_team,
        "ingest_token_id": identity.ingest_token_id,
        "repository": (
            stream.get("repository")
            or resources.get("repository")
            or payload_metadata.get("repository")
        ),
        "project": stream.get("project") or resources.get("project") or payload_metadata.get("project"),
        "session_id": (
            stream.get("session_id")
            or resources.get("session_id")
            or payload_metadata.get("session_id")
        ),
        "conversation_id": (
            stream.get("conversation_id")
            or resources.get("conversation_id")
            or payload_metadata.get("conversation_id")
        ),
        "trace_id": (
            stream.get("trace_id")
            or resources.get("trace_id")
            or payload_metadata.get("trace_id")
        ),
        "span_id": (
            stream.get("span_id")
            or resources.get("span_id")
            or payload_metadata.get("span_id")
        ),
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


def get_last_synced_ns(target, args: argparse.Namespace) -> int:
    output = psql_query(
        target,
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


def upsert_records(target, args: argparse.Namespace, records: list[dict[str, Any]], latest_ns: int) -> None:
    payload = json.dumps(records, ensure_ascii=True)
    sql = f"""
with rows as (
    select *
    from jsonb_to_recordset({sql_literal(payload)}::jsonb) as x(
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
        observed_user_email text,
        resolved_user_id text,
        resolved_team text,
        ingest_token_id text,
        repository text,
        project text,
        session_id text,
        conversation_id text,
        trace_id text,
        span_id text,
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
    observed_user_email,
    resolved_user_id,
    resolved_team,
    ingest_token_id,
    repository,
    project,
    session_id,
    conversation_id,
    trace_id,
    span_id,
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
    observed_user_email,
    resolved_user_id,
    resolved_team,
    ingest_token_id,
    repository,
    project,
    session_id,
    conversation_id,
    trace_id,
    span_id,
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
            f"normalized {len(records)} tool events from {len(entries)} Loki entries "
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
        print(f"tool normalization failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
