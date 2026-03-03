#!/bin/sh
set -eu

mode="$1"
seed_dir="$2"
runtime_dir="$3"
config_name="$4"

seed_path="${seed_dir}/${config_name}"
runtime_path="${runtime_dir}/${config_name}"

mkdir -p "$runtime_dir"

if [ ! -f "$runtime_path" ]; then
  cp "$seed_path" "$runtime_path"
fi

if [ "$mode" = "redis" ]; then
  exec redis-server "$runtime_path"
fi

if [ "$mode" = "sentinel" ]; then
  exec redis-server "$runtime_path" --sentinel
fi

echo "unsupported mode: $mode" >&2
exit 1
