# Codex OTel Observability Stack

Codex CLI의 OpenTelemetry 로그, 메트릭, 트레이스를 로컬에서 수집하고, Grafana와 PostgreSQL에서 조회하기 위한 참조 스택이다.

이 저장소는 OpenAI Codex 공식 문서의 Observability/Telemetry 설정을 기준으로 다음 목적을 가진다.

- Codex 실행 이벤트를 OTLP로 수집한다.
- 모델별 요청 수, 토큰 사용량, tool 사용 패턴을 확인한다.
- raw prompt를 기본적으로 저장하지 않는다.
- token usage 정규화와 향후 비용 집계용 PostgreSQL 저장소까지 확장 가능한 구조를 유지한다.

## 1. 공식 문서 기준 핵심 사항

OpenAI Codex 공식 문서 기준으로 관측 설정은 기본 비활성화이며, `[otel]` 섹션으로 명시적으로 켜야 한다.

- `otel.environment`의 기본값은 `dev`다.
- `otel.exporter` 기본값은 `none`이다.
- `otel.log_user_prompt`는 raw prompt 내보내기를 제어한다.
- `otel.metrics_exporter` 기본값은 `statsig`다.
- `otel.trace_exporter`는 별도로 설정할 수 있다.

이 저장소에서는 보안 정책상 다음 값을 기본 원칙으로 둔다.

- `log_user_prompt = false`
- tool output 원문 장기 저장 금지
- `raw_event`는 redaction 이후 단기 보관

## 2. OpenAI 공식 이벤트/메트릭 기준

공식 문서에서 대표적으로 언급하는 이벤트는 아래와 같다.

- `codex.conversation_starts`
- `codex.api_request`
- `codex.sse_event`
- `codex.websocket_request`
- `codex.websocket_event`
- `codex.user_prompt`
- `codex.tool_decision`
- `codex.tool_result`

중요한 점은 `response.completed`가 최상위 이벤트명이 아니라 `codex.sse_event`의 하위 `kind`로 나타난다는 점이다. 따라서 토큰 사용량 파싱은 `event_name=codex.sse_event`와 `event_kind=response.completed` 조합을 기준으로 설계하는 편이 안전하다.

공식 문서의 OTel 메트릭 이름은 점 표기법을 사용한다.

다만 공식 문서가 보장하는 것은 API/stream/tool 활동 메트릭이며, 토큰 합계 메트릭 이름까지 직접 약속하는 것은 아니다. 이 저장소에서는 토큰 대시보드를 `codex.sse_event(kind=response.completed)` 기반 파생 지표로 취급한다.

| 공식 이름 | Prometheus 적재 후 일반적 이름 |
|----------|-------------------------------|
| `codex.api_request` | `codex_api_request_total` |
| `codex.api_request.duration_ms` | `codex_api_request_duration_ms_bucket` |
| `codex.sse_event` | `codex_sse_event_total` |
| `codex.sse_event.duration_ms` | `codex_sse_event_duration_ms_bucket` |
| `codex.tool.call` | `codex_tool_call_total` |
| `codex.tool.call.duration_ms` | `codex_tool_call_duration_ms_bucket` |

위 변환은 OTLP metric이 Prometheus naming 규칙으로 변환될 때 일반적으로 기대되는 형태다.

## 2.1 Token Usage 해석 원칙

이 저장소는 OpenAI Codex usage payload를 아래 원칙으로 해석한다.

- `input_tokens`는 전체 input token 수다.
- `cached_input_tokens`는 전체 input 내부의 cache hit breakdown이다.
- `output_tokens`는 전체 output token 수다.
- `reasoning_tokens`는 payload가 제공할 경우 전체 output 내부의 breakdown이다.
- 따라서 `cached_input_tokens`와 `reasoning_tokens`는 기본적으로 `input_tokens`, `output_tokens`에 추가로 더하는 별도 총계가 아니다.

PostgreSQL 정규화 스키마에서는 대시보드와 비용 계산을 단순화하기 위해 아래 파생 컬럼을 함께 사용한다.

- `uncached_input_tokens = input_tokens - cached_input_tokens`
- `visible_output_tokens = output_tokens - reasoning_tokens`

## 3. 저장소 구조

```text
.
├── docker-compose.yml
├── .env.example
├── configs
│   ├── grafana
│   ├── loki
│   ├── otel-collector
│   ├── prometheus
│   └── tempo
├── docs
├── scripts
└── Makefile
```

## 4. 로컬 스택 구성

`docker-compose.yml`은 아래 서비스를 띄운다.

