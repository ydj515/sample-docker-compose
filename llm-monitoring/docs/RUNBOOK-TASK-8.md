# RUNBOOK: TASK-8 프롬프트 개선 분석

## 목적

`TASK-8`에서 추가한 local helper 정규화, prompt turn/session 분석 view, Grafana `Codex Prompt Efficiency` 대시보드가 로컬 스택에서 정상 동작하는지 검증한다.

---

## 구성 요소

- TASK-8 스키마: `configs/postgres/init/011-task8-prompt-efficiency-schema.sql`
- Local helper normalizer: `scripts/normalize_local_helper_events.py`
- Local helper 설치/연동: `scripts/codex_local_helper.py`, `scripts/install_codex_local_helper.sh`
- Grafana 대시보드: `configs/grafana/dashboards/prompt-efficiency.json`
- 가이드 문서: `docs/PROMPT-WRITING-GUIDE.md`

---

## 사전 조건

1. `docker compose up -d`로 스택이 올라와 있어야 한다.
2. TASK-3 ~ TASK-8 스키마가 적용되어 있어야 한다.
3. local helper가 설치되어 있거나, 샘플 helper event를 수동으로 보낼 수 있어야 한다.

```bash
make task3-schema
make task4-schema
make task5-schema
make task6-schema
make task7-schema
make task8-schema
```

기존 volume을 재사용 중이면 init script가 자동 재실행되지 않으므로 `make task8-schema`를 한 번 명시적으로 실행한다.

---

## 검증 절차

### 1. local helper 샘플과 correlated runtime 샘플 주입

아래 타깃은 같은 `conversation_id/thread_id`를 공유하는 sample OTLP event와 helper event를 보낸다.

```bash
make task8-sample-mixed
```

이 타깃은 아래 두 종류를 순서대로 보낸다.

- `conv-task8-sample-1` conversation의 usage/tool/api/trace 샘플
- 같은 `thread-id=conv-task8-sample-1`를 가진 `codex.local_helper_context` helper 샘플

### 2. 정규화 실행

```bash
python3 scripts/normalize_usage_events.py
python3 scripts/normalize_tool_events.py
python3 scripts/normalize_api_request_events.py
python3 scripts/normalize_trace_spans.py
python3 scripts/normalize_local_helper_events.py
python3 scripts/calculate_costs.py compute-daily --date $(date +%Y-%m-%d)
```

또는:

```bash
make task8-verify
```

### 3. helper 원천 이벤트 적재 확인

```sql
select
  event_time,
  thread_id,
  turn_id,
  user_id,
  team,
  repo_name,
  input_message_char_count,
  last_assistant_message_char_count
from codex_local_helper_events_dashboard
order by event_time desc
limit 20;
```

확인 포인트:

- `thread_id`
- `turn_id`
- `input_message_char_count`
- `resolved_user_id/resolved_team`가 dashboard view에서 `user_id/team`으로 노출되는지

### 4. turn 분석 view 확인

```sql
select
  helper_event_time,
  thread_id,
  turn_sequence,
  input_message_char_count,
  output_tokens,
  estimated_cost_usd,
  failed_tool_call_count,
  estimated_retry_count,
  primary_model,
  has_correlated_runtime_events
from codex_prompt_turns_dashboard
order by helper_event_time desc
limit 20;
```

확인 포인트:

- `input_message_char_count`
- `output_tokens`
- `estimated_cost_usd`
- `failed_tool_call_count`
- `estimated_retry_count`

### 5. 세션 분석 view 확인

```sql
select
  session_started_at,
  thread_id,
  user_id,
  team,
  repo_name,
  turn_count,
  total_prompt_chars,
  total_output_tokens,
  total_estimated_cost_usd,
  total_failed_tool_calls,
  total_estimated_retries
from codex_prompt_sessions_dashboard
order by total_estimated_cost_usd desc, session_started_at desc
limit 20;
```

### 6. 개선 후보 view 확인

```sql
select
  helper_event_time,
  thread_id,
  user_id,
  team,
  input_message_char_count,
  output_tokens,
  estimated_cost_usd,
  failed_tool_call_count,
  estimated_retry_count,
  recommendation
from codex_prompt_optimization_candidates_dashboard
order by helper_event_time desc
limit 20;
```

### 7. Grafana 대시보드 확인

- Grafana: `http://localhost:3000`
- Dashboard: `Codex Prompt Efficiency`

확인할 패널:

- `Helper Turn 수`
- `평균 Prompt 길이`
- `Prompt 길이 vs Output Token 상관계수`
- `Prompt 길이 vs 비용 상관계수`
- `Prompt Bucket별 효율 요약`
- `고비용 세션 Top 50`
- `반복 실패 패턴 Top 50`
- `개선 후보 Turn`

---

## 해석 원칙

- `prompt length`는 prompt 원문이 아니라 helper가 계산한 문자 수다.
- `estimated_retry_count`는 SDK 내부 retry counter가 아니라, 같은 turn window에서 반복된 request type 개수 기반 proxy다.
- 첫 helper event는 이전 helper event가 없으므로 기본 30분 lookback window를 사용한다.
- `thread_id = conversation_id`가 성립하지 않는 환경이면 correlation 정확도가 떨어질 수 있다.

---

## 알려진 제한

- 현재 helper MVP는 `notify` 기반 turn-complete event까지만 수집한다.
- human approval wait time을 직접 계산하는 `approval_requested/completed` pair event는 아직 없다.
- prompt 원문 sampling과 redaction pipeline은 기본 비활성 상태이며, TASK-8 후속 보강 범위다.
- 기존 `notify = [...]`가 이미 있으면 helper가 그 notifier를 대체할 수 있다. fan-out/wrapper는 아직 후속 구현이다.
