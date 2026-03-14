#!/bin/bash

set -euo pipefail

ES_URL="${ELASTICSEARCH_URL:-http://es-ingest01:9200}"

wait_for_cluster() {
  echo "Waiting for Elasticsearch cluster at ${ES_URL}..."

  until curl -sS -u "elastic:${ELASTIC_PASSWORD}" "${ES_URL}/_cluster/health?wait_for_status=yellow&timeout=10s" >/dev/null; do
    sleep 5
  done
}

call_api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"

  if [ -n "${data}" ]; then
    curl -sS -u "elastic:${ELASTIC_PASSWORD}" \
      -X "${method}" \
      -H "Content-Type: application/json" \
      "${ES_URL}${path}" \
      -d "${data}" >/dev/null
  else
    curl -sS -u "elastic:${ELASTIC_PASSWORD}" \
      -X "${method}" \
      "${ES_URL}${path}" >/dev/null
  fi
}

wait_for_cluster

echo "Updating kibana_system password..."
call_api "POST" "/_security/user/kibana_system/_password" "{\"password\":\"${KIBANA_SYSTEM_PASSWORD}\"}"

echo "Creating logstash role and user..."
call_api "PUT" "/_security/role/logstash_writer" "{
  \"cluster\": [\"monitor\", \"manage_index_templates\"],
  \"indices\": [
    {
      \"names\": [\"${LOGSTASH_INDEX_PREFIX}-*\"],
      \"privileges\": [\"view_index_metadata\", \"create_doc\", \"create_index\", \"auto_configure\", \"write\"]
    }
  ]
}"
call_api "POST" "/_security/user/logstash_internal" "{
  \"password\": \"${LOGSTASH_INTERNAL_PASSWORD}\",
  \"roles\": [\"logstash_writer\"],
  \"full_name\": \"Internal Logstash Writer\"
}"

echo "Creating metricbeat user..."
call_api "POST" "/_security/user/metricbeat_internal" "{
  \"password\": \"${METRICBEAT_INTERNAL_PASSWORD}\",
  \"roles\": [\"remote_monitoring_agent\", \"remote_monitoring_collector\"],
  \"full_name\": \"Internal Metricbeat User\"
}"

echo "Creating grafana role and user..."
call_api "PUT" "/_security/role/grafana_reader" "{
  \"cluster\": [\"monitor\"],
  \"indices\": [
    {
      \"names\": [\"${GRAFANA_LOG_INDEX_PATTERN}\", \"${GRAFANA_METRIC_INDEX_PATTERN}\", \".monitoring-*\"],
      \"privileges\": [\"read\", \"view_index_metadata\"]
    }
  ]
}"
call_api "POST" "/_security/user/grafana_internal" "{
  \"password\": \"${GRAFANA_INTERNAL_PASSWORD}\",
  \"roles\": [\"grafana_reader\"],
  \"full_name\": \"Internal Grafana Reader\"
}"

echo "User bootstrap completed."
