#!/usr/bin/env python3
"""TASK-5 비용 계산 및 데이터 보관 관리."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from runtime_common import add_postgres_args, mark_job_finished, mark_job_started, psql_query
from runtime_common import resolve_postgres_target


RETENTION_COMMANDS = {"purge-raw-events", "drop-old-rows"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex cost calculation and retention jobs.")
    add_postgres_args(parser)

    sub = parser.add_subparsers(dest="command", required=True)

    p_daily = sub.add_parser("compute-daily", help="Compute costs for one date (default: yesterday)")
    p_daily.add_argument("--date", default=None, help="YYYY-MM-DD (default: yesterday)")
    p_daily.add_argument("--dry-run", action="store_true")

    p_range = sub.add_parser("compute-range", help="Recompute costs for a date range")
    p_range.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    p_range.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD (inclusive)")
    p_range.add_argument("--dry-run", action="store_true")

    p_purge = sub.add_parser("purge-raw-events", help="Redact raw_event older than N days")
    p_purge.add_argument("--older-than-days", type=int, default=30)
    p_purge.add_argument("--dry-run", action="store_true")

    p_drop = sub.add_parser("drop-old-rows", help="Delete usage event rows older than N days")
    p_drop.add_argument("--older-than-days", type=int, default=365)
    p_drop.add_argument("--dry-run", action="store_true")

    return parser.parse_args()


def job_group_for_command(command: str) -> str:
    if command in RETENTION_COMMANDS:
        return "retention"
    return "cost"


def should_track_job(args: argparse.Namespace) -> bool:
    return not getattr(args, "dry_run", False)


def _upsert_cost_for_date_sql(target_date: str) -> str:
    return f"""
delete from codex_daily_cost_agg
where usage_date = '{target_date}'::date;

insert into codex_daily_cost_agg (
    usage_date,
    team,
    user_id,
    repository,
    model,
    price_policy_version,
    currency,
    total_requests,
    total_input_tokens,
    total_cached_input_tokens,
    total_output_tokens,
    total_reasoning_tokens,
    total_tokens,
    total_input_cost,
    total_cached_input_cost,
    total_output_cost,
    total_reasoning_cost,
    total_estimated_cost,
    updated_at
)
select
    '{target_date}'::date                            as usage_date,
    coalesce(resolved_team, team, '(unknown)')       as team,
    coalesce(resolved_user_id, user_id, '(unknown)') as user_id,
    coalesce(repository, '(unknown)')                as repository,
    coalesce(model,      '(unknown)')                as model,
    coalesce(price_policy_version, 'unknown')        as price_policy_version,
    coalesce(currency,   'USD')                      as currency,
    count(*)                                         as total_requests,
    sum(input_tokens)                                as total_input_tokens,
    sum(coalesce(cached_input_tokens, 0))            as total_cached_input_tokens,
    sum(output_tokens)                               as total_output_tokens,
    sum(coalesce(reasoning_tokens, 0))               as total_reasoning_tokens,
    sum(total_tokens)                                as total_tokens,
    sum(coalesce(input_cost,        0))              as total_input_cost,
    sum(coalesce(cached_input_cost, 0))              as total_cached_input_cost,
    sum(coalesce(output_cost,       0))              as total_output_cost,
    sum(coalesce(reasoning_cost,    0))              as total_reasoning_cost,
    sum(coalesce(total_estimated_cost, 0))           as total_estimated_cost,
    now()                                            as updated_at
from codex_usage_events_with_cost
where event_time::date = '{target_date}'::date
group by
    coalesce(resolved_team, team, '(unknown)'),
    coalesce(resolved_user_id, user_id, '(unknown)'),
    repository,
    model,
    price_policy_version,
    currency;
