#!/usr/bin/env python3
"""Tempo recent traces를 PostgreSQL span 테이블로 정규화한다."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import string
import time
import urllib.parse
import urllib.request
from typing import Any

from runtime_common import (
    add_postgres_args,
    mark_job_finished,
    mark_job_started,
    normalize_text,
    psql_query,
    resolve_postgres_target,
    sql_literal,
)


HEX_DIGITS = set(string.hexdigits)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize recent Tempo traces into PostgreSQL span rows."
    )
    add_postgres_args(parser)
    parser.add_argument(
        "--tempo-url",
        default=os.getenv("TEMPO_URL", "http://localhost:3200"),
        help="Tempo HTTP API base URL",
    )
    parser.add_argument(
        "--pipeline-name",
        default=os.getenv("SCHEDULER_TRACE_PIPELINE_NAME", "scheduler-trace-spans-v1"),
        help="sync state key",
    )
    parser.add_argument(
        "--lookback-seconds",
        type=int,
        default=int(os.getenv("SCHEDULER_NORMALIZE_TRACE_LOOKBACK_SECONDS", "900")),
        help="initial recent trace window when sync state is empty",
    )
    parser.add_argument(
        "--overlap-seconds",
        type=int,
        default=30,
        help="overlap window to tolerate incomplete recent traces",
    )
    parser.add_argument(
        "--search-limit",
        type=int,
        default=int(os.getenv("SCHEDULER_TRACE_SEARCH_LIMIT", "500")),
        help="Tempo recent trace search limit",
    )
    parser.add_argument(
        "--service-prefix",
        default="codex",
        help="keep only traces whose root/service name starts with this prefix",
    )
    parser.add_argument("--job-name", default="normalize-trace-spans", help="job run status key")
    parser.add_argument("--job-group", default="task7", help="job group label")
    parser.add_argument("--dry-run", action="store_true", help="do not write PostgreSQL rows")
    return parser.parse_args()


def http_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def normalize_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return None


def attr_value_to_python(value: dict[str, Any] | None) -> Any:
    if not isinstance(value, dict):
        return None
    for key in (
        "stringValue",
        "intValue",
        "doubleValue",
        "boolValue",
    ):
        if key in value:
            return value.get(key)
    return None


def flatten_attributes(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    if not isinstance(items, list):
        return flattened
    for item in items:
        if not isinstance(item, dict):
            continue
        key = normalize_text(item.get("key"))
        if key is None:
            continue
        flattened[key] = attr_value_to_python(item.get("value"))
    return flattened


def decode_otel_id(value: Any, expected_hex_length: int) -> str | None:
    text = normalize_text(value)
    if text is None:
        return None
    lowered = text.lower()
    if len(lowered) == expected_hex_length and all(ch in HEX_DIGITS for ch in lowered):
        return lowered
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
    hex_value = raw.hex()
    if len(hex_value) != expected_hex_length:
        return None
    return hex_value


def get_last_synced_ns(target, args: argparse.Namespace) -> int:
    output = psql_query(
        target,
        f"""
