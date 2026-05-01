#!/bin/sh

set -eu

EXPORTER_PORT="${EXPORTER_PORT:-9107}"
EXPORTER_REFRESH_SECONDS="${EXPORTER_REFRESH_SECONDS:-60}"
EXPORTER_WEB_ROOT="${EXPORTER_WEB_ROOT:-/var/www}"
METRICS_FILE="${EXPORTER_WEB_ROOT}/metrics"

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGDATABASE="${PGDATABASE:-codex_observability}"
PGUSER="${PGUSER:-codex}"
PGPASSWORD="${PGPASSWORD:-codex}"
PGTZ="${PGTZ:-Asia/Seoul}"

TOOL_STATS_LOOKBACK_MINUTES="${OPS_TOOL_STATS_LOOKBACK_MINUTES:-30}"
API_STATS_LOOKBACK_MINUTES="${OPS_API_STATS_LOOKBACK_MINUTES:-30}"

ALERT_TEAM_BUDGET_WARNING_RATIO="${ALERT_TEAM_BUDGET_WARNING_RATIO:-0.70}"
ALERT_TEAM_BUDGET_CRITICAL_RATIO="${ALERT_TEAM_BUDGET_CRITICAL_RATIO:-0.90}"
ALERT_USER_DAILY_COST_USD="${ALERT_USER_DAILY_COST_USD:-25}"
ALERT_COMPANY_DAILY_COST_USD="${ALERT_COMPANY_DAILY_COST_USD:-250}"
ALERT_TOOL_FAILURE_RATE_RATIO="${ALERT_TOOL_FAILURE_RATE_RATIO:-0.10}"
ALERT_API_FAILURE_RATE_RATIO="${ALERT_API_FAILURE_RATE_RATIO:-0.05}"
ALERT_TOOL_P95_DURATION_MS="${ALERT_TOOL_P95_DURATION_MS:-5000}"
ALERT_DATA_GAP_SECONDS="${ALERT_DATA_GAP_SECONDS:-1800}"
ALERT_RETENTION_JOB_STALE_SECONDS="${ALERT_RETENTION_JOB_STALE_SECONDS:-129600}"
ALERT_LOKI_RETENTION_STALE_SECONDS="${ALERT_LOKI_RETENTION_STALE_SECONDS:-86400}"

LOKI_RETENTION_DAYS="${LOKI_RETENTION_DAYS:-14}"
PROMETHEUS_RETENTION_DAYS="${PROMETHEUS_RETENTION_DAYS:-180}"
TEMPO_RETENTION_DAYS="${TEMPO_RETENTION_DAYS:-7}"
POSTGRES_RAW_EVENT_RETENTION_DAYS="${POSTGRES_RAW_EVENT_RETENTION_DAYS:-30}"
POSTGRES_NORMALIZED_RETENTION_DAYS="${POSTGRES_NORMALIZED_RETENTION_DAYS:-365}"

LOKI_VOLUME_CAPACITY_BYTES="${LOKI_VOLUME_CAPACITY_BYTES:-2147483648}"
PROMETHEUS_VOLUME_CAPACITY_BYTES="${PROMETHEUS_VOLUME_CAPACITY_BYTES:-2147483648}"
TEMPO_VOLUME_CAPACITY_BYTES="${TEMPO_VOLUME_CAPACITY_BYTES:-2147483648}"
POSTGRES_VOLUME_CAPACITY_BYTES="${POSTGRES_VOLUME_CAPACITY_BYTES:-2147483648}"

psql_query() {
  PGPASSWORD="${PGPASSWORD}" PGTZ="${PGTZ}" psql \
    -h "${PGHOST}" \
    -p "${PGPORT}" \
    -U "${PGUSER}" \
    -d "${PGDATABASE}" \
    -At \
    -F '|' \
    -v ON_ERROR_STOP=1 \
    -c "$1"
}

escape_label() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

