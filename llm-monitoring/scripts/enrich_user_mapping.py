#!/usr/bin/env python3
"""user_email -> 내부 canonical user/team 매핑 관리 및 enrichment job.

서브커맨드:
  import-csv  : CSV 파일에서 codex_user_email_mapping 에 upsert
  backfill    : usage/tool/api/fn_call events 의 resolved identity 컬럼을 채움
  report      : 이벤트에 등장한 user 중 매핑 미존재 목록 출력
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage user_email mapping and enrich event tables."
    )
    parser.add_argument("--postgres-db", default="codex_observability", help="PostgreSQL database name")
    parser.add_argument("--postgres-user", default="codex", help="PostgreSQL user")

    sub = parser.add_subparsers(dest="command", required=True)

    # import-csv
    p_csv = sub.add_parser("import-csv", help="Import user mappings from a CSV file")
    p_csv.add_argument("csv_file", type=Path, help="Path to CSV file")
    p_csv.add_argument(
        "--source",
        default="csv",
        help="Source label written to codex_user_email_mapping.source (default: csv)",
    )
    p_csv.add_argument("--dry-run", action="store_true", help="Parse and validate only, no DB writes")

    # backfill
    p_backfill = sub.add_parser(
        "backfill",
        help="Back-fill resolved identity columns in event tables where mapping exists",
    )
    p_backfill.add_argument("--dry-run", action="store_true", help="Show counts only, no DB writes")

    # report
    sub.add_parser("report", help="Print users seen in events that have no mapping")

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


def psql_query(
    container: str, user: str, database: str, sql: str, *, tuples_only: bool = False
) -> str:
    command = [
        "docker", "exec", "-i", container,
        "psql", "-U", user, "-d", database, "-v", "ON_ERROR_STOP=1",
    ]
    if tuples_only:
        command.extend(["-At"])
    command.extend(["-f", "-"])
    return run_command(command, input_text=sql)


# CSV 필드 정의 (user_email 은 필수, 나머지 선택)
CSV_FIELDS = [
    "user_email",
    "resolved_user_id",
    "display_name",
    "team",
    "department",
    "cost_center",
    "github_handle",
    "slack_handle",
    "is_active",
    "notes",
]


def _str_or_null(value: str) -> str:
    stripped = value.strip()
    if stripped == "":
        return "null"
    return sql_literal(stripped)


def _bool_or_null(value: str) -> str:
    stripped = value.strip().lower()
    if stripped in ("true", "1", "yes", "y"):
        return "true"
    if stripped in ("false", "0", "no", "n"):
        return "false"
    return "true"  # 기본값


def load_csv(csv_file: Path) -> list[dict[str, str]]:
    """CSV 파일을 읽어 row 목록 반환. user_email 필드는 필수."""
    rows: list[dict[str, str]] = []
    with csv_file.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV 파일에 헤더가 없습니다.")
        missing = set(["user_email"]) - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV 필수 컬럼 누락: {missing}")
        for i, row in enumerate(reader, start=2):
            email = row.get("user_email", "").strip().lower()
            if not email:
                print(f"  경고: {i}행 user_email 비어있음 — 건너뜀")
                continue
            rows.append({k: row.get(k, "") for k in CSV_FIELDS})
    return rows


def cmd_import_csv(args: argparse.Namespace, container: str) -> int:
    rows = load_csv(args.csv_file)
    if not rows:
        print("import 할 row 가 없습니다.")
        return 0

    print(f"CSV 에서 {len(rows)}개 row 로드 완료")

    if args.dry_run:
        for row in rows[:5]:
            print(f"  {row}")
        return 0

    # JSON 배열로 일괄 upsert
    payload = json.dumps(rows, ensure_ascii=True)
    source = sql_literal(args.source)
    sql = f"""