select coalesce(last_source_timestamp_ns, 0)
from codex_trace_sync_state
where pipeline_name = {sql_literal(args.pipeline_name)};
""",
        tuples_only=True,
    ).strip()
    if not output:
        return 0
    return int(output)


def load_recent_trace_summaries(args: argparse.Namespace) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"limit": str(args.search_limit)})
    payload = http_get_json(f"{args.tempo_url.rstrip('/')}/api/search?{params}")
    traces = payload.get("traces", [])
    return [trace for trace in traces if isinstance(trace, dict)]


def fetch_trace_payload(args: argparse.Namespace, trace_id: str) -> dict[str, Any] | None:
    try:
        return http_get_json(f"{args.tempo_url.rstrip('/')}/api/traces/{trace_id}")
    except urllib.error.HTTPError as error:
        if error.code in {404, 500, 503}:
            return None
        raise


def parse_trace_records(
    summary: dict[str, Any],
    trace_payload: dict[str, Any],
    *,
    service_prefix: str,
) -> list[dict[str, Any]]:
    root_trace_name = normalize_text(summary.get("rootTraceName"))
    root_service_name = normalize_text(summary.get("rootServiceName"))
    summary_trace_id = decode_otel_id(summary.get("traceID") or summary.get("traceId"), 32)
    records: list[dict[str, Any]] = []

    for batch in trace_payload.get("batches", []):
        if not isinstance(batch, dict):
            continue
        resource_attrs = flatten_attributes(batch.get("resource", {}).get("attributes"))
        service_name = normalize_text(resource_attrs.get("service.name"))
        if service_prefix and service_name and not service_name.lower().startswith(service_prefix.lower()):
            continue
        for scope_span in batch.get("scopeSpans", []):
            if not isinstance(scope_span, dict):
                continue
            scope = scope_span.get("scope", {}) if isinstance(scope_span.get("scope"), dict) else {}
            scope_name = normalize_text(scope.get("name"))
            scope_version = normalize_text(scope.get("version"))
            for span in scope_span.get("spans", []):
                if not isinstance(span, dict):
                    continue
                span_attrs = flatten_attributes(span.get("attributes"))
                trace_id = decode_otel_id(span.get("traceId"), 32) or summary_trace_id
                span_id = decode_otel_id(span.get("spanId"), 16)
                if trace_id is None or span_id is None:
                    continue
                parent_span_id = decode_otel_id(span.get("parentSpanId"), 16)
                start_ns = normalize_int(span.get("startTimeUnixNano"))
                end_ns = normalize_int(span.get("endTimeUnixNano"))
                if start_ns is None:
                    continue
                if end_ns is None or end_ns < start_ns:
                    end_ns = start_ns
                duration_ms = max(0, round((end_ns - start_ns) / 1_000_000.0))
                source_fingerprint = hashlib.sha256(
                    f"{trace_id}\n{span_id}\n{start_ns}\n{end_ns}".encode("utf-8")
                ).hexdigest()
                record = {
                    "source_fingerprint": source_fingerprint,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "parent_span_id": parent_span_id,
                    "root_trace_name": root_trace_name,
                    "root_service_name": root_service_name,
                    "event_time_epoch_ms": start_ns // 1_000_000,
                    "end_time_epoch_ms": end_ns // 1_000_000,
                    "duration_ms": duration_ms,
                    "span_name": normalize_text(span.get("name")) or "(unknown)",
                    "span_kind": normalize_text(span.get("kind")),
                    "service_name": service_name,
                    "service_namespace": normalize_text(resource_attrs.get("service.namespace")),
                    "service_version": normalize_text(resource_attrs.get("service.version")),
                    "scope_name": scope_name,
                    "scope_version": scope_version,
                    "environment": (
                        normalize_text(resource_attrs.get("deployment.environment"))
                        or normalize_text(resource_attrs.get("env"))
                    ),
                    "user_id": normalize_text(resource_attrs.get("user_id") or resource_attrs.get("user_email")),
                    "team": normalize_text(resource_attrs.get("team")),
                    "resolved_user_id": normalize_text(
                        span_attrs.get("resolved_user_id") or resource_attrs.get("resolved_user_id")
                    ),
                    "resolved_team": normalize_text(
                        span_attrs.get("resolved_team") or resource_attrs.get("resolved_team")
                    ),
                    "ingest_token_id": normalize_text(
                        span_attrs.get("ingest_token_id") or resource_attrs.get("ingest_token_id")
                    ),
                    "session_id": normalize_text(
                        span_attrs.get("session_id") or resource_attrs.get("session_id")
                    ),
                    "conversation_id": normalize_text(
                        span_attrs.get("conversation_id") or resource_attrs.get("conversation_id")
                    ),
                    "turn_id": normalize_text(span_attrs.get("turn.id") or span_attrs.get("turn_id")),
                    "model": normalize_text(span_attrs.get("model") or resource_attrs.get("model")),
                    "rpc_system": normalize_text(span_attrs.get("rpc.system")),
                    "rpc_method": normalize_text(span_attrs.get("rpc.method")),
                    "transport": normalize_text(
                        span_attrs.get("transport") or span_attrs.get("rpc.transport")
                    ),
                    "provider": normalize_text(span_attrs.get("provider")),
                    "api_path": normalize_text(span_attrs.get("api.path")),
                    "tool_name": normalize_text(span_attrs.get("tool") or span_attrs.get("tool_name")),
                    "tool_call_id": normalize_text(
                        span_attrs.get("tool_call_id") or span_attrs.get("call_id")
                    ),
                    "tool_success": normalize_bool(span_attrs.get("tool_success")),
                    "busy_ns": normalize_int(span_attrs.get("busy_ns")),
                    "idle_ns": normalize_int(span_attrs.get("idle_ns")),
                    "resource_attributes": resource_attrs,
                    "span_attributes": span_attrs,
                }
                records.append(record)
    return records


def upsert_records(target, args: argparse.Namespace, records: list[dict[str, Any]], latest_ns: int) -> None:
    payload = json.dumps(records, ensure_ascii=True)
    sql = f"""