"""


def cmd_compute_daily(args: argparse.Namespace, target) -> int:
    target_date = args.date or str(date.today() - timedelta(days=1))

    try:
        date.fromisoformat(target_date)
    except ValueError:
        print(f"날짜 형식 오류: {target_date} (YYYY-MM-DD 필요)", file=sys.stderr)
        return 1

    sql = _upsert_cost_for_date_sql(target_date)

    if args.dry_run:
        print(f"[dry-run] compute-daily date={target_date}")
        print(sql)
        return 0

    psql_query(target, sql)
    result = psql_query(
        target,
        (
            f"select count(*), sum(total_requests), round(sum(total_estimated_cost)::numeric, 4)"
            f" from codex_daily_cost_agg where usage_date = '{target_date}';"
        ),
        tuples_only=True,
    ).strip()
    rows, requests, cost = result.split("|") if result else ("0", "0", "0")
    print(f"compute-daily date={target_date}: rows={rows}, requests={requests}, total_estimated_cost={cost} USD")
    return 0


def cmd_compute_range(args: argparse.Namespace, target) -> int:
    try:
        start = date.fromisoformat(args.date_from)
        end = date.fromisoformat(args.date_to)
    except ValueError as error:
        print(f"날짜 형식 오류: {error}", file=sys.stderr)
        return 1

    if start > end:
        print("--from 이 --to 보다 이후입니다.", file=sys.stderr)
        return 1

    current = start
    total_processed = 0
    while current <= end:
        current_date = str(current)
        sql = _upsert_cost_for_date_sql(current_date)
        if args.dry_run:
            print(f"[dry-run] would compute {current_date}")
        else:
            psql_query(target, sql)
            total_processed += 1
        current += timedelta(days=1)

    action = "would process" if args.dry_run else "processed"
    days = (end - start).days + 1
    print(f"compute-range {start} ~ {end}: {action} {days} days, upserted {total_processed} day batches")
    return 0


def cmd_purge_raw_events(args: argparse.Namespace, target) -> int:
    cutoff_days = args.older_than_days
    count_sql = (
        f"select count(*) from codex_usage_events"
        f" where event_time < now() - interval '{cutoff_days} days'"
        f" and raw_event != '{{\"_purged\":true}}'::jsonb;"
    )
    count = psql_query(target, count_sql, tuples_only=True).strip()
    print(f"raw_event purge 대상: {count} rows (event_time < now() - {cutoff_days}일)")

    if args.dry_run:
        return 0

    update_sql = (
        f"update codex_usage_events"
        f" set raw_event = '{{\"_purged\":true}}'::jsonb"
        f" where event_time < now() - interval '{cutoff_days} days'"
        f" and raw_event != '{{\"_purged\":true}}'::jsonb;"
    )
    psql_query(target, update_sql)
    print(f"raw_event purge 완료: {count} rows -> {{\"_purged\":true}}")
    return 0


def cmd_drop_old_rows(args: argparse.Namespace, target) -> int:
    cutoff_days = args.older_than_days
    count_sql = (
        f"select count(*) from codex_usage_events"
        f" where event_time < now() - interval '{cutoff_days} days';"
    )
    count = psql_query(target, count_sql, tuples_only=True).strip()
    print(f"삭제 대상: {count} rows (event_time < now() - {cutoff_days}일)")

    if args.dry_run:
        return 0

    delete_sql = (
        f"delete from codex_usage_events"
        f" where event_time < now() - interval '{cutoff_days} days';"
    )
    psql_query(target, delete_sql)
    print(f"retention 삭제 완료: {count} rows removed")
    return 0


def main() -> int:
    args = parse_args()
    try:
        target = resolve_postgres_target(args)
    except RuntimeError as error:
        print(f"DB 연결 실패: {error}", file=sys.stderr)
        return 1

    job_name = args.command
    job_group = job_group_for_command(job_name)
    tracking_enabled = should_track_job(args)

    if tracking_enabled:
        try:
            mark_job_started(target, job_name, job_group)
        except RuntimeError as error:
            print(f"job status 시작 기록 실패: {error}", file=sys.stderr)
            return 1

    try:
        if args.command == "compute-daily":
            rc = cmd_compute_daily(args, target)
        elif args.command == "compute-range":
            rc = cmd_compute_range(args, target)
        elif args.command == "purge-raw-events":
            rc = cmd_purge_raw_events(args, target)
        elif args.command == "drop-old-rows":
            rc = cmd_drop_old_rows(args, target)
        else:
            print(f"알 수 없는 커맨드: {args.command}", file=sys.stderr)
            rc = 1
    except RuntimeError as error:
        if tracking_enabled:
            try:
                mark_job_finished(
                    target,
                    job_name,
                    job_group,
                    success=False,
                    error_message=str(error),
                )
            except RuntimeError as mark_error:
                print(f"job status 실패 기록 실패: {mark_error}", file=sys.stderr)
        print(f"오류: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001
        if tracking_enabled:
            try:
                mark_job_finished(
                    target,
                    job_name,
                    job_group,
                    success=False,
                    error_message=str(error),
                )
            except RuntimeError as mark_error:
                print(f"job status 실패 기록 실패: {mark_error}", file=sys.stderr)
        print(f"예상치 못한 오류: {error}", file=sys.stderr)
        return 1

    if tracking_enabled:
        try:
            mark_job_finished(
                target,
                job_name,
                job_group,
                success=(rc == 0),
                error_message=None if rc == 0 else f"command exited with {rc}",
            )
        except RuntimeError as error:
            print(f"job status 완료 기록 실패: {error}", file=sys.stderr)
            return 1

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
