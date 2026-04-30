.PHONY: up down config sample \
  task3-schema task3-normalize task3-sample-mixed task3-verify \
  task4-schema task4-normalize task4-sample-mixed task4-verify \
  task5-schema task5-cost-compute task5-sample-mixed task5-verify \
  task6-schema task6-api-schema task6-api-normalize task6-verify \
  task7-schema task7-normalize task7-verify \
  task8-schema task8-normalize task8-helper-sample task8-sample-mixed task8-verify \
  task9-schema task9-verify \
  fn-call-schema fn-call-normalize fn-call-sample fn-call-verify \
  enrich-import-csv enrich-backfill enrich-report \
  cost-purge-raw cost-purge-old cost-recompute

up:
	docker compose up -d

down:
	docker compose down

config:
	docker compose config

sample:
	python3 scripts/send_sample_otel.py

task3-schema:
	docker exec -i llm-monitoring-postgres-1 psql -U codex -d codex_observability -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/001-task3-schema.sql

task3-normalize:
	python3 scripts/normalize_usage_events.py

task3-sample-mixed:
	python3 scripts/send_sample_otel.py
	python3 scripts/send_sample_otel.py --team backend --user-id sample-second@example.com --model gpt-5.4 --repository /workspace/backend-api --project llm-monitoring --session-id session-task3-missing --conversation-id conv-task3-missing --input-tokens 900 --output-tokens 240 --total-tokens 1140 --omit-cached-input-tokens --omit-reasoning-tokens

task3-verify:
	$(MAKE) task3-schema
	$(MAKE) task3-sample-mixed
	$(MAKE) task3-normalize

task4-schema:
	docker exec -i llm-monitoring-postgres-1 psql -U codex -d codex_observability -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/002-task4-schema.sql

task4-normalize:
	python3 scripts/normalize_tool_events.py

task4-sample-mixed:
	python3 scripts/send_sample_otel.py --response-id resp-task4-web-1 --session-id session-task4-web-1 --conversation-id conv-task4-web-1 --tool web.search --tool-call-id toolcall-web-1 --tool-duration-ms 180 --tool-output-size 6400
	python3 scripts/send_sample_otel.py --response-id resp-task4-web-2 --session-id session-task4-web-2 --conversation-id conv-task4-web-2 --tool web.search --tool-call-id toolcall-web-2 --tool-duration-ms 320 --tool-output-size 7200
	python3 scripts/send_sample_otel.py --response-id resp-task4-web-3 --session-id session-task4-web-3 --conversation-id conv-task4-web-3 --tool web.search --tool-call-id toolcall-web-3 --tool-duration-ms 1100 --tool-output-size 0 --tool-failure --tool-error-code TOOL_TIMEOUT --tool-error-message "web search timed out"
	python3 scripts/send_sample_otel.py --team backend --user-id sample-second@example.com --repository /workspace/backend-api --response-id resp-task4-shell-1 --session-id session-task4-shell-1 --conversation-id conv-task4-shell-1 --tool shell.exec --tool-call-id toolcall-shell-1 --tool-duration-ms 900 --tool-output-size 2048

task4-verify:
	$(MAKE) task4-schema
	$(MAKE) task4-sample-mixed
	$(MAKE) task4-normalize

# ── TASK-5: Cost 계산 및 정산용 데이터 모델 ─────────────────
task5-schema:
	docker exec -i llm-monitoring-postgres-1 psql -U codex -d codex_observability -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/004-cost-schema.sql

task5-cost-compute:
	python3 scripts/calculate_costs.py compute-daily

task5-sample-mixed:
	python3 scripts/send_sample_otel.py --response-id resp-task5-p1 --session-id session-task5-p1 --conversation-id conv-task5-p1 --tool shell.exec --tool-call-id toolcall-task5-p1 --input-tokens 2400 --output-tokens 680 --cached-input-tokens 800 --reasoning-tokens 120 --total-tokens 3080 --tool-duration-ms 310 --tool-output-size 2048
	python3 scripts/send_sample_otel.py --team backend --user-id sample-second@example.com --model gpt-5.4 --repository /workspace/backend-api --response-id resp-task5-p2 --session-id session-task5-p2 --conversation-id conv-task5-p2 --tool web.search --tool-call-id toolcall-task5-p2 --input-tokens 1800 --output-tokens 450 --total-tokens 2250 --omit-cached-input-tokens --omit-reasoning-tokens --tool-duration-ms 540 --tool-output-size 6144

task5-verify:
	$(MAKE) task5-schema
	$(MAKE) task5-sample-mixed
	$(MAKE) task3-normalize
	# 샘플을 오늘 주입했으므로 오늘 날짜로 명시해야 집계가 잡힌다
	python3 scripts/calculate_costs.py compute-daily --date $$(date +%Y-%m-%d)

# ── TASK-6: 운영 안정화 및 알림 ─────────────────────────────
task6-schema:
	docker exec -i llm-monitoring-postgres-1 psql -U codex -d codex_observability -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/005-ops-schema.sql

task6-api-schema:
	docker exec -i llm-monitoring-postgres-1 psql -U codex -d codex_observability -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/006-api-request-schema.sql

task6-api-normalize:
	python3 scripts/normalize_api_request_events.py