print_metric() {
  metric_name="$1"
  labels="$2"
  metric_value="$3"

  if [ -n "${labels}" ]; then
    printf '%s{%s} %s\n' "${metric_name}" "${labels}" "${metric_value}"
  else
    printf '%s %s\n' "${metric_name}" "${metric_value}"
  fi
}

status_code_from_name() {
  case "$1" in
    never) printf '0' ;;
    running) printf '1' ;;
    success) printf '2' ;;
    failure) printf '3' ;;
    *) printf '-1' ;;
  esac
}

success_value_from_status() {
  case "$1" in
    success) printf '1' ;;
    *) printf '0' ;;
  esac
}

safe_dir_size_bytes() {
  target_path="$1"
  if [ ! -d "${target_path}" ]; then
    printf '0'
    return
  fi

  du -sk "${target_path}" 2>/dev/null | awk '{print $1 * 1024}'
}

safe_ratio() {
  numerator="$1"
  denominator="$2"
  awk -v numerator="${numerator}" -v denominator="${denominator}" 'BEGIN { if (denominator > 0) { printf "%.6f", numerator / denominator } else { printf "0" } }'
}

emit_threshold_metrics() {
  print_metric "codex_alert_threshold" 'name="team_budget_warning_ratio",unit="ratio"' "${ALERT_TEAM_BUDGET_WARNING_RATIO}"
  print_metric "codex_alert_threshold" 'name="team_budget_critical_ratio",unit="ratio"' "${ALERT_TEAM_BUDGET_CRITICAL_RATIO}"
  print_metric "codex_alert_threshold" 'name="user_daily_cost_usd",unit="currencyUSD"' "${ALERT_USER_DAILY_COST_USD}"
  print_metric "codex_alert_threshold" 'name="company_daily_cost_usd",unit="currencyUSD"' "${ALERT_COMPANY_DAILY_COST_USD}"
  print_metric "codex_alert_threshold" 'name="tool_failure_rate_ratio",unit="ratio"' "${ALERT_TOOL_FAILURE_RATE_RATIO}"
  print_metric "codex_alert_threshold" 'name="api_failure_rate_ratio",unit="ratio"' "${ALERT_API_FAILURE_RATE_RATIO}"
  print_metric "codex_alert_threshold" 'name="tool_p95_duration_ms",unit="ms"' "${ALERT_TOOL_P95_DURATION_MS}"
  print_metric "codex_alert_threshold" 'name="data_gap_seconds",unit="s"' "${ALERT_DATA_GAP_SECONDS}"
  print_metric "codex_alert_threshold" 'name="retention_job_stale_seconds",unit="s"' "${ALERT_RETENTION_JOB_STALE_SECONDS}"
  print_metric "codex_alert_threshold" 'name="loki_retention_stale_seconds",unit="s"' "${ALERT_LOKI_RETENTION_STALE_SECONDS}"
}

emit_retention_policy_metrics() {
  print_metric "codex_retention_configured_days" 'store="loki"' "${LOKI_RETENTION_DAYS}"
  print_metric "codex_retention_configured_days" 'store="prometheus"' "${PROMETHEUS_RETENTION_DAYS}"
  print_metric "codex_retention_configured_days" 'store="tempo"' "${TEMPO_RETENTION_DAYS}"
  print_metric "codex_retention_configured_days" 'store="postgres_raw_event"' "${POSTGRES_RAW_EVENT_RETENTION_DAYS}"
  print_metric "codex_retention_configured_days" 'store="postgres_normalized"' "${POSTGRES_NORMALIZED_RETENTION_DAYS}"
}