| 서비스 | 역할 | 기본 포트 |
|--------|------|----------|
| `ingest-gateway` | OTLP HTTP 진입점, `x-codex-ingest-token` 검증, identity attribute 주입 | `4318` |
| `otel-collector` | 내부 fan-out, health 노출 | `13133` |
| `loki` | raw log 저장/검색 | `3100` |
| `prometheus` | metric 저장/조회 | `9090` |
| `tempo` | trace 저장/조회 | `3200` |
| `grafana` | 통합 UI | `3000` |
| `alertmanager` | alert 수신/상태 확인 | `9093` |
| `postgres` | 정규화/비용 저장소 | `5432` |
| `ops-exporter` | 운영 메트릭 노출 | `9107` |
| `cron-scheduler` | 정규화/비용/retention 주기 실행 | 없음 |

2026-04-28 기준으로 실제 기동 및 호환성 검증을 마친 버전 조합은 아래와 같다.

| 서비스 | 버전 |
|--------|------|
| OTel Collector Contrib | `0.150.1` |
| Loki | `3.6.10` |
| Prometheus | `3.5.2` |
| Tempo | `2.10.4` |
| Grafana | `13.0.1` |
| Alertmanager | `0.32.0` |
| PostgreSQL | `17.9-alpine` |

버전 선정 원칙은 다음과 같다.

- PostgreSQL은 메이저 `17`의 최신 안정 패치로 고정한다.
- Prometheus는 공식 다운로드 페이지에서 `LTS`로 표기하는 `3.5.2`를 사용한다.
- Grafana는 `13.x` 계열까지 올린 뒤 provisioning, datasource, dashboard 호환성을 실제로 다시 검증한다.
- Tempo, Alertmanager, OTel Collector는 현재 설정과 호환성이 확인된 안정 패치를 사용한다.
- Loki는 최신 기능 브랜치보다 로컬 참조 스택 호환성이 좋은 `3.6.x` 최신 패치 `3.6.10`을 사용한다.

현재 로컬 참조 스택의 데이터 흐름은 아래와 같다.

```text
Codex CLI
  -> Ingest Gateway
      -> OTel Collector
      -> Loki
      -> Prometheus
      -> Tempo

Loki response.completed log
  -> normalize_usage_events.py
  -> PostgreSQL
  -> Grafana SQL datasource

cron-scheduler
  -> normalize_usage_events.py
  -> normalize_tool_events.py
  -> normalize_api_request_events.py
  -> calculate_costs.py

Loki / PostgreSQL / retention job status / volume usage
  -> task6_ops_exporter.sh
  -> Prometheus
  -> Alertmanager / Grafana

Cost Pipeline
  -> PostgreSQL aggregate / policy table
  -> Grafana SQL datasource
```

## 5. 실행 방법

### 5.1 환경 변수 준비

```bash
cp .env.example .env
```

### 5.2 스택 기동

```bash
docker compose up -d
```

### 5.3 접속 주소

- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- Alertmanager: `http://localhost:9093`
- Loki: `http://localhost:3100`
- Tempo: `http://localhost:3200`
- OTLP ingest gateway health: `http://localhost:4318/healthz`
- OTel Collector health: `http://localhost:13133`
- Operations exporter health: `http://localhost:9107/healthz`
- Operations exporter metrics: `http://localhost:9107/metrics`

## 6. Codex 설정 예시

공식 문서의 `[otel]` 설정과 Config Reference를 기준으로, 이 저장소에서는 아래와 같은 구성을 권장한다.

- `x-codex-ingest-token`은 사용자별 또는 기기별로 발급한 ingest token을 넣는다.
- 이 저장소의 `ingest-gateway`는 이 토큰을 검증한 뒤 `ingest_token_id`, `resolved_user_id`, `resolved_team`을 OTLP payload의 resource/attribute에 직접 주입한다.
- 현재 Codex telemetry에서 `user_email`이 관찰될 수는 있지만, 장기 운영 식별자는 `resolved_user_id`를 기준으로 잡는 편이 안전하다.
- 아래 예시의 `USER_SPECIFIC_TOKEN`은 placeholder다. 조직 배포 시에는 실제 발급 토큰 문자열로 치환하거나, 별도 템플릿 렌더링 단계에서 주입한다.
- 현재 gateway 구현 범위는 OTLP/HTTP 기준이다. 사용자 식별을 일관되게 유지하려면 Codex exporter도 `otlp-http`를 사용한다.

```toml
[otel]
environment = "local"
log_user_prompt = false

exporter = { otlp-http = {
  endpoint = "http://localhost:4318/v1/logs",
  protocol = "binary",
  headers = { "x-codex-ingest-token" = "USER_SPECIFIC_TOKEN" }
}}

metrics_exporter = { otlp-http = {
  endpoint = "http://localhost:4318/v1/metrics",
  protocol = "binary",
  headers = { "x-codex-ingest-token" = "USER_SPECIFIC_TOKEN" }
}}

trace_exporter = { otlp-http = {
  endpoint = "http://localhost:4318/v1/traces",
  protocol = "binary",
  headers = { "x-codex-ingest-token" = "USER_SPECIFIC_TOKEN" }
}}
```

