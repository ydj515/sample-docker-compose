#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
ENV_FILE="${ENV_FILE:-${PROJECT_DIR}/.env}"

if [ ! -f "${ENV_FILE}" ]; then
  echo "[ERROR] .env 파일을 찾을 수 없습니다: ${ENV_FILE}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a