emit_team_budget_metrics() {
  rows="$(psql_query "select team, currency, monthly_budget, current_month_cost, budget_usage_pct / 100.0, forecast_month_end_cost, remaining_budget from codex_team_budget_usage order by team;")" || return 1
  if [ -z "${rows}" ]; then
    return
  fi

  printf '%s\n' "${rows}" | while IFS='|' read -r team currency monthly_budget current_month_cost budget_usage_ratio forecast_month_end_cost remaining_budget
  do
    team_label="$(escape_label "${team}")"
    currency_label="$(escape_label "${currency}")"
    common_labels="team=\"${team_label}\",currency=\"${currency_label}\""
    print_metric "codex_team_budget_monthly_budget_usd" "${common_labels}" "${monthly_budget}"
    print_metric "codex_team_budget_current_month_cost_usd" "${common_labels}" "${current_month_cost}"
    print_metric "codex_team_budget_usage_ratio" "${common_labels}" "${budget_usage_ratio}"
    print_metric "codex_team_budget_forecast_month_end_cost_usd" "${common_labels}" "${forecast_month_end_cost}"
    print_metric "codex_team_budget_remaining_usd" "${common_labels}" "${remaining_budget}"
  done
}

emit_daily_cost_metrics() {
  company_cost="$(psql_query "select coalesce(sum(total_estimated_cost), 0) from codex_daily_cost_agg where usage_date = current_date;")" || return 1
  print_metric "codex_company_daily_estimated_cost_usd" "" "${company_cost}"

  rows="$(psql_query "select coalesce(team, '(unknown)'), coalesce(user_id, '(unknown)'), coalesce(sum(total_estimated_cost), 0) from codex_daily_cost_agg where usage_date = current_date group by 1, 2 order by 1, 2;")" || return 1
  if [ -z "${rows}" ]; then
    return
  fi

  printf '%s\n' "${rows}" | while IFS='|' read -r team user_id total_cost
  do
    team_label="$(escape_label "${team}")"
    user_label="$(escape_label "${user_id}")"
    print_metric "codex_user_daily_estimated_cost_usd" "team=\"${team_label}\",user_id=\"${user_label}\"" "${total_cost}"
  done
}

emit_recent_tool_metrics() {
  rows="$(psql_query "with recent as ( select coalesce(tool_name, '(unknown)') as tool_name, tool_success, tool_duration_ms from codex_tool_results_dashboard where event_time >= now() - make_interval(mins => ${TOOL_STATS_LOOKBACK_MINUTES}) ) select tool_name, count(*)::bigint as total_calls, count(*) filter (where tool_success is not null)::bigint as evaluated_calls, count(*) filter (where tool_success = false)::bigint as failed_calls, round(coalesce((count(*) filter (where tool_success = false))::numeric / nullif(count(*) filter (where tool_success is not null), 0), 0), 6) as failure_rate_ratio, round(coalesce((percentile_cont(0.95) within group (order by tool_duration_ms))::numeric, 0), 3) as p95_duration_ms from recent group by tool_name order by tool_name;")" || return 1
  if [ -z "${rows}" ]; then
    return
  fi

  printf '%s\n' "${rows}" | while IFS='|' read -r tool_name total_calls evaluated_calls failed_calls failure_rate_ratio p95_duration_ms
  do
    tool_label="$(escape_label "${tool_name}")"
    labels="tool_name=\"${tool_label}\""
    print_metric "codex_tool_recent_total_calls" "${labels}" "${total_calls}"
    print_metric "codex_tool_recent_evaluated_calls" "${labels}" "${evaluated_calls}"
    print_metric "codex_tool_recent_failed_calls" "${labels}" "${failed_calls}"
    print_metric "codex_tool_recent_failure_rate_ratio" "${labels}" "${failure_rate_ratio}"
    print_metric "codex_tool_recent_p95_duration_ms" "${labels}" "${p95_duration_ms}"
  done
}