추가로, OpenAI로 전송되는 익명 usage/health metrics까지 끄고 싶다면 별도 analytics 설정을 사용할 수 있다.

```toml
[analytics]
enabled = false
```

현재 운영 정책은 아래처럼 두는 것을 기본값으로 한다.

- 사용자 1명당 active ingest token 1개
- 권장 `ingest_token_id` 형식: `<resolved_user_id>-primary`
- 한 사용자의 여러 이메일 alias는 token이 아니라 `codex_user_email_mapping`으로 합친다
- 토큰 원문은 발급 시 1회만 확인하고, 이후에는 secret manager 또는 비밀 저장소로만 관리한다
- `expires_at` 컬럼과 입력 옵션은 있지만, 현재 gateway는 만료일을 자동 차단하지 않는다
- 즉 현재 효력이 있는 상태 제어는 `is_active`와 `revoke`이며, `expires_at`는 운영 메타데이터로 본다

토큰 발급은 아래처럼 할 수 있다.

```bash
docker compose exec -T cron-scheduler \
  python3 scripts/manage_ingest_tokens.py issue \
  --postgres-host postgres \
  --ingest-token-id dj.yoo-primary \
  --resolved-user-id dj.yoo \
  --resolved-team backend
```

위 명령은 `raw_token=...` 한 줄을 출력한다. 이 값이 실제 `~/.codex/config.toml`의 `x-codex-ingest-token` header에 들어가는 비밀 문자열이다.

토큰 목록 조회:

```bash
docker compose exec -T cron-scheduler \
  python3 scripts/manage_ingest_tokens.py list \
  --postgres-host postgres
```

토큰 회수:

```bash
docker compose exec -T cron-scheduler \
  python3 scripts/manage_ingest_tokens.py revoke \
  --postgres-host postgres \
  --ingest-token-id dj.yoo-primary
```

토큰 재발급:

```bash
docker compose exec -T cron-scheduler \
  python3 scripts/manage_ingest_tokens.py issue \
  --postgres-host postgres \
  --ingest-token-id dj.yoo-primary \
  --resolved-user-id dj.yoo \
  --resolved-team backend \
  --description "reissued after token rotation"
```

같은 `ingest_token_id`로 `issue`를 다시 실행하면 새 `raw_token`이 발급되고, 이전 token hash는 즉시 교체된다. 즉 현재 스크립트 기준 재발급은 “같은 사용자 키 ID를 유지한 채 비밀값만 회전”하는 방식이다.

현재 구현 기준으로 `expires_at`는 조회와 운영 기록에는 사용되지만, gateway가 이를 보고 자동으로 `403` 차단을 하지는 않는다. 만료 통제가 필요하면 현재는 `revoke`를 사용해야 한다.

상세 운영 절차는 [docs/RUNBOOK-INGEST-TOKEN.md](docs/RUNBOOK-INGEST-TOKEN.md)에 정리돼 있다.

## 6.1 Identity Resolution 모델

이 저장소는 direct telemetry와 gateway enrichment를 분리해서 본다.

- `observed_user_email`
  - Codex telemetry에서 직접 관찰한 이메일 값
  - 현재 버전에서 들어올 수 있지만, 장기 계약 필드라고 가정하지 않는다.
- `resolved_user_id`
  - gateway token mapping 또는 이메일 alias mapping으로 정한 canonical 사용자 ID
  - 대시보드와 비용 집계의 기본 사용자 식별자로 사용한다.
- `resolved_team`
  - gateway token mapping 또는 사용자 alias mapping으로 정한 canonical 팀 값
  - direct `team`이 비어 있어도 운영 집계를 유지하기 위해 사용한다.
- `ingest_token_id`
  - 원문 토큰 자체가 아니라 gateway가 해석한 비밀정보 없는 token key id
  - 추적과 운영 감사용으로만 저장한다.

같은 이름이 비슷해서 자주 헷갈리는 필드는 아래처럼 나눠서 본다.

- `codex_user_mapping.email`
  - canonical user master에 저장한 대표 이메일이다.
  - 실제 Codex telemetry에서 매번 이 값이 날아와야 한다는 의미는 아니다.
- `observed_user_email`
  - 그 시점의 Codex telemetry 또는 alias mapping 과정에서 실제로 관찰한 이메일 값이다.
  - 한 사용자가 여러 계정을 쓰면 세션마다 달라질 수 있다.
- `codex_user_email_mapping`
  - `observed_user_email -> resolved_user_id`를 연결하는 alias 테이블이다.
  - `example.1@example.com`, `example.2@example.com`처럼 여러 이메일이 같은 `example`로 합쳐질 수 있다.

즉 `codex_user_mapping`은 사람 기준 master이고, `codex_user_email_mapping`은 이메일 alias 기준 매핑 테이블이다.

