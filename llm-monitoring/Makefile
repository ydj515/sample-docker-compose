.PHONY: up down config sample task3-schema task3-normalize task3-sample-mixed task3-verify task4-schema task4-normalize task4-sample-mixed task4-verify

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
	python3 scripts/send_sample_otel.py --team backend --user-id dev-b --model gpt-5.2-codex --repository /workspace/another-repo --project llm-monitoring --session-id session-task3-missing --conversation-id conv-task3-missing --input-tokens 900 --output-tokens 240 --total-tokens 1140 --omit-cached-input-tokens --omit-reasoning-tokens

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
	python3 scripts/send_sample_otel.py --team backend --user-id dev-b --repository /workspace/another-repo --response-id resp-task4-shell-1 --session-id session-task4-shell-1 --conversation-id conv-task4-shell-1 --tool shell.exec --tool-call-id toolcall-shell-1 --tool-duration-ms 900 --tool-output-size 2048

task4-verify:
	$(MAKE) task4-schema
	$(MAKE) task4-sample-mixed
	$(MAKE) task4-normalize