task6-verify:
	$(MAKE) task6-schema
	$(MAKE) task6-api-schema
	python3 scripts/calculate_costs.py compute-daily --date $$(date +%Y-%m-%d)
	python3 scripts/calculate_costs.py purge-raw-events --older-than-days 30
	python3 scripts/calculate_costs.py drop-old-rows --older-than-days 365

# ── TASK-7: Trace 기반 병목 분석 ────────────────────────────
task7-schema:
	docker exec -i llm-monitoring-postgres-1 psql -U codex -d codex_observability -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/010-trace-schema.sql

task7-normalize:
	python3 scripts/normalize_trace_spans.py

task7-verify:
	$(MAKE) task7-schema
	$(MAKE) task3-normalize
	$(MAKE) task4-normalize
	$(MAKE) task6-api-normalize
	$(MAKE) fn-call-normalize
	$(MAKE) task7-normalize

# ── TASK-8: 프롬프트 개선 분석 ────────────────────────────────
task8-schema:
	docker exec -i llm-monitoring-postgres-1 psql -U codex -d codex_observability -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/011-prompt-efficiency-schema.sql

task8-normalize:
	python3 scripts/normalize_local_helper_events.py

task8-helper-sample:
	python3 scripts/codex_local_helper.py --config examples/codex.local-helper.toml.example '{"type":"agent-turn-complete","thread-id":"conv-task8-sample-1","turn-id":"turn-task8-1","cwd":"$(CURDIR)","input-messages":["README와 docker compose 기준으로 prompt efficiency dashboard 구현 상태를 점검하고 누락된 패널을 찾아줘."],"last-assistant-message":"알겠습니다. 관련 스키마와 대시보드를 점검하겠습니다."}'

task8-sample-mixed:
	python3 scripts/send_sample_otel.py --response-id resp-task8-1 --session-id session-task8-1 --conversation-id conv-task8-sample-1 --input-tokens 1800 --output-tokens 420 --cached-input-tokens 300 --reasoning-tokens 80 --total-tokens 2220 --tool shell.exec --tool-call-id toolcall-task8-1 --tool-duration-ms 340 --tool-output-size 2048
	$(MAKE) task8-helper-sample

task8-verify:
	$(MAKE) task8-schema
	$(MAKE) task8-sample-mixed
	$(MAKE) task3-normalize
	$(MAKE) task4-normalize
	$(MAKE) task6-api-normalize
	$(MAKE) task7-normalize
	$(MAKE) task8-normalize
	python3 scripts/calculate_costs.py compute-daily --date $$(date +%Y-%m-%d)

# ── TASK-9: Usage context enrichment ─────────────────────────
task9-schema:
	docker exec -i llm-monitoring-postgres-1 psql -U codex -d codex_observability -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/012-usage-context-schema.sql

task9-verify:
	$(MAKE) task9-schema
	$(MAKE) task3-normalize
	$(MAKE) task8-normalize
	python3 scripts/calculate_costs.py compute-daily --date $$(date +%Y-%m-%d)

# 재계산: make cost-recompute FROM=2025-01-01 TO=2025-01-31
cost-recompute:
	python3 scripts/calculate_costs.py compute-range --from $(FROM) --to $(TO)

# raw_event 30일 purge (default) — make cost-purge-raw DAYS=30
cost-purge-raw:
	python3 scripts/calculate_costs.py purge-raw-events

# 365일 이상 된 usage row 삭제 — make cost-purge-old
cost-purge-old:
	python3 scripts/calculate_costs.py drop-old-rows

# ── fn_call 이벤트 파이프라인 ────────────────────────────────
fn-call-schema:
	docker exec -i llm-monitoring-postgres-1 psql -U codex -d codex_observability -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/003-fn-call-and-mapping-schema.sql

fn-call-normalize:
	python3 scripts/normalize_fn_call_events.py

fn-call-sample:
	python3 scripts/send_sample_otel.py \
	  --response-id resp-fn-shell-1 \
	  --session-id session-fn-shell-1 \
	  --conversation-id conv-fn-shell-1 \
	  --tool shell.exec \
	  --tool-call-id toolcall-shell-fn-1 \
	  --fn-call-item-id toolcall-shell-fn-1 \
	  --fn-call-arguments '{"command":"ls -la /tmp"}' \
	  --tool-duration-ms 210 \
	  --tool-output-size 1024
	python3 scripts/send_sample_otel.py \
	  --team backend --user-id sample-second@example.com \
	  --response-id resp-fn-web-1 \
	  --session-id session-fn-web-1 \
	  --conversation-id conv-fn-web-1 \
	  --tool web.search \
	  --tool-call-id toolcall-web-fn-1 \
	  --fn-call-item-id toolcall-web-fn-1 \
	  --fn-call-arguments '{"query":"openai pricing 2025"}' \
	  --tool-duration-ms 450 \
	  --tool-output-size 8192

fn-call-verify:
	$(MAKE) fn-call-schema
	$(MAKE) fn-call-sample
	$(MAKE) fn-call-normalize

# ── user mapping enrichment ──────────────────────────────────
# CSV 예시: configs/user-mapping-sample.csv
enrich-import-csv:
	python3 scripts/enrich_user_mapping.py import-csv configs/user-mapping-sample.csv

enrich-backfill:
	python3 scripts/enrich_user_mapping.py backfill

enrich-report:
	python3 scripts/enrich_user_mapping.py report