초기 canonical user seed는 `configs/user-mapping-sample.csv`를 기준으로 아래처럼 설정돼 있다.

- `example`의 대표 이메일: `example@example.com`
- `example.1@example.com` -> `example`
- `example.2@example.com` -> `example`

즉 한 사용자가 여러 Codex/OpenAI 계정 또는 이메일 별칭을 사용하더라도, `resolved_user_id` 기준으로 같은 사용자로 집계된다.

gateway 또는 관리 스크립트에서 사용할 기본 테이블은 아래 두 개다.

- `codex_ingest_token_mapping`
  - `ingest_token_id`
  - `token_hash`
  - `resolved_user_id`
  - `resolved_team`
  - `is_active`
- `codex_user_email_mapping`
  - `user_email`
  - `resolved_user_id`
  - `team`
  - `display_name`
  - 기타 부서/코스트센터 메타데이터

canonical 사용자 예시는 아래와 같다.

- `codex_user_mapping`
  - `user_id = example`
  - `email = example@example.com`
  - `team = backend`
- `codex_user_email_mapping`
  - `example.1@example.com -> example`
  - `example.2@example.com -> example`

정규화 테이블은 raw field와 resolved field를 둘 다 유지한다.

- raw field
  - `user_id`
  - `team`
- resolved field
  - `observed_user_email`
  - `resolved_user_id`
  - `resolved_team`
  - `ingest_token_id`

Grafana 대시보드는 `codex_usage_events_dashboard`, `codex_tool_events_dashboard`, `codex_api_request_events_dashboard`에서 `resolved_user_id/resolved_team`를 우선 사용하도록 구성되어 있다. 따라서 alias 매핑을 추가하면 과거 데이터를 backfill한 뒤 바로 canonical 사용자 기준으로 집계된다.

## 6.2 Resolved Identity PromQL 예시

`x-codex-ingest-token`이 gateway에서 정상 해석되면, Prometheus 시계열에도 `resolved_user_id`, `resolved_team`, `ingest_token_id`, `identity_source=ingest_token` 라벨이 함께 붙을 수 있다.

아래 예시는 “canonical 사용자/팀 기준”으로 바로 집계하거나, 실제 series에 resolved 라벨이 붙었는지 검증할 때 사용할 수 있다.

### 사용자/팀별 tool 호출 수

```promql
sum by (resolved_user_id, resolved_team) (
  increase(codex_tool_call_total[$__range])
)
```

### 사용자/팀별 API 요청 수

```promql
sum by (resolved_user_id, resolved_team) (
  increase(codex_api_request_total[$__range])
)
```

### 최근 resolved identity 시계열 존재 여부 확인

```promql
count by (resolved_user_id, resolved_team, otel_scope_name, job) (
  last_over_time(codex_tool_call_total[2h])
)
```

### 최근 2시간 API 요청 시계열에서 resolved 라벨 확인

```promql
count by (resolved_user_id, resolved_team, otel_scope_name, job) (
  last_over_time(codex_api_request_total[2h])
)
```

### raw 라벨과 resolved 라벨 비교

```promql
count by (user_id, team, resolved_user_id, resolved_team, ingest_token_id) (
  last_over_time(codex_tool_call_total[2h])
)
```

운영 시에는 direct telemetry의 `user_id/team`보다 `resolved_user_id/resolved_team` 기준 집계를 우선 사용하는 편이 안정적이다.

## 6.3 Trace Sampling / Approval 분석 원칙

현재 Phase 6의 trace 운영 기본값은 아래와 같다.

- Tempo raw trace: 100% 수집
- PostgreSQL trace 정규화: 100% 적재
- 기본 retention: 7일

샘플링 완화는 아직 코드 enforcement가 아니라 운영 정책이다. 아래 조건 중 하나라도 만족하면 selective sampling 도입을 검토한다.

- 일 trace span 100만 건 초과
- Tempo 저장소 사용률 24시간 이상 70% 초과
- `normalize-trace-spans` 잡 실행 시간이 3회 연속 300초 초과

샘플링을 도입하더라도 아래 trace는 100% 유지한다.

- `op.dispatch.*_approval` span 포함 trace
- `codex.tool_result` 실패 trace
- 세션 duration 30초 이상 trace
- slowest span duration 3초 이상 trace
- API failure alert 발생 시간대 trace

approval 관련해서 현재 실제 Codex trace에서 확인된 span은 아래 두 종류다.

- `op.dispatch.exec_approval`
- `op.dispatch.patch_approval`

현재 측정 가능한 값:

- approval span 발생 횟수
- approval span duration
- approval span이 속한 trace의 사용자/팀/세션 컨텍스트

현재 직접 측정할 수 없는 값:

- 사용자가 승인 UI를 보고 실제로 승인/거절하기까지의 human wait time
- approval requested 시각과 completed 시각의 pair latency
- 거절, 취소, timeout 원인별 dwell time

