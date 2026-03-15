#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/load-env.sh"

APISIX_ADMIN_BASE_URL="${APISIX_ADMIN_BASE_URL:-http://127.0.0.1:${APISIX2_ADMIN_PORT}}"
UPSTREAM_ID="${APISIX_SAMPLE_UPSTREAM_ID}"
ROUTE_ID="${APISIX_SAMPLE_ROUTE_ID}"

usage() {
  cat <<'EOF'
사용법:
  ./scripts/apisix-admin-sample.sh put-upstream
  ./scripts/apisix-admin-sample.sh put-route
  ./scripts/apisix-admin-sample.sh put-all
  ./scripts/apisix-admin-sample.sh get-routes
  ./scripts/apisix-admin-sample.sh get-route
  ./scripts/apisix-admin-sample.sh get-upstreams
  ./scripts/apisix-admin-sample.sh delete-route
  ./scripts/apisix-admin-sample.sh delete-upstream
  ./scripts/apisix-admin-sample.sh show-env
EOF
}

methods_json() {
  OLD_IFS=$IFS
  IFS=','
  set -- ${APISIX_SAMPLE_METHODS}
  IFS=$OLD_IFS

  METHODS_JSON=""
  for METHOD in "$@"; do
    if [ -n "${METHODS_JSON}" ]; then
      METHODS_JSON="${METHODS_JSON}, "
    fi
    METHODS_JSON="${METHODS_JSON}\"${METHOD}\""
  done

  printf '[%s]' "${METHODS_JSON}"
}

request() {
  METHOD=$1
  PATH_SUFFIX=$2
  shift 2

  curl -sS -i -X "${METHOD}" \
    "${APISIX_ADMIN_BASE_URL}${PATH_SUFFIX}" \
    -H "X-API-KEY: ${APISIX_ADMIN_KEY}" \
    -H "Content-Type: application/json" \
    "$@"
}

put_upstream() {
  request PUT "/apisix/admin/upstreams/${UPSTREAM_ID}" --data-binary @- <<EOF
{
  "id": "${UPSTREAM_ID}",
  "type": "roundrobin",
  "nodes": {
    "${APISIX_SAMPLE_UPSTREAM_HOST}:${APISIX_SAMPLE_UPSTREAM_PORT}": 1
  }
}
EOF
}

put_route() {
  METHODS_JSON=$(methods_json)

  request PUT "/apisix/admin/routes/${ROUTE_ID}" --data-binary @- <<EOF
{
  "id": "${ROUTE_ID}",
  "name": "sample-route-${ROUTE_ID}",
  "uri": "${APISIX_SAMPLE_ROUTE_URI}",
  "methods": ${METHODS_JSON},
  "upstream_id": "${UPSTREAM_ID}",
  "plugins": {
    "prometheus": {},
    "active_health_control": {
      "health_check_enabled": true,
      "admin_api_url": "${APISIX_CLUSTER_ADMIN_API_URL}",
      "admin_api_token": "${APISIX_ADMIN_KEY}",
      "health_check_path": "${APISIX_SAMPLE_HEALTH_CHECK_URL}",
      "expected_status": ${APISIX_SAMPLE_HEALTH_EXPECTED_STATUS},
      "interval": ${APISIX_HEALTH_CHECK_INTERVAL}
    },
    "limit-req": {
      "rate": ${APISIX_SAMPLE_LIMIT_REQ_RATE},
      "burst": ${APISIX_SAMPLE_LIMIT_REQ_BURST},
      "key": "route_id",
      "policy": "redis",
      "redis_host": "redis",
      "redis_port": 6379,
      "redis_timeout": 1000,
      "rejected_code": 429
    },
    "ext-plugin-pre-req": {
      "conf": [
        {
          "name": "${APISIX_SAMPLE_EXT_PLUGIN_FILTER_NAME}",
          "value": ""
        }
      ]
    }
  }
}
EOF
}

get_routes() {
  request GET "/apisix/admin/routes"
}

get_route() {
  request GET "/apisix/admin/routes/${ROUTE_ID}"
}

get_upstreams() {
  request GET "/apisix/admin/upstreams"
}

delete_route() {
  request DELETE "/apisix/admin/routes/${ROUTE_ID}"
}

delete_upstream() {
  request DELETE "/apisix/admin/upstreams/${UPSTREAM_ID}"
}

show_env() {
  cat <<EOF
APISIX_ADMIN_BASE_URL=${APISIX_ADMIN_BASE_URL}
APISIX_CLUSTER_ADMIN_API_URL=${APISIX_CLUSTER_ADMIN_API_URL}
APISIX_SAMPLE_UPSTREAM_ID=${UPSTREAM_ID}
APISIX_SAMPLE_ROUTE_ID=${ROUTE_ID}
APISIX_SAMPLE_ROUTE_URI=${APISIX_SAMPLE_ROUTE_URI}
APISIX_SAMPLE_UPSTREAM_HOST=${APISIX_SAMPLE_UPSTREAM_HOST}
APISIX_SAMPLE_UPSTREAM_PORT=${APISIX_SAMPLE_UPSTREAM_PORT}
APISIX_SAMPLE_METHODS=${APISIX_SAMPLE_METHODS}
APISIX_SAMPLE_HEALTH_CHECK_URL=${APISIX_SAMPLE_HEALTH_CHECK_URL}
EOF
}

COMMAND="${1:-}"

case "${COMMAND}" in
  put-upstream)
    put_upstream
    ;;
  put-route)
    put_route
    ;;
  put-all)
    put_upstream
    put_route
    ;;
  get-routes)
    get_routes
    ;;
  get-route)
    get_route
    ;;
  get-upstreams)
    get_upstreams
    ;;
  delete-route)
    delete_route
    ;;
  delete-upstream)
    delete_upstream
    ;;
  show-env)
    show_env
    ;;
  *)
    usage
    exit 1
    ;;
esac