with rows as (
    select *
    from jsonb_to_recordset($json${payload}$json$::jsonb) as x(
        user_email text,
        resolved_user_id text,
        display_name text,
        team text,
        department text,
        cost_center text,
        github_handle text,
        slack_handle text,
        is_active text,
        notes text
    )
)
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
    lower(user_email),
    nullif(trim(resolved_user_id), ''),
    nullif(trim(display_name), ''),
    nullif(trim(team), ''),
    nullif(trim(department), ''),
    nullif(trim(cost_center), ''),
    nullif(trim(github_handle), ''),
    nullif(trim(slack_handle), ''),
    case
        when lower(trim(is_active)) in ('false','0','no','n') then false
        else true
    end,
    {source},
    nullif(trim(notes), ''),
    now()
from rows
where user_email is not null and trim(user_email) <> ''
on conflict (user_email) do update set
    resolved_user_id = coalesce(excluded.resolved_user_id, codex_user_email_mapping.resolved_user_id),
    display_name  = coalesce(excluded.display_name, codex_user_email_mapping.display_name),
    team          = coalesce(excluded.team, codex_user_email_mapping.team),
    department    = coalesce(excluded.department, codex_user_email_mapping.department),
    cost_center   = coalesce(excluded.cost_center, codex_user_email_mapping.cost_center),
    github_handle = coalesce(excluded.github_handle, codex_user_email_mapping.github_handle),
    slack_handle  = coalesce(excluded.slack_handle, codex_user_email_mapping.slack_handle),
    is_active     = excluded.is_active,
    source        = excluded.source,
    notes         = coalesce(excluded.notes, codex_user_email_mapping.notes),
    updated_at    = now();
"""
    psql_query(container, args.postgres_user, args.postgres_db, sql)
    print(f"{len(rows)}개 mapping upsert 완료 (source={args.source})")
    return 0


def cmd_backfill(args: argparse.Namespace, container: str) -> int:
    """mapping 과 canonical user 정보를 이용해 resolved identity 를 채운다."""

    count_sql = """
select
    (select count(*) from codex_usage_events e
     join codex_user_email_mapping m
       on coalesce(lower(nullif(e.observed_user_email, '')),
                   case when position('@' in coalesce(e.user_id, '')) > 0 then lower(e.user_id) else null end) = m.user_email
     where (e.resolved_user_id is null and m.resolved_user_id is not null)
        or (e.resolved_team is null and m.team is not null)) as usage_fillable,
    (select count(*) from codex_tool_events e
     join codex_user_email_mapping m
       on coalesce(lower(nullif(e.observed_user_email, '')),
                   case when position('@' in coalesce(e.user_id, '')) > 0 then lower(e.user_id) else null end) = m.user_email
     where (e.resolved_user_id is null and m.resolved_user_id is not null)
        or (e.resolved_team is null and m.team is not null)) as tool_fillable,
    (select count(*) from codex_api_request_events e
     join codex_user_email_mapping m
       on coalesce(lower(nullif(e.observed_user_email, '')),
                   case when position('@' in coalesce(e.user_id, '')) > 0 then lower(e.user_id) else null end) = m.user_email
     where (e.resolved_user_id is null and m.resolved_user_id is not null)
        or (e.resolved_team is null and m.team is not null)) as api_fillable,
    (select count(*) from codex_fn_call_events e
     join codex_user_email_mapping m on lower(e.user_id) = m.user_email
     where e.team is null and m.team is not null) as fn_call_fillable;
"""
    result = psql_query(
        container, args.postgres_user, args.postgres_db, count_sql, tuples_only=True
    ).strip()
    usage_n, tool_n, api_n, fn_n = (int(v) for v in result.split("|"))
    print(
        "backfill 가능: "
        f"usage_events={usage_n}, tool_events={tool_n}, api_request_events={api_n}, fn_call_events={fn_n}"
    )

    if args.dry_run:
        return 0

    update_sql = """
update codex_usage_events e
set observed_user_email = coalesce(
        e.observed_user_email,
        case when position('@' in coalesce(e.user_id, '')) > 0 then lower(e.user_id) else null end
    ),
    resolved_user_id = coalesce(e.resolved_user_id, m.resolved_user_id),
    resolved_team = coalesce(e.resolved_team, m.team, e.team)
