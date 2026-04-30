# Ingest Token 운영 Runbook

## 목표

이 문서는 현재 운영 정책인 `사용자 1명당 active ingest token 1개` 기준으로, Codex OTLP gateway용 ingest token을 발급하고 회수하고 재발급하는 절차를 정리한다.

---

## 운영 정책

- canonical 사용자 기준으로 token을 관리한다.
- 현재 기본 정책은 `user당 active token 1개`다.
- 권장 `ingest_token_id` 형식은 `<resolved_user_id>-primary`다.
- 여러 이메일 alias는 token을 여러 개 만드는 대신 `codex_user_email_mapping`으로 canonical 사용자에 매핑한다.
- token 원문은 발급 시 1회만 사용자에게 전달하고, DB에는 hash만 저장한다.
- token 원문은 채팅, 커밋, 문서 본문에 남기지 않고 비밀 저장소에만 보관한다.
- `expires_at`는 현재 조회와 운영 메모용으로만 저장되며, gateway가 자동으로 만료 차단을 하지는 않는다.
- 즉 현재 실제 차단 수단은 `revoke`다.

---

## 사전 준비

아래 정보가 먼저 정해져 있어야 한다.

- `resolved_user_id`
- `resolved_team`
- 필요하면 `codex_user_mapping`의 display name, 대표 이메일, 팀 정보
- 필요하면 `codex_user_email_mapping`의 이메일 alias

예시:

- `resolved_user_id = example`
- `resolved_team = backend`
- 대표 이메일:
  - `example@example.com`
- alias:
  - `example.1@example.com -> example`
  - `example.2@example.com -> example`

---

## 1. 신규 발급

발급 명령:

```bash
docker compose exec -T cron-scheduler \
  python3 scripts/manage_ingest_tokens.py issue \
  --postgres-host postgres \
  --ingest-token-id dj.yoo-primary \
  --resolved-user-id dj.yoo \
  --resolved-team backend \
  --description "primary Codex token for DJ Yoo"
```

출력 예시:

```text
ingest_token_id=dj.yoo-primary
resolved_user_id=dj.yoo
resolved_team=backend
raw_token=...
```

해야 할 후속 작업:

1. `raw_token`을 즉시 안전한 비밀 저장소에 저장한다.
2. 사용자 `~/.codex/config.toml`의 logs/metrics/traces exporter header에 같은 값을 넣는다.
3. 사용자가 새 Codex 세션을 열게 한다.
4. Loki/PostgreSQL/Grafana에서 `resolved_user_id`, `resolved_team`, `ingest_token_id`가 정상 반영되는지 확인한다.

설정 예시:

```toml
[otel]
environment = "production"
log_user_prompt = false

exporter = { otlp-http = {
  endpoint = "https://otel.company.com/v1/logs",
  protocol = "binary",
  headers = { "x-codex-ingest-token" = "USER_SPECIFIC_TOKEN" }
}}

metrics_exporter = { otlp-http = {
  endpoint = "https://otel.company.com/v1/metrics",
  protocol = "binary",
  headers = { "x-codex-ingest-token" = "USER_SPECIFIC_TOKEN" }
}}

trace_exporter = { otlp-http = {
  endpoint = "https://otel.company.com/v1/traces",
  protocol = "binary",
  headers = { "x-codex-ingest-token" = "USER_SPECIFIC_TOKEN" }
}}
```

---

## 2. 조회

현재 발급된 token 목록 조회:

```bash
docker compose exec -T cron-scheduler \
  python3 scripts/manage_ingest_tokens.py list \
  --postgres-host postgres
```

출력 예시:

```text
dj.yoo-primary	dj.yoo	backend	active	-
```

조회 결과로 확인할 것:

- `ingest_token_id`
- `resolved_user_id`
- `resolved_team`
- `status`
- `expires_at`

주의:

- 여기서는 raw token 원문이 다시 보이지 않는다.
- 원문을 잃어버렸다면 조회가 아니라 재발급 절차로 가야 한다.
- `expires_at`가 과거 시각이어도 현재 구현에서는 자동 차단되지 않을 수 있다.

---

## 3. 회수

다음 상황이면 회수한다.

- 사용자 퇴사 또는 권한 제거
- token 유출 의심
- 잘못된 사용자에게 발급
- 계정/팀 매핑 오류로 즉시 차단이 필요

회수 명령:

```bash
docker compose exec -T cron-scheduler \
  python3 scripts/manage_ingest_tokens.py revoke \
  --postgres-host postgres \
  --ingest-token-id dj.yoo-primary
```

