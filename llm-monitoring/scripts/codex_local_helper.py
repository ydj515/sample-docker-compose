#!/usr/bin/env python3
"""Codex local helper MVP.

기본 목표:
- Codex notify payload를 받아 로컬 작업 컨텍스트를 OTLP log로 전송
- raw prompt / raw assistant message / tool output 원문은 수집하지 않음
- repository / branch / remote slug / message 길이 통계만 보강

현재 범위:
- notify 기반 turn-complete payload 처리
- approval lifecycle 정밀 측정을 위한 이벤트 스키마는 예약하되,
  실제 human wait time 수집은 후속 hook 연동이 필요
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import tomllib
    HAS_TOMLLIB = True
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]
    HAS_TOMLLIB = False


HELPER_VERSION = "0.1.0"
DEFAULT_CONFIG_PATH = "~/.codex/codex-local-helper.toml"
DEFAULT_CODEX_CONFIG_PATH = "~/.codex/config.toml"
DEFAULT_EVENT_NAME = "codex.local_helper_context"
DEFAULT_SERVICE_NAME = "codex-local-helper"
DEFAULT_SCOPE_NAME = "codex_local_helper"


def now_ns() -> int:
    return time.time_ns()


def attr(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


def load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    raw_text = path.read_text(encoding="utf-8")
    if HAS_TOMLLIB:
        return tomllib.loads(raw_text)
    return parse_simple_toml(raw_text)


def parse_simple_toml(raw_text: str) -> dict:
    """tomllib가 없는 Python 3.9 환경용 최소 TOML 파서.

    helper 설정 파일처럼 `[section]` + `key = value` 형태만 지원한다.
    Codex 본 설정처럼 더 복잡한 TOML은 load_codex_otel_config의 regex fallback에 맡긴다.
    """

    result: dict[str, object] = {}
    current: dict[str, object] = result

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section_name = line[1:-1].strip()
            if not section_name:
                continue
            section = result.get(section_name)
            if not isinstance(section, dict):
                section = {}
                result[section_name] = section
            current = section
            continue
        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()

        if "#" in value and not value.startswith('"'):
            value = value.split("#", 1)[0].strip()

        if value.startswith('"') and value.endswith('"'):
            parsed: object = bytes(value[1:-1], "utf-8").decode("unicode_escape")
        elif value.lower() == "true":
            parsed = True
        elif value.lower() == "false":
            parsed = False
        else:
            parsed = value

        current[key] = parsed

    return result


def expand_path(raw: str) -> Path:
    return Path(os.path.expanduser(raw)).resolve()


def load_helper_config(path: Path) -> dict:
    data = load_toml(path)
    helper = data.get("helper", {})
    return {
        "event_name": helper.get("event_name", DEFAULT_EVENT_NAME),
        "logs_endpoint": helper.get("logs_endpoint", ""),
        "codex_config_path": helper.get("codex_config_path", DEFAULT_CODEX_CONFIG_PATH),
        "include_raw_cwd": bool(helper.get("include_raw_cwd", False)),
        "include_repo_root": bool(helper.get("include_repo_root", True)),
        "include_git_branch": bool(helper.get("include_git_branch", True)),
        "include_git_remote_slug": bool(helper.get("include_git_remote_slug", True)),
        "collect_input_message_stats": bool(helper.get("collect_input_message_stats", True)),
        "collect_last_assistant_message_stats": bool(helper.get("collect_last_assistant_message_stats", True)),
        "collect_host_name": bool(helper.get("collect_host_name", True)),
        "redact_home_prefix": bool(helper.get("redact_home_prefix", True)),
    }


def load_codex_otel_config(path: Path) -> dict:
    raw_text = path.read_text(encoding="utf-8") if path.exists() else ""
    data = {}
    if raw_text and HAS_TOMLLIB:
        try:
            data = tomllib.loads(raw_text)
        except tomllib.TOMLDecodeError:
            data = {}

    otel = data.get("otel", {})
    exporter = otel.get("exporter", {})
    otlp_http = exporter.get("otlp-http", {}) if isinstance(exporter, dict) else {}
    headers = otlp_http.get("headers", {}) if isinstance(otlp_http, dict) else {}
    environment = otel.get("environment", "")
    logs_endpoint = otlp_http.get("endpoint", "")

    if not environment and raw_text:
        env_match = re.search(
            r"(?ms)^\[otel\]\s+.*?^\s*environment\s*=\s*\"([^\"]+)\"",
            raw_text,
        )
        if env_match:
            environment = env_match.group(1)

    if not logs_endpoint and raw_text:
        endpoint_match = re.search(
            r"(?ms)^\s*exporter\s*=\s*\{\s*otlp-http\s*=\s*\{.*?^\s*endpoint\s*=\s*\"([^\"]+)\"",
            raw_text,
        )
        if endpoint_match:
            logs_endpoint = endpoint_match.group(1)

    if (not isinstance(headers, dict) or not headers) and raw_text:
        token_match = re.search(
            r'(?ms)^\s*exporter\s*=\s*\{\s*otlp-http\s*=\s*\{.*?x-codex-ingest-token"\s*=\s*"([^"]+)"',
            raw_text,
        )
        if token_match:
            headers = {"x-codex-ingest-token": token_match.group(1)}

    return {
        "environment": environment or "dev",
        "logs_endpoint": logs_endpoint or "",
        "headers": headers if isinstance(headers, dict) else {},
    }


def run_git(cwd: str, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    output = result.stdout.strip()
    return output or None


def sanitize_path(raw_path: str | None, *, redact_home_prefix: bool) -> str | None:
    if not raw_path:
        return None
    try:
        normalized = str(Path(raw_path).resolve())
    except OSError:
        normalized = raw_path
    if redact_home_prefix:
        home = str(Path.home())
        if normalized == home:
            return "$HOME"
        if normalized.startswith(home + os.sep):
            return "$HOME" + normalized[len(home):]
    return normalized


def normalize_remote_slug(remote_url: str | None) -> str | None:
    if not remote_url:
        return None
    cleaned = remote_url.strip()
    cleaned = re.sub(r"\.git$", "", cleaned)
    ssh_match = re.match(r"^[^@]+@[^:]+:(.+/.+)$", cleaned)
    if ssh_match:
        return ssh_match.group(1)
    https_match = re.match(r"^[a-z]+://[^/]+/(.+/.+)$", cleaned)
    if https_match:
        return https_match.group(1)
    if "/" in cleaned:
        return cleaned.split("/", 1)[-1]
    return cleaned


def summarize_chars(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (int, float, bool)):
        return len(str(value))
    if isinstance(value, list):
        return sum(summarize_chars(item) for item in value)
    if isinstance(value, dict):
        total = 0
        for key in ("content", "text", "message", "value"):
            if key in value:
                total += summarize_chars(value[key])
        if total > 0:
            return total
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return len(str(value))


def summarize_count(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, list):
        return len(value)
    return 1


def derive_repo_context(cwd: str, helper_config: dict) -> dict[str, object]:
    repo_root = run_git(cwd, "rev-parse", "--show-toplevel")
    is_git = repo_root is not None
    branch = run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD") if is_git else None
    remote_origin = run_git(cwd, "remote", "get-url", "origin") if is_git else None
    repo_root_sanitized = sanitize_path(
        repo_root,
        redact_home_prefix=helper_config["redact_home_prefix"],
    )
    return {
        "is_git": is_git,
        "repo_root": repo_root_sanitized if helper_config["include_repo_root"] else None,
        "repo_name": Path(repo_root).name if repo_root else None,
        "git_branch": branch if helper_config["include_git_branch"] else None,
        "git_remote_slug": (
            normalize_remote_slug(remote_origin)
            if helper_config["include_git_remote_slug"]
            else None
        ),
    }


def build_helper_event(payload: dict, helper_config: dict, codex_otel: dict) -> tuple[dict, dict[str, str]]:
    notification_type = str(payload.get("type", "unknown"))
    cwd = payload.get("cwd") or os.getcwd()
    if not isinstance(cwd, str):
        cwd = os.getcwd()

    cwd_sanitized = sanitize_path(
        cwd,
        redact_home_prefix=helper_config["redact_home_prefix"],
    )
    repo_context = derive_repo_context(cwd, helper_config)

    event_payload: dict[str, object] = {
        "helper_event_name": helper_config["event_name"],
        "notification_type": notification_type,
        "thread_id": payload.get("thread-id"),
        "turn_id": payload.get("turn-id"),
        "cwd": cwd_sanitized if not helper_config["include_raw_cwd"] else cwd,
        "is_git": repo_context["is_git"],
        "repo_root": repo_context["repo_root"],
        "repo_name": repo_context["repo_name"],
        "git_branch": repo_context["git_branch"],
        "git_remote_slug": repo_context["git_remote_slug"],
        "helper_version": HELPER_VERSION,
    }

    if helper_config["collect_host_name"]:
        event_payload["host_name"] = socket.gethostname()

    input_messages = payload.get("input-messages")
    if helper_config["collect_input_message_stats"]:
        event_payload["input_message_count"] = summarize_count(input_messages)
        event_payload["input_message_char_count"] = summarize_chars(input_messages)

    last_assistant_message = payload.get("last-assistant-message")
    if helper_config["collect_last_assistant_message_stats"]:
        event_payload["last_assistant_message_char_count"] = summarize_chars(last_assistant_message)

    body = json.dumps(event_payload, ensure_ascii=False, separators=(",", ":"))
    time_ns = str(now_ns())
    attributes = [
        attr("event.name", helper_config["event_name"]),
        attr("notification.type", notification_type),
        attr("helper.version", HELPER_VERSION),
        attr("service.name", DEFAULT_SERVICE_NAME),
        attr("deployment.environment", str(codex_otel["environment"])),
        attr("thread_id", str(event_payload.get("thread_id") or "")),
        attr("turn_id", str(event_payload.get("turn_id") or "")),
        attr("cwd", str(event_payload.get("cwd") or "")),
        attr("is_git", "true" if repo_context["is_git"] else "false"),
    ]

    for key in ("repo_root", "repo_name", "git_branch", "git_remote_slug", "host_name"):
        value = event_payload.get(key)
        if value:
            attributes.append(attr(key, str(value)))

    for key in (
        "input_message_count",
        "input_message_char_count",
        "last_assistant_message_char_count",
    ):
        value = event_payload.get(key)
        if value is not None:
            attributes.append(attr(key, str(value)))

    otlp_payload = {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        attr("service.name", DEFAULT_SERVICE_NAME),
                        attr("service.namespace", "codex-observability"),
                        attr("deployment.environment", str(codex_otel["environment"])),
                    ]
                },
                "scopeLogs": [
                    {
                        "scope": {
                            "name": DEFAULT_SCOPE_NAME,
                            "version": HELPER_VERSION,
                        },
                        "logRecords": [
                            {
                                "timeUnixNano": time_ns,
                                "observedTimeUnixNano": time_ns,
                                "severityNumber": 9,
                                "severityText": "INFO",
                                "body": {"stringValue": body},
                                "attributes": attributes,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    headers = {"Content-Type": "application/json"}
    for key, value in codex_otel["headers"].items():
        headers[str(key)] = str(value)
    return otlp_payload, headers


def send_json(url: str, payload: dict, headers: dict[str, str]) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status >= 300:
            body = response.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{url} returned {response.status}: {body}")


def read_payload_text(explicit_payload: str | None) -> str:
    if explicit_payload:
        return explicit_payload
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise ValueError("notify payload JSON이 필요합니다.")


def print_install_snippet(config_path: Path) -> None:
    helper_path = Path(__file__).resolve()
    print("notify = [")
    print('  "/usr/bin/env",')
    print('  "python3",')
    print(f'  "{helper_path}",')
    print('  "--config",')
    print(f'  "{config_path}",')
    print("]")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Codex local helper notify payload를 OTLP log로 보낸다."
    )
    parser.add_argument(
        "payload",
        nargs="?",
        help="Codex notify JSON payload. 생략 시 stdin에서 읽는다.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="helper 설정 파일 경로",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="OTLP 전송 없이 정규화된 payload만 stdout에 출력한다.",
    )
    parser.add_argument(
        "--print-install-snippet",
        action="store_true",
        help="~/.codex/config.toml에 넣을 notify 설정 snippet을 출력한다.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="전송 실패 시 non-zero로 종료한다.",
    )
    args = parser.parse_args()

    config_path = expand_path(args.config)
    if args.print_install_snippet:
        print_install_snippet(config_path)
        return 0

    try:
        helper_config = load_helper_config(config_path)
        codex_config_path = expand_path(str(helper_config["codex_config_path"]))
        codex_otel = load_codex_otel_config(codex_config_path)
        logs_endpoint = str(helper_config["logs_endpoint"] or codex_otel["logs_endpoint"])
        if not logs_endpoint:
            raise RuntimeError(
                "logs endpoint를 찾을 수 없습니다. helper config 또는 ~/.codex/config.toml의 [otel].exporter.otlp-http.endpoint를 확인하세요."
            )

        payload_text = read_payload_text(args.payload)
        payload = json.loads(payload_text)
        otlp_payload, headers = build_helper_event(payload, helper_config, codex_otel)
        if args.dry_run:
            print(json.dumps(otlp_payload, ensure_ascii=False, indent=2))
            return 0
        send_json(logs_endpoint, otlp_payload, headers)
        return 0
    except Exception as exc:  # pragma: no cover - fail-open by default
        print(f"[codex-local-helper] {exc}", file=sys.stderr)
        return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
