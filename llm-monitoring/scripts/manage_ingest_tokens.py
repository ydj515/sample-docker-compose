#!/usr/bin/env python3
"""ingest token 발급/조회/비활성화 도구."""

from __future__ import annotations

import argparse
import hashlib
import secrets

from runtime_common import add_postgres_args, psql_query, resolve_postgres_target, sql_literal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage codex ingest tokens.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    issue_parser = subparsers.add_parser("issue", help="새 ingest token 발급 또는 기존 token 교체")
    add_postgres_args(issue_parser)
    issue_parser.add_argument("--ingest-token-id", required=True, help="운영용 token key id")
    issue_parser.add_argument("--resolved-user-id", required=True, help="canonical user id")
    issue_parser.add_argument("--resolved-team", required=True, help="canonical team")
    issue_parser.add_argument("--description", default=None, help="운영 메모")
    issue_parser.add_argument("--expires-at", default=None, help="RFC3339 timestamptz 문자열")
    issue_parser.add_argument(
        "--raw-token",
        default=None,
        help="미지정 시 새 random token 생성. 지정하면 해당 raw token으로 교체한다.",
    )

    list_parser = subparsers.add_parser("list", help="현재 ingest token 목록 조회")
    add_postgres_args(list_parser)

    revoke_parser = subparsers.add_parser("revoke", help="ingest token 비활성화")
    add_postgres_args(revoke_parser)
    revoke_parser.add_argument("--ingest-token-id", required=True, help="비활성화할 token key id")

    return parser


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_token(args: argparse.Namespace) -> int:
    target = resolve_postgres_target(args)
    raw_token = args.raw_token or secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    expires_sql = "null" if not args.expires_at else sql_literal(args.expires_at)
    description_sql = "null" if not args.description else sql_literal(args.description)
    sql = f"""
insert into codex_ingest_token_mapping (
    ingest_token_id,
    token_hash,
    resolved_user_id,
    resolved_team,
    description,
    is_active,
    expires_at,
    updated_at
)
values (
    {sql_literal(args.ingest_token_id)},
    {sql_literal(token_hash)},
    {sql_literal(args.resolved_user_id)},
    {sql_literal(args.resolved_team)},
    {description_sql},
    true,
    {expires_sql},
    now()
)
on conflict (ingest_token_id) do update set
    token_hash = excluded.token_hash,
    resolved_user_id = excluded.resolved_user_id,
    resolved_team = excluded.resolved_team,
    description = coalesce(excluded.description, codex_ingest_token_mapping.description),
    is_active = true,
    expires_at = excluded.expires_at,
    updated_at = now();
"""
    psql_query(target, sql)
    print(f"ingest_token_id={args.ingest_token_id}")
    print(f"resolved_user_id={args.resolved_user_id}")
    print(f"resolved_team={args.resolved_team}")
    print(f"raw_token={raw_token}")
    print("주의: raw_token은 다시 조회되지 않으므로 안전한 비밀 저장소에 별도로 보관해야 한다.")
    return 0


def list_tokens(args: argparse.Namespace) -> int:
    target = resolve_postgres_target(args)
    sql = """
select
    ingest_token_id,
    coalesce(resolved_user_id, '(unknown)') as resolved_user_id,
    coalesce(resolved_team, '(unknown)') as resolved_team,
    case when is_active then 'active' else 'inactive' end as status,
    coalesce(to_char(expires_at, 'YYYY-MM-DD"T"HH24:MI:SSOF'), '-') as expires_at
from codex_ingest_token_mapping
order by ingest_token_id;
"""
    rows = psql_query(target, sql, tuples_only=True).strip()
    if not rows:
        print("no ingest tokens")
        return 0
    for line in rows.splitlines():
        token_id, user_id, team, status, expires_at = (line.split("|") + ["", "", "", "", ""])[:5]
        print(f"{token_id}\t{user_id}\t{team}\t{status}\t{expires_at}")
    return 0


def revoke_token(args: argparse.Namespace) -> int:
    target = resolve_postgres_target(args)
    sql = f"""
update codex_ingest_token_mapping
set is_active = false,
    updated_at = now()
where ingest_token_id = {sql_literal(args.ingest_token_id)};
"""
    psql_query(target, sql)
    print(f"revoked ingest_token_id={args.ingest_token_id}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "issue":
        return issue_token(args)
    if args.command == "list":
        return list_tokens(args)
    if args.command == "revoke":
        return revoke_token(args)
    parser.error(f"unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
