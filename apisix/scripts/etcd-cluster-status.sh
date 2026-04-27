#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/load-env.sh"

ENDPOINTS="http://etcd1:2379,http://etcd2:2379,http://etcd3:2379"

usage() {
  cat <<'EOF'
사용법:
  ./scripts/etcd-cluster-status.sh member-list
  ./scripts/etcd-cluster-status.sh endpoint-status
  ./scripts/etcd-cluster-status.sh endpoint-health
EOF
}

run_etcdctl() {
  (
    cd "${PROJECT_DIR}"
    docker compose exec etcd1 etcdctl --endpoints="${ENDPOINTS}" "$@"
  )
}

COMMAND="${1:-}"

case "${COMMAND}" in
  member-list)
    run_etcdctl member list
    ;;
  endpoint-status)
    run_etcdctl endpoint status --write-out=table
    ;;
  endpoint-health)
    run_etcdctl endpoint health --write-out=table
    ;;
  *)
    usage
    exit 1
    ;;
esac