회수 후 기대 동작:

- gateway는 해당 token을 더 이상 유효한 것으로 보지 않는다.
- 이후 같은 raw token으로 들어오는 요청은 차단된다.
- 기존 정규화 데이터는 남아 있지만, 새 이벤트는 더 이상 `ingest_token_id` 기준으로 수집되지 않는다.

중요:

- 현재 만료일(`expires_at`) 경과만으로는 같은 수준의 차단이 자동 수행되지 않는다.
- 자동 차단이 필요하면 추후 gateway enforcement를 추가해야 하고, 현재는 `revoke`를 사용해야 한다.

운영 후속 작업:

1. 사용자에게 기존 `~/.codex/config.toml` token이 더 이상 유효하지 않음을 알린다.
2. 필요하면 새 token 재발급 절차로 바로 이어간다.
3. 유출 사고라면 secret manager에 저장된 이전 token도 폐기 표시한다.

---

## 4. 재발급

재발급은 같은 `ingest_token_id`를 유지한 채 raw token만 회전하는 방식으로 처리한다.

명령:

```bash
docker compose exec -T cron-scheduler \
  python3 scripts/manage_ingest_tokens.py issue \
  --postgres-host postgres \
  --ingest-token-id dj.yoo-primary \
  --resolved-user-id dj.yoo \
  --resolved-team backend \
  --description "reissued after loss or rotation"
```

동작 설명:

- 같은 `ingest_token_id`에 대해 새 `raw_token`이 생성된다.
- DB에는 새 `token_hash`가 저장된다.
- 이전 raw token은 즉시 무효화된다.
- `resolved_user_id`, `resolved_team`는 유지된다.

재발급이 필요한 대표 사례:

- 사용자가 token 원문을 잃어버림
- 노트북 분실 또는 화면 노출
- 정기 rotation
- 잘못된 채널에 token을 붙여넣음

재발급 후 체크리스트:

1. 새 `raw_token`을 안전한 비밀 저장소에 기록
2. 사용자 `~/.codex/config.toml`의 3개 header 값 교체
3. 사용자에게 Codex 세션 재시작 안내
4. 최신 이벤트가 새 token으로 수집되는지 확인

---

## 5. 검증

### 5.1 설정 반영 확인

사용자 `~/.codex/config.toml`에 아래 3개가 모두 같은 token인지 본다.

- `exporter`
- `metrics_exporter`
- `trace_exporter`

### 5.2 gateway health 확인

```bash
curl -sS http://localhost:4318/healthz
```

### 5.3 수집 결과 확인

권장 확인 항목:

- PostgreSQL 정규화 row에 `ingest_token_id`가 찍히는지
- `resolved_user_id`, `resolved_team`가 canonical 값으로 들어오는지
- Grafana 대시보드에서 resolved 기준 집계가 보이는지

예시 확인 SQL:

```sql
select
  event_time,
  conversation_id,
  observed_user_email,
  resolved_user_id,
  resolved_team,
  ingest_token_id
from codex_usage_events
order by event_time desc
limit 20;
```

---

## 6. 운영 권장 사항

- token은 사용자별 1개 정책으로 시작하되, 추후 장비별 분리가 필요하면 정책을 별도 개정한다.
- canonical 집계는 항상 `resolved_user_id`, `resolved_team` 기준으로 본다.
- direct telemetry의 `user_email`, `team`은 참고값으로만 사용한다.
- raw token은 절대 DB 조회 기능으로 복구할 수 없다는 점을 온보딩 문서에 명시한다.
- token rotation이 발생해도 `ingest_token_id`는 그대로 유지하는 편이 감사 추적에 유리하다.

---

## 7. 장애 대응 메모

### 증상: 설정은 맞는데 수집이 안 된다

확인 순서:

1. `ingest_token_id`가 `revoke` 상태인지 확인
2. gateway health 확인
3. 사용자 `~/.codex/config.toml`의 3개 exporter header가 모두 같은지 확인
4. Codex 세션을 재시작했는지 확인
5. gateway 로그에서 `403 unknown ingest token` 또는 `401 x-codex-ingest-token header is required`가 보이는지 확인

### 증상: 사용자 이메일은 보이는데 canonical user로 안 묶인다

확인 순서:

1. token mapping에 `resolved_user_id`, `resolved_team`가 정확한지 확인
2. `codex_user_mapping`에 canonical 사용자 row가 있는지 확인
3. 필요하면 `codex_user_email_mapping` alias를 추가
4. 정규화 job이 최근 데이터를 다시 읽었는지 확인
