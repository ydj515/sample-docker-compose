#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="${1:-$HOME/.codex/local-helper}"
TARGET_SCRIPT="$TARGET_DIR/codex-local-helper.py"
TARGET_CONFIG="${2:-$HOME/.codex/codex-local-helper.toml}"

mkdir -p "$TARGET_DIR"
mkdir -p "$(dirname "$TARGET_CONFIG")"

cp "$ROOT_DIR/scripts/codex_local_helper.py" "$TARGET_SCRIPT"
chmod +x "$TARGET_SCRIPT"

if [ ! -f "$TARGET_CONFIG" ]; then
  cp "$ROOT_DIR/examples/codex.local-helper.toml.example" "$TARGET_CONFIG"
fi

echo "Codex local helper 설치 완료"
echo "- helper script: $TARGET_SCRIPT"
echo "- helper config: $TARGET_CONFIG"
echo
echo "아래 snippet을 ~/.codex/config.toml에 추가하세요:"
python3 "$TARGET_SCRIPT" --config "$TARGET_CONFIG" --print-install-snippet