따라서 현재 `approval_duration_ms`는 사람 대기 시간이 아니라 runtime approval dispatch overhead로 해석한다.

## 6.4 Local Helper

Codex direct telemetry만으로는 `repository`, `cwd`, 정밀 approval lifecycle 같은 로컬 컨텍스트를 안정적으로 얻기 어렵다. 이 저장소는 그 보강 경로로 `local helper`를 채택한다.

현재 helper MVP 범위:

- Codex `notify` payload를 받아 `codex.local_helper_context` OTLP log를 전송
- `cwd`, `repo_root`, `repo_name`, `git_branch`, `git_remote_slug`, `host_name` 같은 로컬 컨텍스트 보강
- prompt 원문, assistant 원문, tool output 원문은 미수집
- Codex의 `x-codex-ingest-token` header를 재사용해 helper event도 같은 `resolved_user_id/resolved_team` 경로로 수집

현재 helper가 수집하는 항목:

- `notification_type`
- `thread_id`
- `turn_id`
- `cwd`
- `is_git`
- `repo_root`
- `repo_name`
- `git_branch`
- `git_remote_slug`
- `host_name`
- `input_message_count`
- `input_message_char_count`
- `last_assistant_message_char_count`

기본 미수집 항목:

- prompt 원문
- assistant 원문
- tool output 원문
- 파일 내용
- remote URL 원문

설치 절차 요약:

```bash
bash scripts/install_codex_local_helper.sh
```

그 뒤 install script가 출력한 top-level `notify = [...]` snippet을 `~/.codex/config.toml`에 추가한다.

상세 절차와 collected field 정책은 [docs/RUNBOOK-LOCAL-HELPER.md](docs/RUNBOOK-LOCAL-HELPER.md)에 정리돼 있다.

중요한 점은 현재 helper MVP가 `notify` 기반이라는 점이다. 따라서 `agent-turn-complete` 요약 이벤트는 수집할 수 있지만, human approval wait time을 계산할 수 있는 정밀 `approval_requested/completed` pair는 아직 없다. 이 부분은 같은 helper에 hook 기반 또는 별도 로컬 이벤트 소스를 추가해 확장한다.

현재 install script는 `codex-notify-fanout.py`를 같이 설치하고, 기존 `notify = [...]`가 있으면 fan-out config에 자동으로 포함한다. 따라서 기존 notifier와 local helper를 함께 유지하는 것이 기본 경로다.

## 6.5 Prompt Efficiency

`TASK-8`은 local helper의 `input_message_char_count`, `input_message_count`, `last_assistant_message_char_count`를 프롬프트 간접 지표의 원천으로 사용한다. 이 저장소는 raw prompt를 저장하지 않고도 아래 항목을 같이 본다.

- prompt length proxy
- output token
- tool failure
- API retry proxy
- high cost session
- long duration session

현재 구현은 `thread_id = conversation_id`와 `이전 helper event ~ 현재 helper event` window를 사용해 helper turn과 usage/tool/api/cost/trace를 상관분석한다. 결과는 PostgreSQL `codex_prompt_turns_dashboard`, `codex_prompt_sessions_dashboard`, `codex_prompt_optimization_candidates_dashboard`와 Grafana `Codex Prompt Efficiency` 대시보드에서 확인할 수 있다.

이 지표는 프롬프트 원문 품질을 직접 측정하는 것이 아니라, 길이 대비 산출량, 실패율, 비용, retry 경향을 간접적으로 해석하기 위한 것이다. 상세 해석 기준은 [docs/PROMPT-WRITING-GUIDE.md](docs/PROMPT-WRITING-GUIDE.md)에 정리했다.

## 7. Retention 정책

이 저장소 초안은 “무엇을 얼마나 오래 보관할지”를 저장소별로 분리해서 본다.

| 데이터 | 저장소 | 기본 보관 기간 | 현재 상태 |
|--------|--------|---------------|----------|
| Raw OTel 로그 | Loki | 14일 | 설정 반영 완료 |
| Metrics | Prometheus | 180일 | 설정 반영 완료 |
| Traces | Tempo | 7일 | 설정 반영 완료 |
| 정규화 usage row | PostgreSQL | 365일 | scheduler 연계 완료 |
| `raw_event` JSON | PostgreSQL | 30일 | purge job + scheduler 연계 완료 |
| 비용 집계 | PostgreSQL | 365일 | `compute-daily` + scheduler 연계 완료 |

추가 운영 기준은 아래와 같다.

- 디스크 사용률 70%에서 경고, 85%에서 긴급 알림
- `raw_event`는 redaction 이후에만 저장
- `raw_event`와 정규화 row는 서로 다른 retention을 적용
- PostgreSQL은 월 단위 파티션 기반 운영 권장