emit_recent_api_request_metrics() {
  rows="$(psql_query "with recent as ( select coalesce(request_type, '(unknown)') as request_type, request_success, request_duration_ms from codex_api_request_events_dashboard where event_time >= now() - make_interval(mins => ${API_STATS_LOOKBACK_MINUTES}) ) select request_type, count(*)::bigint as total_calls, count(*) filter (where request_success is not null)::bigint as evaluated_calls, count(*) filter (where request_success = false)::bigint as failed_calls, round(coalesce((count(*) filter (where request_success = false))::numeric / nullif(count(*) filter (where request_success is not null), 0), 0), 6) as failure_rate_ratio, round(coalesce((percentile_cont(0.95) within group (order by request_duration_ms))::numeric, 0), 3) as p95_duration_ms from recent group by request_type order by request_type;")" || return 1
  if [ -z "${rows}" ]; then
    return
  fi

  printf '%s\n' "${rows}" | while IFS='|' read -r request_type total_calls evaluated_calls failed_calls failure_rate_ratio p95_duration_ms
  do
    request_label="$(escape_label "${request_type}")"
    labels="request_type=\"${request_label}\""
    print_metric "codex_api_recent_total_calls" "${labels}" "${total_calls}"
    print_metric "codex_api_recent_evaluated_calls" "${labels}" "${evaluated_calls}"
    print_metric "codex_api_recent_failed_calls" "${labels}" "${failed_calls}"
    print_metric "codex_api_recent_failure_rate_ratio" "${labels}" "${failure_rate_ratio}"
    print_metric "codex_api_recent_p95_duration_ms" "${labels}" "${p95_duration_ms}"
  done
}

emit_freshness_metrics() {
  usage_row="$(psql_query "select coalesce(extract(epoch from max(event_time)), 0), coalesce(extract(epoch from now() - max(event_time)), -1), count(*) filter (where event_time >= now() - interval '24 hours') from codex_usage_events;")" || return 1
  IFS='|' read -r usage_last_timestamp usage_age_seconds usage_last_24h_total <<EOF
${usage_row}
EOF
  print_metric "codex_usage_last_event_timestamp_seconds" "" "${usage_last_timestamp}"
  print_metric "codex_usage_last_event_age_seconds" "" "${usage_age_seconds}"
  print_metric "codex_usage_events_last_24h_total" "" "${usage_last_24h_total}"

  tool_row="$(psql_query "select coalesce(extract(epoch from max(event_time)), 0), coalesce(extract(epoch from now() - max(event_time)), -1), count(*) filter (where event_time >= now() - interval '24 hours') from codex_tool_results_dashboard;")" || return 1
  IFS='|' read -r tool_last_timestamp tool_age_seconds tool_last_24h_total <<EOF
${tool_row}
EOF
  print_metric "codex_tool_last_event_timestamp_seconds" "" "${tool_last_timestamp}"
  print_metric "codex_tool_last_event_age_seconds" "" "${tool_age_seconds}"
  print_metric "codex_tool_results_last_24h_total" "" "${tool_last_24h_total}"

  api_row="$(psql_query "select coalesce(extract(epoch from max(event_time)), 0), coalesce(extract(epoch from now() - max(event_time)), -1), count(*) filter (where event_time >= now() - interval '24 hours') from codex_api_request_events;")" || return 1
  IFS='|' read -r api_last_timestamp api_age_seconds api_last_24h_total <<EOF
${api_row}
EOF
  print_metric "codex_api_last_event_timestamp_seconds" "" "${api_last_timestamp}"
  print_metric "codex_api_last_event_age_seconds" "" "${api_age_seconds}"
  print_metric "codex_api_requests_last_24h_total" "" "${api_last_24h_total}"
}

