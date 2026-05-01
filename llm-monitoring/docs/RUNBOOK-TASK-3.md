# TASK-3 로컬 운영 Runbook

## 목표

Loki에 적재된 `codex.sse_event(kind=response.completed)` 로그에서 token usage를 정규화해 PostgreSQL에 적재하고, Grafana SQL 대시보드에서 모델/팀/사용자 단위로 조회한다.

---

## 사전 준비

1. 스택 기동

```bash
docker compose up -d
```

2. PostgreSQL 스키마 적용

신규 볼륨이면 자동 적용된다. 기존 `postgres17-data`를 계속 쓰는 경우 아래 명령으로 수동 적용한다.

```bash
make task3-schema
```

---

## 샘플 데이터 주입

기본 usage breakdown이 포함된 이벤트를 보낸다.

```bash
python3 scripts/send_sample_otel.py
```

cached/reasoning breakdown이 없는 이벤트도 하나 더 보낸다.

```bash
python3 scripts/send_sample_otel.py \
  --team sample-team \
  --user-id sample-user@example.com \
  --model gpt-5.4 \
  --repository /workspace/example-repo \
  --session-id session-task3-missing \
  --conversation-id conv-task3-missing \
  --input-tokens 900 \
  --output-tokens 240 \
  --total-tokens 1140 \
  --omit-cached-input-tokens \
  --omit-reasoning-tokens
```

또는 한 번에:

```bash
make task3-sample-mixed
```

---

## 정규화 실행

```bash
python3 scripts/normalize_usage_events.py
```

또는:

```bash
make task3-normalize
```

---

## 검증 절차

### 1. PostgreSQL 적재 확인

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c 'select event_time, team, user_id, model, input_tokens, cached_input_tokens, cached_input_tokens_available, output_tokens, reasoning_tokens, reasoning_tokens_available, total_tokens from codex_usage_events order by event_time desc limit 20;'
```

### 2. Breakdown 제공 여부 확인

```bash
docker exec llm-monitoring-postgres-1 \
  psql -U codex -d codex_observability \
  -c 'select model, count(*) as requests, sum(case when cached_input_tokens_available then 1 else 0 end) as cached_present, sum(case when reasoning_tokens_available then 1 else 0 end) as reasoning_present from codex_usage_events group by model order by model;'
```

### 3. Grafana 대시보드 확인

- `Codex Token Usage - Models`
- `Codex Token Usage - Teams`
- `Codex Token Usage - Users`

Grafana 접속 주소:

- `http://localhost:3000`

### 4. Grafana 프로비저닝 확인

```bash
curl -sS -u admin:admin http://localhost:3000/api/search | jq '.[] | {title, uid}'
```

---

## 완료 기준 해석

로컬 기준으로는 아래가 확인되면 TASK-3의 기술적 구성이 준비된 것으로 본다.

- `response.completed` 로그에서 token usage가 파싱된다.
- PostgreSQL `codex_usage_events`에 중복 없이 적재된다.
- 모델/팀/사용자 단위 토큰 조회가 가능하다.
- cached/reasoning breakdown 제공 여부를 별도로 확인할 수 있다.
- Grafana SQL 대시보드에서 기간 필터와 변수 필터가 동작한다.