## 8. 현재 포함된 설정 파일

- `configs/otel-collector/config.yaml`
  - OTLP gRPC/HTTP receiver
  - Loki OTLP ingest / Prometheus Remote Write / Tempo OTLP gRPC fan-out
  - Collector self-metrics (`:8888`)
  - health endpoint (`:13133`)
- `Dockerfile.ingest-gateway`
  - OTLP HTTP ingest gateway 런타임 이미지
- `scripts/otlp_ingest_gateway.py`
  - `x-codex-ingest-token` 헤더를 검증하고 canonical identity attribute를 주입한 뒤 내부 collector로 전달
- `scripts/manage_ingest_tokens.py`
  - ingest token 발급, 조회, 비활성화 관리
- `configs/loki/config.yml`
  - filesystem storage
  - 14일 retention
- `configs/prometheus/prometheus.yml`
  - Collector/Loki/Tempo/Prometheus self-scrape
  - remote write receiver 사용
  - Alertmanager 연동
- `configs/prometheus/rules/otel-collector-alerts.yml`
  - `OTelCollectorDown`
  - `OTelExporterSendFailures`
- `configs/prometheus/rules/codex-operations-alerts.yml`
  - 비용 임계치, tool failure/p95, 데이터 gap, 저장소 사용률, retention job alert
- `configs/tempo/config.yml`
  - local backend
  - 7일 retention
- `configs/grafana/provisioning/datasources/datasources.yml`
  - Prometheus / Loki / Tempo / PostgreSQL / Alertmanager datasource 자동 연결
  - Tempo -> Loki traces-to-logs 상관분석 기본 설정 포함
- `configs/grafana/dashboards`
  - `Codex MVP Overview`
  - `Collector Health`
  - `Codex Token Usage - Models`
  - `Codex Token Usage - Teams`
  - `Codex Token Usage - Users`
  - `Codex Tool Usage`
  - `Codex Operations Alerting`
  - `Codex Trace Analysis`
  - `Codex Prompt Efficiency`
- `configs/postgres/init/001-task3-schema.sql`
  - `codex_usage_events`, `codex_usage_sync_state`, `codex_usage_events_dashboard` 생성
- `configs/postgres/init/002-task4-schema.sql`
  - `codex_tool_events`, `codex_tool_sync_state`, `codex_tool_results_dashboard` 생성
- `configs/postgres/init/004-cost-schema.sql`
  - 비용 집계, 가격 정책, 팀 budget view 생성
- `configs/postgres/init/005-ops-schema.sql`
  - `codex_job_run_status`, `codex_job_run_status_dashboard` 생성
- `configs/postgres/init/007-identity-resolution-schema.sql`
  - email alias / ingest token / resolved identity 컬럼과 dashboard view 생성
- `configs/postgres/init/009-user-seed-from-csv.sql`
  - `configs/user-mapping-sample.csv`를 읽어 canonical user와 email alias seed 적재
- `configs/postgres/init/010-trace-schema.sql`
  - trace span 저장, log-trace correlation view, session aggregate view, approval span view 생성
- `configs/postgres/init/011-prompt-efficiency-schema.sql`
  - local helper 정규화 테이블과 prompt turn/session/candidate view 생성
- `configs/postgres/init/012-usage-context-schema.sql`
  - usage event에 local helper 기반 repository context를 보강하고 cost view와 연동
- `examples/codex.local-helper.toml.example`
  - local helper privacy / 수집 범위 설정 예시
- `scripts/send_sample_otel.py`
  - 로컬 샘플 OTLP 로그/메트릭/트레이스 전송
  - `--ingest-token` 옵션으로 gateway identity 주입 검증 가능
  - sample logs와 traces가 같은 `trace_id/span_id`를 공유하도록 전송
- `scripts/normalize_usage_events.py`
  - Loki `response.completed` usage payload를 PostgreSQL로 정규화
- `scripts/normalize_tool_events.py`
  - Loki `codex.tool_decision`, `codex.tool_result` payload를 PostgreSQL로 정규화
  - 실제 Codex `codex_cli_rs` label-only `tool_result`도 파싱하고 `arguments`/`output`는 redaction 처리
- `scripts/normalize_trace_spans.py`
  - Tempo recent trace를 PostgreSQL span row로 정규화
- `scripts/normalize_local_helper_events.py`
  - Loki `codex.local_helper_context` 이벤트를 PostgreSQL로 정규화
- `scripts/codex_local_helper.py`
  - Codex notify payload를 받아 로컬 컨텍스트를 OTLP log로 보강
- `scripts/install_codex_local_helper.sh`
  - local helper 설치 및 notify snippet 출력
- `scripts/task6_ops_exporter.sh`
  - PostgreSQL 비용/retention 상태와 volume 사용량을 Prometheus text format으로 노출
