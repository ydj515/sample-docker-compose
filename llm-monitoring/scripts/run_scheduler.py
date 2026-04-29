#!/usr/bin/env python3
"""정규화 및 비용 계산 작업을 주기적으로 실행하는 컨테이너용 스케줄러."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    interval_seconds: int
    command: list[str]
    run_on_start: bool = True


def int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def common_args() -> list[str]:
    args = [
        "--postgres-host",
        os.getenv("POSTGRES_HOST", "postgres"),
        "--postgres-port",
        os.getenv("POSTGRES_PORT", "5432"),
        "--postgres-db",
        os.getenv("POSTGRES_DB", "codex_observability"),
        "--postgres-user",
        os.getenv("POSTGRES_USER", "codex"),
    ]
    return args


def build_jobs() -> list[ScheduledJob]:
    python_bin = sys.executable
    pg_args = common_args()
    loki_url = os.getenv("LOKI_URL", "http://loki:3100")
    tempo_url = os.getenv("TEMPO_URL", "http://tempo:3200")
    chunk_seconds = str(int_env("SCHEDULER_NORMALIZE_CHUNK_SECONDS", 300))
    usage_lookback = str(int_env("SCHEDULER_NORMALIZE_USAGE_LOOKBACK_SECONDS", 300))
    tool_lookback = str(int_env("SCHEDULER_NORMALIZE_TOOL_LOOKBACK_SECONDS", 300))
    api_lookback = str(int_env("SCHEDULER_NORMALIZE_API_LOOKBACK_SECONDS", 300))
    trace_lookback = str(int_env("SCHEDULER_NORMALIZE_TRACE_LOOKBACK_SECONDS", 900))
    helper_lookback = str(int_env("SCHEDULER_NORMALIZE_LOCAL_HELPER_LOOKBACK_SECONDS", 300))

    return [
        ScheduledJob(
            name="normalize-usage-events",
            interval_seconds=int_env("SCHEDULER_NORMALIZE_USAGE_INTERVAL_SECONDS", 60),
            command=[
                python_bin,
                "scripts/normalize_usage_events.py",
                "--loki-url",
                loki_url,
                "--pipeline-name",
                os.getenv("SCHEDULER_USAGE_PIPELINE_NAME", "scheduler-usage-events-v1"),
                "--lookback-seconds",
                usage_lookback,
                "--chunk-seconds",
                chunk_seconds,
                *pg_args,
            ],
            run_on_start=True,
        ),
        ScheduledJob(
            name="normalize-tool-events",
            interval_seconds=int_env("SCHEDULER_NORMALIZE_TOOL_INTERVAL_SECONDS", 60),
            command=[
                python_bin,
                "scripts/normalize_tool_events.py",
                "--loki-url",
                loki_url,
                "--pipeline-name",
                os.getenv("SCHEDULER_TOOL_PIPELINE_NAME", "scheduler-tool-events-v1"),
                "--lookback-seconds",
                tool_lookback,
                "--chunk-seconds",
                chunk_seconds,
                *pg_args,
            ],
            run_on_start=True,
        ),
        ScheduledJob(
            name="normalize-api-request-events",
            interval_seconds=int_env("SCHEDULER_NORMALIZE_API_INTERVAL_SECONDS", 60),
            command=[
                python_bin,
                "scripts/normalize_api_request_events.py",
                "--loki-url",
                loki_url,
                "--pipeline-name",
                os.getenv("SCHEDULER_API_PIPELINE_NAME", "scheduler-api-request-events-v1"),
                "--lookback-seconds",
                api_lookback,
                "--chunk-seconds",
                chunk_seconds,
                *pg_args,
            ],
            run_on_start=True,
        ),
        ScheduledJob(
            name="normalize-trace-spans",
            interval_seconds=int_env("SCHEDULER_NORMALIZE_TRACE_INTERVAL_SECONDS", 60),
            command=[
                python_bin,
                "scripts/normalize_trace_spans.py",
                "--tempo-url",
                tempo_url,
                "--pipeline-name",
                os.getenv("SCHEDULER_TRACE_PIPELINE_NAME", "scheduler-trace-spans-v1"),
                "--lookback-seconds",
                trace_lookback,
                "--search-limit",
                os.getenv("SCHEDULER_TRACE_SEARCH_LIMIT", "500"),
                *pg_args,
            ],
            run_on_start=True,
        ),
        ScheduledJob(
            name="normalize-local-helper-events",
            interval_seconds=int_env("SCHEDULER_NORMALIZE_LOCAL_HELPER_INTERVAL_SECONDS", 60),
            command=[
                python_bin,
                "scripts/normalize_local_helper_events.py",
                "--loki-url",
                loki_url,
                "--pipeline-name",
                os.getenv(
                    "SCHEDULER_LOCAL_HELPER_PIPELINE_NAME",
                    "scheduler-local-helper-events-v1",
                ),
                "--lookback-seconds",
                helper_lookback,
                "--chunk-seconds",
                chunk_seconds,
                *pg_args,
            ],
            run_on_start=True,
        ),
        ScheduledJob(
            name="compute-daily",
            interval_seconds=int_env("SCHEDULER_COMPUTE_DAILY_INTERVAL_SECONDS", 300),
            command=[
                python_bin,
                "scripts/calculate_costs.py",
                *pg_args,
                "compute-daily",
                "--date",
                str(date.today()),
            ],
            run_on_start=True,
        ),
        ScheduledJob(
            name="purge-raw-events",
            interval_seconds=int_env("SCHEDULER_PURGE_RAW_INTERVAL_SECONDS", 86400),
            command=[
                python_bin,
                "scripts/calculate_costs.py",
                *pg_args,
                "purge-raw-events",
                "--older-than-days",
                os.getenv("POSTGRES_RAW_EVENT_RETENTION_DAYS", "30"),
            ],
            run_on_start=False,
        ),
        ScheduledJob(
            name="drop-old-rows",
            interval_seconds=int_env("SCHEDULER_DROP_OLD_ROWS_INTERVAL_SECONDS", 86400),
            command=[
                python_bin,
                "scripts/calculate_costs.py",
                *pg_args,
                "drop-old-rows",
                "--older-than-days",
                os.getenv("POSTGRES_NORMALIZED_RETENTION_DAYS", "365"),
            ],
            run_on_start=False,
        ),
    ]


def log(message: str) -> None:
    print(f"[scheduler] {message}", flush=True)


def run_job(job: ScheduledJob) -> int:
    command = list(job.command)
    if job.name == "compute-daily":
        command[-1] = str(date.today())

    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    log(f"start {job.name} at {started_at}")
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )
    if result.stdout.strip():
        print(result.stdout.rstrip(), flush=True)
    if result.stderr.strip():
        print(result.stderr.rstrip(), file=sys.stderr, flush=True)
    log(f"finish {job.name} rc={result.returncode}")
    return result.returncode


def main() -> int:
    jobs = build_jobs()
    now = time.time()
    next_run: dict[str, float] = {}
    for job in jobs:
        next_run[job.name] = now if job.run_on_start else now + job.interval_seconds

    log("scheduler loop started")

    while True:
        now = time.time()
        due_jobs = [job for job in jobs if next_run[job.name] <= now]

        if not due_jobs:
            sleep_for = max(1.0, min(next_run.values()) - now)
            time.sleep(min(sleep_for, 5.0))
            continue

        for job in due_jobs:
            run_job(job)
            next_run[job.name] = time.time() + job.interval_seconds


if __name__ == "__main__":
    raise SystemExit(main())