emit_job_status_metrics() {
  rows="$(psql_query "select job_name, job_group, last_status, coalesce(extract(epoch from last_started_at), 0), coalesce(extract(epoch from last_finished_at), 0), coalesce(extract(epoch from last_success_at), 0), coalesce(extract(epoch from last_failure_at), 0), coalesce(last_duration_seconds, 0) from codex_job_run_status order by job_group, job_name;")" || return 1
  if [ -z "${rows}" ]; then
    return
  fi

  printf '%s\n' "${rows}" | while IFS='|' read -r job_name job_group last_status last_started_at last_finished_at last_success_at last_failure_at last_duration_seconds
  do
    job_label="$(escape_label "${job_name}")"
    group_label="$(escape_label "${job_group}")"
    labels="job_name=\"${job_label}\",job_group=\"${group_label}\""
    print_metric "codex_job_last_status_code" "${labels}" "$(status_code_from_name "${last_status}")"
    print_metric "codex_job_last_run_success" "${labels}" "$(success_value_from_status "${last_status}")"
    print_metric "codex_job_last_started_timestamp_seconds" "${labels}" "${last_started_at}"
    print_metric "codex_job_last_finished_timestamp_seconds" "${labels}" "${last_finished_at}"
    print_metric "codex_job_last_success_timestamp_seconds" "${labels}" "${last_success_at}"
    print_metric "codex_job_last_failure_timestamp_seconds" "${labels}" "${last_failure_at}"
    print_metric "codex_job_last_duration_seconds" "${labels}" "${last_duration_seconds}"
  done
}

emit_store_metrics() {
  emit_store_metric "loki" "/data/loki" "${LOKI_VOLUME_CAPACITY_BYTES}"
  emit_store_metric "prometheus" "/data/prometheus" "${PROMETHEUS_VOLUME_CAPACITY_BYTES}"
  emit_store_metric "tempo" "/data/tempo" "${TEMPO_VOLUME_CAPACITY_BYTES}"
  emit_store_metric "postgres" "/data/postgres" "${POSTGRES_VOLUME_CAPACITY_BYTES}"
}

emit_store_metric() {
  store_name="$1"
  store_path="$2"
  capacity_bytes="$3"
  used_bytes="$(safe_dir_size_bytes "${store_path}")"
  usage_ratio="$(safe_ratio "${used_bytes}" "${capacity_bytes}")"
  print_metric "codex_store_used_bytes" "store=\"${store_name}\"" "${used_bytes}"
  print_metric "codex_store_capacity_bytes" "store=\"${store_name}\"" "${capacity_bytes}"
  print_metric "codex_store_usage_ratio" "store=\"${store_name}\"" "${usage_ratio}"
}

render_metrics() {
  now_seconds="$(date +%s)"
  print_metric "codex_ops_exporter_last_render_timestamp_seconds" "" "${now_seconds}"
  print_metric "codex_ops_exporter_render_success" "" "1"
  emit_threshold_metrics
  emit_retention_policy_metrics
  emit_team_budget_metrics
  emit_daily_cost_metrics
  emit_recent_tool_metrics
  emit_recent_api_request_metrics
  emit_freshness_metrics
  emit_job_status_metrics
  emit_store_metrics
}

write_failure_metrics() {
  tmp_file="$1"
  now_seconds="$(date +%s)"
  cat > "${tmp_file}" <<EOF
codex_ops_exporter_last_render_timestamp_seconds ${now_seconds}
codex_ops_exporter_render_success 0
EOF
}

write_metrics_file() {
  mkdir -p "${EXPORTER_WEB_ROOT}"
  tmp_file="$(mktemp)"

  if render_metrics > "${tmp_file}"; then
    mv "${tmp_file}" "${METRICS_FILE}"
    return 0
  fi

  write_failure_metrics "${tmp_file}"
  mv "${tmp_file}" "${METRICS_FILE}"
  return 1
}

run_updater_loop() {
  while true
  do
    sleep "${EXPORTER_REFRESH_SECONDS}"
    write_metrics_file || true
  done
}

serve_http_forever() {
  mkdir -p "${EXPORTER_WEB_ROOT}"
  export METRICS_FILE
  exec python3 /usr/local/bin/task6_ops_http_server.py
}

main() {
  write_metrics_file || true
  run_updater_loop &
  serve_http_forever
}

main "$@"
