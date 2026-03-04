#!/bin/sh
set -eu

seed_dir="$1"
runtime_dir="$2"
config_name="$3"

seed_path="${seed_dir}/${config_name}"
runtime_path="${runtime_dir}/${config_name}"

mkdir -p "$runtime_dir"

if [ ! -f "$runtime_path" ]; then
  cp "$seed_path" "$runtime_path"
fi

exec redis-server "$runtime_path"