from codex_user_email_mapping m
where coalesce(
        lower(nullif(e.observed_user_email, '')),
        case when position('@' in coalesce(e.user_id, '')) > 0 then lower(e.user_id) else null end
    ) = m.user_email
  and (
      (e.resolved_user_id is null and m.resolved_user_id is not null)
      or (e.resolved_team is null and m.team is not null)
      or e.observed_user_email is null
  );

update codex_tool_events e
set observed_user_email = coalesce(
        e.observed_user_email,
        case when position('@' in coalesce(e.user_id, '')) > 0 then lower(e.user_id) else null end
    ),
    resolved_user_id = coalesce(e.resolved_user_id, m.resolved_user_id),
    resolved_team = coalesce(e.resolved_team, m.team, e.team)
from codex_user_email_mapping m
where coalesce(
        lower(nullif(e.observed_user_email, '')),
        case when position('@' in coalesce(e.user_id, '')) > 0 then lower(e.user_id) else null end
    ) = m.user_email
  and (
      (e.resolved_user_id is null and m.resolved_user_id is not null)
      or (e.resolved_team is null and m.team is not null)
      or e.observed_user_email is null
  );

update codex_api_request_events e
set observed_user_email = coalesce(
        e.observed_user_email,
        case when position('@' in coalesce(e.user_id, '')) > 0 then lower(e.user_id) else null end
    ),
    resolved_user_id = coalesce(e.resolved_user_id, m.resolved_user_id),
    resolved_team = coalesce(e.resolved_team, m.team, e.team)
from codex_user_email_mapping m
where coalesce(
        lower(nullif(e.observed_user_email, '')),
        case when position('@' in coalesce(e.user_id, '')) > 0 then lower(e.user_id) else null end
    ) = m.user_email
  and (
      (e.resolved_user_id is null and m.resolved_user_id is not null)
      or (e.resolved_team is null and m.team is not null)
      or e.observed_user_email is null
  );

update codex_fn_call_events e
set team = m.team
from codex_user_email_mapping m
where lower(e.user_id) = m.user_email
  and e.team is null
  and m.team is not null;
"""
    psql_query(container, args.postgres_user, args.postgres_db, update_sql)
    print(
        "backfill 완료: "
        f"usage_events={usage_n}, tool_events={tool_n}, api_request_events={api_n}, fn_call_events={fn_n} rows 갱신"
    )
    return 0


def cmd_report(args: argparse.Namespace, container: str) -> int:
    """이벤트에 등장했지만 매핑이 없는 user 목록 출력."""

    sql = """
select user_email, resolved_user_id, has_mapping, team, department
from codex_user_mapping_coverage
order by has_mapping, user_email;
"""
    result = psql_query(
        container, args.postgres_user, args.postgres_db, sql, tuples_only=True
    ).strip()

    if not result:
        print("이벤트에 user 데이터가 없습니다.")
        return 0

    unmapped: list[str] = []
    mapped: list[str] = []
    for line in result.splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        email, resolved_user_id, has_mapping = parts[0], parts[1], parts[2]
        team = parts[3] if len(parts) > 3 else ""
        department = parts[4] if len(parts) > 4 else ""
        if has_mapping == "f":
            unmapped.append(email)
        else:
            mapped.append(
                f"{email} -> {resolved_user_id or '-'} (team={team or '-'}, dept={department or '-'})"
            )

    print(f"\n[매핑 완료: {len(mapped)}명]")
    for entry in mapped:
        print(f"  + {entry}")

    print(f"\n[매핑 미존재: {len(unmapped)}명]")
    for email in unmapped:
        print(f"  - {email}")

    total = len(mapped) + len(unmapped)
    if total > 0:
        pct = round(100.0 * len(mapped) / total, 1)
        print(f"\n매핑 커버리지: {pct}% ({len(mapped)}/{total})")
    return 0


def main() -> int:
    args = parse_args()
    container = resolve_postgres_container()
    if args.command == "import-csv":
        return cmd_import_csv(args, container)
    if args.command == "backfill":
        return cmd_backfill(args, container)
    if args.command == "report":
        return cmd_report(args, container)
    print(f"알 수 없는 서브커맨드: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