with rows as (
    select *
    from jsonb_to_recordset({sql_literal(payload)}::jsonb) as x(
        source_fingerprint text,
        trace_id text,
        span_id text,
        parent_span_id text,
        root_trace_name text,
        root_service_name text,
        event_time_epoch_ms bigint,
        end_time_epoch_ms bigint,
        duration_ms bigint,
        span_name text,
        span_kind text,
        service_name text,
        service_namespace text,
        service_version text,
        scope_name text,
        scope_version text,
        environment text,
        user_id text,
        team text,
        resolved_user_id text,
        resolved_team text,
        ingest_token_id text,
        session_id text,
        conversation_id text,
        turn_id text,
        model text,
        rpc_system text,
        rpc_method text,
        transport text,
        provider text,
        api_path text,
        tool_name text,
        tool_call_id text,
        tool_success boolean,
        busy_ns bigint,
        idle_ns bigint,
        resource_attributes jsonb,
        span_attributes jsonb
    )
)
insert into codex_trace_spans (
    source_fingerprint,
    trace_id,
    span_id,
    parent_span_id,
    root_trace_name,
    root_service_name,
    event_time,
    end_time,
    duration_ms,
    span_name,
    span_kind,
    service_name,
    service_namespace,
    service_version,
    scope_name,
    scope_version,
    environment,
    user_id,
    team,
    resolved_user_id,
    resolved_team,
    ingest_token_id,
    session_id,
    conversation_id,
    turn_id,
    model,
    rpc_system,
    rpc_method,
    transport,
    provider,
    api_path,
    tool_name,
    tool_call_id,
    tool_success,
    busy_ns,
    idle_ns,
    resource_attributes,
    span_attributes
)
select
    source_fingerprint,
    trace_id,
    span_id,
    parent_span_id,
    root_trace_name,
    root_service_name,
    to_timestamp(event_time_epoch_ms / 1000.0),
    to_timestamp(end_time_epoch_ms / 1000.0),
    duration_ms,
    span_name,
    span_kind,
    service_name,
    service_namespace,
    service_version,
    scope_name,
    scope_version,
    environment,
    user_id,
    team,
    resolved_user_id,
    resolved_team,
    ingest_token_id,
    session_id,
    conversation_id,
    turn_id,
    model,
    rpc_system,
    rpc_method,
    transport,
    provider,
    api_path,
    tool_name,
    tool_call_id,
    tool_success,
    busy_ns,
    idle_ns,
    resource_attributes,
    span_attributes
from rows
on conflict (source_fingerprint) do nothing;

insert into codex_trace_sync_state (pipeline_name, last_source_timestamp_ns, updated_at)
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
        last_synced_ns = get_last_synced_ns(target, args)
        now_ns = time.time_ns()
        threshold_ns = max(
            0,
            (last_synced_ns - args.overlap_seconds * 1_000_000_000)
            if last_synced_ns > 0
            else (now_ns - args.lookback_seconds * 1_000_000_000),
        )

        summaries = load_recent_trace_summaries(args)
        candidate_summaries = []
        for summary in summaries:
            start_ns = normalize_int(summary.get("startTimeUnixNano")) or 0
            if start_ns <= 0:
                continue
            if start_ns >= threshold_ns:
                candidate_summaries.append(summary)

        records: list[dict[str, Any]] = []
        latest_ns = last_synced_ns
        for summary in sorted(
            candidate_summaries,
            key=lambda item: normalize_int(item.get("startTimeUnixNano")) or 0,
        ):
            summary_start_ns = normalize_int(summary.get("startTimeUnixNano")) or 0
            trace_id = decode_otel_id(summary.get("traceID") or summary.get("traceId"), 32)
            if trace_id is None:
                continue
            trace_payload = fetch_trace_payload(args, trace_id)
            if trace_payload is None:
                continue
            trace_records = parse_trace_records(
                summary,
                trace_payload,
                service_prefix=args.service_prefix,
            )
            if trace_records:
                records.extend(trace_records)
                latest_ns = max(latest_ns, summary_start_ns)

        if args.dry_run:
            print(
                json.dumps(
                    {
                        "summaries": len(summaries),
                        "candidate_summaries": len(candidate_summaries),
                        "normalized_records": len(records),
                        "last_source_timestamp_ns": latest_ns,
                    },
                    ensure_ascii=False,
                )
            )
            for record in records[:10]:
                print(json.dumps(record, ensure_ascii=False))
            return 0

        if records:
            upsert_records(target, args, records, latest_ns)
        elif latest_ns > last_synced_ns:
            upsert_records(target, args, [], latest_ns)

        print(
            f"normalized {len(records)} trace spans from {len(candidate_summaries)} recent traces "
            f"(last_source_timestamp_ns={latest_ns})"
        )

        if tracking_enabled:
            mark_job_finished(target, args.job_name, args.job_group, success=True)
        return 0
    except Exception as error:
        if tracking_enabled:
            mark_job_finished(
                target,
                args.job_name,
                args.job_group,
                success=False,
                error_message=str(error),
            )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
