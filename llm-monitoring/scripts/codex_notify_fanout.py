#!/usr/bin/env python3
"""Codex notify fan-out helper.

한 번의 Codex notify payload를 여러 notifier로 안전하게 전달한다.
기본 동작은 fail-open이며, 각 대상 명령은 payload JSON을 마지막 argv로 받는다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
    HAS_TOMLLIB = True
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]
    HAS_TOMLLIB = False


DEFAULT_CONFIG_PATH = "~/.codex/codex-notify-fanout.json"
DEFAULT_CODEX_CONFIG_PATH = "~/.codex/config.toml"


def expand_path(raw: str) -> Path:
    return Path(os.path.expanduser(raw)).resolve()


def read_payload_text(explicit_payload: str | None) -> str:
    if explicit_payload:
        return explicit_payload
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise ValueError("notify payload JSON이 필요합니다.")


def load_json_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_notify_from_codex_config(path: Path) -> list[str]:
    if not path.exists():
        return []

    raw_text = path.read_text(encoding="utf-8")
    if HAS_TOMLLIB:
        try:
            data = tomllib.loads(raw_text)
            notify = data.get("notify", [])
            if isinstance(notify, list):
                return [str(item) for item in notify]
        except tomllib.TOMLDecodeError:
            pass

    match = re.search(r"(?ms)^\s*notify\s*=\s*\[(.*?)\]", raw_text)
    if not match:
        return []

    values = re.findall(r'"((?:\\.|[^"])*)"', match.group(1))
    return [bytes(value, "utf-8").decode("unicode_escape") for value in values]


def should_preserve_notify(command: list[str], *, fanout_script: Path, helper_script: Path) -> bool:
    if not command:
        return False
    resolved_targets = {str(fanout_script), str(helper_script)}
    for part in command:
        expanded = str(expand_path(part)) if part.startswith("~") or part.startswith("/") else part
        if expanded in resolved_targets:
            return False
    return True


def build_fanout_config(
    *,
    fanout_script: Path,
    helper_script: Path,
    helper_config_path: Path,
    codex_config_path: Path,
) -> dict:
    existing_notify = load_notify_from_codex_config(codex_config_path)
    commands: list[dict[str, object]] = []

    if should_preserve_notify(
        existing_notify,
        fanout_script=fanout_script,
        helper_script=helper_script,
    ):
        commands.append(
            {
                "name": "existing_notify",
                "argv": existing_notify,
                "payload_mode": "argv",
                "required": False,
                "enabled": True,
            }
        )

    commands.append(
        {
            "name": "local_helper",
            "argv": [
                "/usr/bin/env",
                "python3",
                str(helper_script),
                "--config",
                str(helper_config_path),
            ],
            "payload_mode": "argv",
            "required": False,
            "enabled": True,
        }
    )
    return {"commands": commands}


def write_fanout_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def print_install_snippet(config_path: Path, *, fanout_script: Path | None = None) -> None:
    script_path = fanout_script or Path(__file__).resolve()
    print("notify = [")
    print('  "/usr/bin/env",')
    print('  "python3",')
    print(f'  "{script_path}",')
    print('  "--config",')
    print(f'  "{config_path}",')
    print("]")


def run_command(command: dict[str, object], payload_text: str) -> tuple[bool, str]:
    argv = command.get("argv", [])
    name = str(command.get("name", "unnamed"))
    payload_mode = str(command.get("payload_mode", "argv"))

    if not isinstance(argv, list) or not argv:
        return False, f"[{name}] argv가 비어 있습니다."

    normalized_argv = [str(part) for part in argv]
    try:
        if payload_mode == "stdin":
            result = subprocess.run(
                normalized_argv,
                input=payload_text,
                text=True,
                capture_output=True,
                check=False,
            )
        else:
            result = subprocess.run(
                [*normalized_argv, payload_text],
                text=True,
                capture_output=True,
                check=False,
            )
    except FileNotFoundError as exc:
        return False, f"[{name}] 실행 파일을 찾을 수 없습니다: {exc}"
    except OSError as exc:
        return False, f"[{name}] 실행 실패: {exc}"

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        return False, f"[{name}] {detail}"

    if result.stderr.strip():
        return True, f"[{name}] {result.stderr.strip()}"
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex notify payload를 여러 notifier로 fan-out 한다.")
    parser.add_argument("payload", nargs="?", help="Codex notify JSON payload. 생략 시 stdin에서 읽는다.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="fan-out JSON 설정 파일 경로")
    parser.add_argument(
        "--print-install-snippet",
        action="store_true",
        help="~/.codex/config.toml에 넣을 notify 설정 snippet을 출력한다.",
    )
    parser.add_argument(
        "--bootstrap-config",
        action="store_true",
        help="현재 Codex notify를 유지한 fan-out 설정 파일을 생성한다.",
    )
    parser.add_argument(
        "--helper-script",
        default="",
        help="bootstrap 시 local helper script 경로",
    )
    parser.add_argument(
        "--helper-config",
        default="",
        help="bootstrap 시 local helper config 경로",
    )
    parser.add_argument(
        "--codex-config",
        default=DEFAULT_CODEX_CONFIG_PATH,
        help="현재 Codex config.toml 경로",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fan-out 대상 중 하나라도 실패하면 non-zero로 종료한다.",
    )
    args = parser.parse_args()

    config_path = expand_path(args.config)
    fanout_script = Path(__file__).resolve()

    if args.print_install_snippet:
        print_install_snippet(config_path, fanout_script=fanout_script)
        return 0

    if args.bootstrap_config:
        if not args.helper_script or not args.helper_config:
            raise SystemExit("--bootstrap-config 사용 시 --helper-script, --helper-config가 필요합니다.")
        helper_script = expand_path(args.helper_script)
        helper_config = expand_path(args.helper_config)
        codex_config = expand_path(args.codex_config)
        config = build_fanout_config(
            fanout_script=fanout_script,
            helper_script=helper_script,
            helper_config_path=helper_config,
            codex_config_path=codex_config,
        )
        write_fanout_config(config_path, config)
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0

    try:
        payload_text = read_payload_text(args.payload)
        payload = json.loads(payload_text)
        payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        config = load_json_config(config_path)
        commands = config.get("commands", [])
        if not isinstance(commands, list) or not commands:
            raise RuntimeError("fan-out 대상 command가 없습니다.")

        has_error = False
        for command in commands:
            if not isinstance(command, dict):
                continue
            if not bool(command.get("enabled", True)):
                continue
            ok, message = run_command(command, payload_text)
            if message:
                print(f"[codex-notify-fanout] {message}", file=sys.stderr)
            if not ok:
                has_error = True
                if bool(command.get("required", False)):
                    return 1

        return 1 if has_error and args.strict else 0
    except Exception as exc:  # pragma: no cover - fail-open by default
        print(f"[codex-notify-fanout] {exc}", file=sys.stderr)
        return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
