#!/usr/bin/env python3
"""TASK-2 로컬 검증용 샘플 OTLP 이벤트 전송 스크립트."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request


def now_ns() -> int:
    return time.time_ns()


def attr(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


def send_json(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8", errors="replace")
        if response.status >= 300:
            raise RuntimeError(f"{url} returned {response.status}: {body}")


def metadata_payload(args: argparse.Namespace) -> dict[str, object]:
    return {
        "team": args.team,
        "user_id": args.user_id,
        "repository": args.repository,
        "project": args.project,
        "session_id": args.session_id,
        "conversation_id": args.conversation_id,
    }


def build_response_completed_body(args: argparse.Namespace) -> str:
    usage: dict[str, object] = {
        "input_tokens": args.input_tokens,
        "output_tokens": args.output_tokens,
        "total_tokens": args.total_tokens,
    }
    if not args.omit_cached_input_tokens:
        usage["input_tokens_details"] = {
            "cached_tokens": args.cached_input_tokens,
        }
    if not args.omit_reasoning_tokens:
        usage["output_tokens_details"] = {
            "reasoning_tokens": args.reasoning_tokens,
        }

    payload = {
        "event": "response.completed",
        "response": {
            "id": args.response_id,
            "model": args.model,
            "usage": usage,
        },
        "metadata": metadata_payload(args),
    }
    return json.dumps(payload, separators=(",", ":"))


def build_tool_decision_body(args: argparse.Namespace) -> str:
    payload = {
        "event": "tool_decision",
        "tool": {
            "name": args.tool,
            "call_id": args.tool_call_id,
            "decision": args.tool_decision,
        },
        "metadata": metadata_payload(args),
    }
    return json.dumps(payload, separators=(",", ":"))


def build_tool_result_body(args: argparse.Namespace) -> str:
    payload: dict[str, object] = {
        "event": "tool_result",
        "tool": {
            "name": args.tool,
            "call_id": args.tool_call_id,
            "success": not args.tool_failure,
            "duration_ms": args.tool_duration_ms,
            "output_size": args.tool_output_size,
        },
        "metadata": metadata_payload(args),
    }
    if args.tool_failure:
        payload["tool"]["error"] = {
            "code": args.tool_error_code,
            "message": args.tool_error_message,
        }
    return json.dumps(payload, separators=(",", ":"))


def build_logs(base_ns: int, args: argparse.Namespace) -> dict:
    attributes = [
        attr("service.name", "codex-cli"),
        attr("deployment.environment", args.environment),
        attr("team", args.team),
        attr("user_id", args.user_id),
        attr("repository", args.repository),
        attr("project", args.project),
        attr("session_id", args.session_id),
        attr("conversation_id", args.conversation_id),
        attr("model", args.model),
    ]
    log_records = [
        {
            "timeUnixNano": str(base_ns),
            "observedTimeUnixNano": str(base_ns),
            "severityNumber": 9,
            "severityText": "INFO",
            "body": {"stringValue": build_response_completed_body(args)},
            "attributes": [
                attr("event.name", "codex.sse_event"),
                attr("event.kind", "response.completed"),
                attr("model", args.model),
                attr("team", args.team),
                attr("user_id", args.user_id),
            ],
        },
        {
            "timeUnixNano": str(base_ns + 1_000_000),
            "observedTimeUnixNano": str(base_ns + 1_000_000),
            "severityNumber": 9,
            "severityText": "INFO",
            "body": {"stringValue": build_tool_decision_body(args)},
            "attributes": [
                attr("event.name", "codex.tool_decision"),
                attr("tool", args.tool),
                attr("tool_call_id", args.tool_call_id),
                attr("tool_decision", args.tool_decision),
                attr("team", args.team),
                attr("user_id", args.user_id),
                attr("model", args.model),
            ],
        },
        {
            "timeUnixNano": str(base_ns + 2_000_000),
            "observedTimeUnixNano": str(base_ns + 2_000_000),
            "severityNumber": 17 if args.tool_failure else 9,
            "severityText": "ERROR" if args.tool_failure else "INFO",
            "body": {"stringValue": build_tool_result_body(args)},
            "attributes": [
                attr("event.name", "codex.tool_result"),
                attr("tool", args.tool),
                attr("tool_call_id", args.tool_call_id),
                attr("tool_success", "false" if args.tool_failure else "true"),
                attr("tool_duration_ms", str(args.tool_duration_ms)),
                attr("tool_output_size", str(args.tool_output_size)),
                attr("team", args.team),
                attr("user_id", args.user_id),
                attr("model", args.model),
            ],
        },
    ]
    return {
        "resourceLogs": [
            {
                "resource": {"attributes": attributes},
                "scopeLogs": [
                    {
                        "scope": {"name": "task2-sample", "version": "1.0.0"},
                        "logRecords": log_records,
                    }
                ],
            }
        ]
    }


def build_metrics(start_ns: int, end_ns: int, args: argparse.Namespace) -> dict:
    common = [
        attr("model", args.model),
        attr("team", args.team),
        attr("user_id", args.user_id),
    ]
    tool_attrs = common + [attr("tool", args.tool), attr("success", "false" if args.tool_failure else "true")]
    return {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        attr("service.name", "codex-cli"),
                        attr("deployment.environment", args.environment),
                        attr("team", args.team),
                    ]
                },
                "scopeMetrics": [
                    {
                        "scope": {"name": "task2-sample", "version": "1.0.0"},
                        "metrics": [
                            {
                                "name": "codex.api_request",
                                "description": "Codex API requests",
                                "unit": "1",
                                "sum": {
                                    "aggregationTemporality": 2,
                                    "isMonotonic": True,
                                    "dataPoints": [
                                        {
                                            "attributes": common,
                                            "startTimeUnixNano": str(start_ns),
                                            "timeUnixNano": str(end_ns),
                                            "asInt": str(args.api_requests),
                                        }
                                    ],
                                },
                            },
                            {
                                "name": "codex.sse_event",
                                "description": "Codex SSE events",
                                "unit": "1",
                                "sum": {
                                    "aggregationTemporality": 2,
                                    "isMonotonic": True,
                                    "dataPoints": [
                                        {
                                            "attributes": common
                                            + [attr("kind", "response.completed")],
                                            "startTimeUnixNano": str(start_ns),
                                            "timeUnixNano": str(end_ns),
                                            "asInt": str(args.api_requests),
                                        }
                                    ],
                                },
                            },
                            {
                                "name": "codex.tool.call",
                                "description": "Codex tool calls",
                                "unit": "1",
                                "sum": {
                                    "aggregationTemporality": 2,
                                    "isMonotonic": True,
                                    "dataPoints": [
                                        {
                                            "attributes": tool_attrs,
                                            "startTimeUnixNano": str(start_ns),
                                            "timeUnixNano": str(end_ns),
                                            "asInt": str(args.tool_calls),
                                        }
                                    ],
                                },
                            },
                            {
                                "name": "codex.tool.call.duration_ms",
                                "description": "Codex tool call duration in milliseconds",
                                "unit": "ms",
                                "gauge": {
                                    "dataPoints": [
                                        {
                                            "attributes": tool_attrs,
                                            "timeUnixNano": str(end_ns),
                                            "asDouble": float(args.tool_duration_ms),
                                        }
                                    ]
                                },
                            },
                        ],
                    }
                ],
            }
        ]
    }


def build_traces(start_ns: int, args: argparse.Namespace) -> dict:
    trace_id = secrets.token_hex(16)
    root_span_id = secrets.token_hex(8)
    child_span_id = secrets.token_hex(8)
    tool_end_ns = start_ns + 1_000_000 + args.tool_duration_ms * 1_000_000
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        attr("service.name", "codex-cli"),
                        attr("deployment.environment", args.environment),
                        attr("team", args.team),
                        attr("user_id", args.user_id),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "task2-sample", "version": "1.0.0"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": root_span_id,
                                "name": "codex.session",
                                "kind": 1,
                                "startTimeUnixNano": str(start_ns),
                                "endTimeUnixNano": str(max(start_ns + 4_000_000, tool_end_ns + 1_000_000)),
                                "attributes": [
                                    attr("session_id", args.session_id),
                                    attr("conversation_id", args.conversation_id),
                                    attr("model", args.model),
                                ],
                            },
                            {
                                "traceId": trace_id,
                                "spanId": child_span_id,
                                "parentSpanId": root_span_id,
                                "name": "codex.tool.call",
                                "kind": 1,
                                "startTimeUnixNano": str(start_ns + 1_000_000),
                                "endTimeUnixNano": str(tool_end_ns),
                                "attributes": [
                                    attr("tool", args.tool),
                                    attr("tool_call_id", args.tool_call_id),
                                    attr("tool_success", "false" if args.tool_failure else "true"),
                                ],
                            },
                        ],
                    }
                ],
            }
        ]
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send sample OTLP data to the local collector.")
    parser.add_argument("--base-url", default="http://localhost:4318", help="OTLP HTTP base URL")
    parser.add_argument("--environment", default="local", help="Environment label")
    parser.add_argument("--team", default="platform", help="Team label")
    parser.add_argument("--user-id", default="dev-a", help="User label")
    parser.add_argument("--repository", default="/workspace/sample-repo", help="Repository label")
    parser.add_argument("--project", default="llm-monitoring", help="Project label")
    parser.add_argument("--session-id", default="session-task2-demo", help="Session id")
    parser.add_argument("--conversation-id", default="conv-task2-demo", help="Conversation id")
    parser.add_argument("--model", default="gpt-5-codex", help="Model label")
    parser.add_argument("--response-id", default="resp-task2-demo", help="Response id")
    parser.add_argument("--tool", default="web.search", help="Tool label")
    parser.add_argument("--tool-call-id", default="toolcall-task-demo", help="Tool call id")
    parser.add_argument("--tool-decision", default="approved", help="Tool decision result")
    parser.add_argument("--tool-duration-ms", type=int, default=180, help="Tool duration in milliseconds")
    parser.add_argument("--tool-output-size", type=int, default=4096, help="Tool output size in bytes")
    parser.add_argument("--tool-failure", action="store_true", help="Mark the tool result as failure")
    parser.add_argument("--tool-error-code", default="TOOL_TIMEOUT", help="Tool failure code")
    parser.add_argument("--tool-error-message", default="tool execution failed", help="Tool failure message")
    parser.add_argument("--api-requests", type=int, default=1, help="Cumulative API request count")
    parser.add_argument("--tool-calls", type=int, default=1, help="Cumulative tool call count")
    parser.add_argument("--input-tokens", type=int, default=1200, help="Response input tokens")
    parser.add_argument(
        "--cached-input-tokens",
        type=int,
        default=300,
        help="Cached token count within input_tokens",
    )
    parser.add_argument("--output-tokens", type=int, default=420, help="Response output tokens")
    parser.add_argument(
        "--reasoning-tokens",
        type=int,
        default=120,
        help="Reasoning token count within output_tokens",
    )
    parser.add_argument("--total-tokens", type=int, default=1620, help="Response total tokens")
    parser.add_argument(
        "--omit-cached-input-tokens",
        action="store_true",
        help="Omit cached_tokens breakdown from usage payload",
    )
    parser.add_argument(
        "--omit-reasoning-tokens",
        action="store_true",
        help="Omit reasoning_tokens breakdown from usage payload",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    start_ns = now_ns() - 5_000_000_000
    end_ns = now_ns()
    try:
        send_json(f"{args.base_url}/v1/logs", build_logs(end_ns, args))
        send_json(f"{args.base_url}/v1/metrics", build_metrics(start_ns, end_ns, args))
        send_json(f"{args.base_url}/v1/traces", build_traces(end_ns, args))
    except (urllib.error.URLError, RuntimeError) as error:
        print(f"sample OTLP send failed: {error}", file=sys.stderr)
        return 1
    print("sample OTLP logs/metrics/traces sent successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