- `scripts/calculate_costs.py`
  - 비용 집계와 retention job 실행 시 `codex_job_run_status`에 성공/실패 상태 기록
- `docs/RUNBOOK-TASK-2.md`
  - 로컬 검증 절차
- `docs/RUNBOOK-TASK-3.md`
  - token usage 정규화 및 SQL 대시보드 검증 절차
- `docs/RUNBOOK-TASK-4.md`
  - tool usage 정규화 및 SQL 대시보드 검증 절차
- `docs/RUNBOOK-TASK-6.md`
  - 운영 alert/rule/retention 검증 절차
- `docs/RUNBOOK-TASK-7.md`
  - trace span/session/correlation 검증 절차
- `docs/RUNBOOK-TASK-8.md`
  - prompt efficiency 정규화, helper correlation, dashboard 검증 절차
- `docs/RUNBOOK-LOCAL-HELPER.md`
  - local helper 설치, 수집 항목, privacy 정책, notify 연동 절차
- `docs/RUNBOOK-INGEST-TOKEN.md`
  - 사용자별 ingest token 발급, 회수, 재발급 운영 절차
- `docs/PROMPT-WRITING-GUIDE.md`
  - 간접 지표 기반 prompt 개선 해석 가이드

## 9. 2026-04-28 검증 결과

- `docker compose up -d`로 전체 스택 기동 확인
- Grafana `13.0.1` 기동 및 provisioning 호환성 확인
- `python3 scripts/send_sample_otel.py`로 샘플 OTLP 로그/메트릭/트레이스 주입 확인
- Prometheus에서 `codex_api_request_total`, `codex_tool_call_total` 조회 확인
- Loki에서 `event_name=codex.sse_event`, `event_name=codex.tool_result` 로그 검색 확인
- Tempo Search API에서 `service.name=codex-cli` trace 조회 확인
- Alertmanager에서 `OTelCollectorDown` firing 및 collector 재기동 후 복구 확인
- Tempo recent trace를 PostgreSQL `codex_trace_spans`로 정규화하고 `Codex Trace Analysis` 대시보드 provisioning 확인
- 실제 Codex 세션 기준 `codex_trace_sessions_dashboard`, `codex_trace_log_correlation_dashboard` 조회 확인
- 실제 approval span `op.dispatch.patch_approval`, `op.dispatch.exec_approval` 관찰 및 approval span view 조회 확인
- `codex_local_helper.py` dry-run payload 생성 및 실제 Loki `service_name=codex-local-helper` 적재 확인
- `make task3-schema`, `make task3-sample-mixed`, `make task3-normalize` 경로 검증
- PostgreSQL `codex_usage_events`에 breakdown 유무가 다른 2개 usage row 정규화 적재 확인
- Grafana에서 모델/팀/사용자 SQL 대시보드 3종 자동 프로비저닝 확인
- `make task4-schema`, `make task4-sample-mixed`, `make task4-normalize` 경로 검증
- PostgreSQL `codex_tool_events`에 success/failure, duration, error metadata가 다른 tool event 정규화 적재 확인
- Grafana에서 `Codex Tool Usage` SQL 대시보드 자동 프로비저닝 확인
- 실제 Codex 세션 `conversation_id=019dd1e4-1635-75b0-a34f-584e814c2137`의 `codex.tool_decision`, `codex.tool_result`, `codex.websocket_event` 수집 확인
- 실제 Codex `tool_result`는 `service_name=codex_cli_rs`, `tool_name`, `call_id`, `duration_ms`, `success` label 중심 포맷임을 확인
- `ops-exporter`의 `/metrics`에서 팀 budget, 회사/사용자 일 비용, retention job status, 저장소 사용률 노출 확인
- Prometheus에서 `codex-operations-alerts` rule group 로드 및 `codex-ops-exporter` scrape target `up` 확인
- Grafana에서 `Codex Operations Alerting` 대시보드 자동 프로비저닝 확인
- `compute-daily`, `purge-raw-events`, `drop-old-rows` 실행 후 `codex_job_run_status` 메트릭 반영 확인
- `cron-scheduler`가 5분 이내 실사용 Codex usage/tool/API request를 자동 정규화하는 것 확인
- PostgreSQL `codex_usage_events`에 실제 `service_name=codex_cli_rs` 세션 usage 80건 이상 적재 확인
- PostgreSQL `codex_api_request_events`에 실제 `codex.websocket_request`와 샘플 실패 이벤트가 함께 적재되는 것 확인
- `codex_api_recent_failure_rate_ratio`가 `0.107143`으로 계산되고 `CodexApiFailureRateHigh`가 `pending` 상태로 전환되는 것 확인
- `CodexUsageDataGapDetected`가 해소되는 것 확인
- `normalize_local_helper_events.py`로 helper event가 PostgreSQL `codex_local_helper_events`에 적재되는 것 확인
- `codex_prompt_turns_dashboard`, `codex_prompt_sessions_dashboard`가 helper turn과 usage/tool/api/cost를 같은 window로 묶는 것 확인
- Grafana `Codex Prompt Efficiency` 대시보드 자동 프로비저닝 확인

