#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="${1:-$HOME/.codex/local-helper}"
TARGET_SCRIPT="$TARGET_DIR/codex-local-helper.py"
TARGET_CONFIG="${2:-$HOME/.codex/codex-local-helper.toml}"
FANOUT_SCRIPT="$TARGET_DIR/codex-notify-fanout.py"
FANOUT_CONFIG="${3:-$HOME/.codex/codex-notify-fanout.json}"
CODEX_CONFIG="${4:-$HOME/.codex/config.toml}"

mkdir -p "$TARGET_DIR"
mkdir -p "$(dirname "$TARGET_CONFIG")"
mkdir -p "$(dirname "$FANOUT_CONFIG")"

cp "$ROOT_DIR/scripts/codex_local_helper.py" "$TARGET_SCRIPT"
cp "$ROOT_DIR/scripts/codex_notify_fanout.py" "$FANOUT_SCRIPT"
chmod +x "$TARGET_SCRIPT"
chmod +x "$FANOUT_SCRIPT"

if [ ! -f "$TARGET_CONFIG" ]; then
  cp "$ROOT_DIR/examples/codex.local-helper.toml.example" "$TARGET_CONFIG"
fi

python3 "$FANOUT_SCRIPT" \
  --config "$FANOUT_CONFIG" \
  --bootstrap-config \
  --helper-script "$TARGET_SCRIPT" \
  --helper-config "$TARGET_CONFIG" \
  --codex-config "$CODEX_CONFIG" >/dev/null

echo "Codex local helper 설치 완료"
echo "- helper script: $TARGET_SCRIPT"
echo "- helper config: $TARGET_CONFIG"
echo "- notify fan-out script: $FANOUT_SCRIPT"
echo "- notify fan-out config: $FANOUT_CONFIG"
echo
echo "아래 snippet을 ~/.codex/config.toml의 top-level notify = [...] 로 설정하세요:"
python3 "$FANOUT_SCRIPT" --config "$FANOUT_CONFIG" --print-install-snippet