## 10. 아직 남아 있는 작업

- PostgreSQL 파티션 생성/삭제 고도화 및 월 파티션 운영 자동화
- Grafana folder/team RBAC 자동화
- tool output snippet에 대한 추가 redaction 규칙
- Collector HA 구성
- local helper `notify` fan-out 또는 wrapper 고도화
- helper approval lifecycle hook과 human wait time 계산
- opt-in prompt snippet sampling 검토와 redaction 정책 구체화

## 11. TASK-2 로컬 검증 절차

```bash
cp .env.example .env
docker compose up -d
python3 scripts/send_sample_otel.py
```

확인 포인트:

- Grafana `Codex MVP Overview`에서 모델별 요청 수와 Tool별 호출 수 확인
- Grafana Explore 또는 Loki에서 raw event 검색
- Grafana `Collector Health` 또는 Alertmanager에서 collector 상태/alert 확인

상세 절차는 [docs/RUNBOOK-TASK-2.md](docs/RUNBOOK-TASK-2.md)를 참고한다.

## 12. TASK-3 로컬 검증 절차

```bash
make task3-schema
make task3-sample-mixed
make task3-normalize
```

확인 포인트:

- PostgreSQL `codex_usage_events`에 `response.completed` usage row가 중복 없이 적재된다.
- `cached_input_tokens_available`, `reasoning_tokens_available`로 breakdown 제공 여부를 구분할 수 있다.
- Grafana `Codex Token Usage - Models`, `Codex Token Usage - Teams`, `Codex Token Usage - Users`에서 기간/변수 필터가 동작한다.

상세 절차는 [docs/RUNBOOK-TASK-3.md](docs/RUNBOOK-TASK-3.md)를 참고한다.

## 13. TASK-4 로컬 검증 절차

```bash
make task4-schema
make task4-sample-mixed
make task4-normalize
```

확인 포인트:

- PostgreSQL `codex_tool_events`에 `codex.tool_decision`, `codex.tool_result` row가 중복 없이 적재된다.
- Grafana `Codex Tool Usage`에서 tool별 호출 수, 실패율, p95 duration을 확인할 수 있다.
- 실패한 tool call과 느린 tool call을 테이블 패널에서 바로 조회할 수 있다.

상세 절차는 [docs/RUNBOOK-TASK-4.md](docs/RUNBOOK-TASK-4.md)를 참고한다.

## 14. TASK-6 로컬 검증 절차

```bash
docker compose up -d
make task6-schema
python3 scripts/calculate_costs.py compute-daily --date $(date +%Y-%m-%d)
python3 scripts/calculate_costs.py purge-raw-events --older-than-days 30
python3 scripts/calculate_costs.py drop-old-rows --older-than-days 365
```

확인 포인트:

- `curl http://localhost:9107/metrics`에서 `codex_team_budget_usage_ratio`, `codex_job_last_run_success`, `codex_store_usage_ratio`가 노출된다.
- Prometheus target에서 `codex-ops-exporter`가 `up` 상태다.
- Prometheus rule group `codex-operations-alerts`가 로드된다.
- Grafana `Codex Operations Alerting` 대시보드가 보인다.
- 현재 로컬 스택처럼 normalizer를 주기 실행하지 않으면 data gap alert가 `pending` 또는 `firing`으로 올라온다.

상세 절차는 [docs/RUNBOOK-TASK-6.md](docs/RUNBOOK-TASK-6.md)를 참고한다.

## 15. TASK-8 로컬 검증 절차

```bash
make task8-schema
make task8-sample-mixed
make task8-normalize
python3 scripts/calculate_costs.py compute-daily --date $(date +%Y-%m-%d)
```

확인 포인트:

- PostgreSQL `codex_local_helper_events`에 helper event가 중복 없이 적재된다.
- `codex_prompt_turns_dashboard`에서 prompt length, output token, tool failure, retry proxy, estimated cost를 함께 볼 수 있다.
- `codex_prompt_sessions_dashboard`에서 고비용 세션과 실패 turn 비율을 볼 수 있다.
- Grafana `Codex Prompt Efficiency`에서 bucket 분석, 고비용 세션, 반복 실패 패턴, 개선 후보 turn이 보인다.

상세 절차는 [docs/RUNBOOK-TASK-8.md](docs/RUNBOOK-TASK-8.md)를 참고한다.

## 16. 참고 문서

- OpenAI Codex Advanced Configuration
  - https://developers.openai.com/codex/config-advanced#observability-and-telemetry
- OpenAI Codex Configuration Reference
  - https://developers.openai.com/codex/config-reference
