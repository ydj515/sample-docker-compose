# 배포 체크리스트

## 목적

현재 `llm-monitoring` 스택을 배포하거나 재배포할 때 필요한 절차를 체크리스트 형태로 정리한다.

이 문서는 아래 변경 사항을 반영한다.

- PostgreSQL init을 CSV seed 기반으로 정리
- canonical user 대표 이메일과 Codex alias 이메일 분리
- `dj.yoo-primary` ingest token 발급 및 Codex 설정 반영
- `ops-exporter`를 Python HTTP 서버 기반으로 전환
- `ops-exporter` `/metrics`, `/healthz` 직접 점검 절차 추가

---

## 1. 배포 전 준비

- [ ] 작업 브랜치와 배포 대상 커밋을 확정했다.
- [ ] `.env` 또는 배포 환경 변수 값을 최종 점검했다.
- [ ] 사용자 seed CSV가 최신 상태인지 확인했다.
  - 파일: `configs/user-mapping-sample.csv`
  - 대표 이메일: `example@example.com`
  - Codex alias: `example.1@example.com`, `example.2@example.com`
- [ ] 필요한 Docker 이미지 빌드 권한과 호스트 포트 사용 가능 여부를 확인했다.

---

## 2. 데이터 초기화 여부 결정

### 2.1 완전 초기화가 필요한 경우

- [ ] 기존 로컬/운영 데이터를 모두 비워도 되는지 확인했다.
- [ ] 아래 명령으로 compose 리소스와 named volume을 정리했다.

```bash
docker compose down -v
```

### 2.2 데이터 유지가 필요한 경우

- [ ] `down -v`를 사용하지 않고 재배포 계획을 따로 세웠다.
- [ ] 기존 PostgreSQL volume 재사용 시 init SQL이 자동 재실행되지 않는 점을 인지했다.

> 운영 환경에서는 `docker compose down -v`가 곧 데이터 삭제이므로, 백업 없이 실행하면 안 된다.

---

## 3. PostgreSQL 초기화 확인

- [ ] `configs/postgres/init` 스크립트가 최신인지 확인했다.
- [ ] `configs/user-mapping-sample.csv`가 Postgres 컨테이너에 마운트되도록 compose 설정을 확인했다.
- [ ] 전체 스택 또는 `postgres`를 기동했다.

```bash
docker compose up -d
```

- [ ] canonical user seed가 정상 반영됐는지 확인했다.

```bash
docker compose exec -T postgres \
  psql -U codex -d codex_observability -At \
  -c "select user_id, email, team, department, active from codex_user_mapping order by user_id;"
```

- [ ] alias mapping seed가 정상 반영됐는지 확인했다.

```bash
docker compose exec -T postgres \
  psql -U codex -d codex_observability -At \
  -c "select user_email, resolved_user_id, team, department, is_active, source from codex_user_email_mapping order by user_email;"
```

기대값:

- `example | example@example.com | backend | Engineering | true`
- `example.1@example.com -> example`
- `example.2@example.com -> example`

---

## 4. Ingest Token 발급 및 적용

- [ ] canonical 사용자용 ingest token을 발급했다.

```bash
docker compose exec -T cron-scheduler \
  python3 scripts/manage_ingest_tokens.py issue \
  --postgres-host postgres \
  --ingest-token-id dj.yoo-primary \
  --resolved-user-id dj.yoo \
  --resolved-team backend \
  --description "primary Codex token for DJ Yoo"
```

- [ ] 출력된 `raw_token`을 안전한 비밀 저장소에 저장했다.
- [ ] `~/.codex/config.toml`의 OTLP logs/metrics/traces header를 새 token 값으로 교체했다.
- [ ] 새 Codex 세션 또는 재시작 후 이 토큰이 실제로 사용되는지 확인했다.

---

## 5. 서비스 기동 확인

- [ ] `docker compose ps`에서 주요 서비스가 모두 `Up` 상태다.
  - `postgres`
  - `ingest-gateway`
  - `otel-collector`
  - `loki`
  - `prometheus`
  - `tempo`
  - `ops-exporter`
  - `cron-scheduler`
  - `grafana`
  - `alertmanager`

- [ ] 주요 health endpoint가 응답한다.

```bash
curl -fsS http://localhost:4318/healthz
curl -fsS http://localhost:13133
curl -fsS http://localhost:9090/-/healthy
curl -fsS http://localhost:9093/-/healthy
curl -fsS http://localhost:3000/api/health
curl -fsS http://localhost:9107/healthz
```

- [ ] `ops-exporter` metrics endpoint가 응답한다.

```bash
curl -fsS http://localhost:9107/metrics | head -n 20
```

---

## 6. Grafana / Datasource / Dashboard 확인

- [ ] Grafana 로그인 페이지에 접속된다.
  - `http://localhost:3000`
- [ ] datasource provisioning이 완료됐다.
  - `Prometheus`
  - `Loki`
  - `Tempo`
  - `PostgreSQL`
  - `Alertmanager`
- [ ] 주요 dashboard가 보인다.
  - `Collector Health`
  - `Codex Operations Alerting`
  - `Cost Analysis`
  - `User-Team Enrichment`

---

## 7. End-to-End Telemetry 확인

- [ ] 샘플 OTEL 이벤트를 새 token으로 전송했다.

```bash
python3 scripts/send_sample_otel.py \
  --base-url http://localhost:4318 \
  --ingest-token '<RAW_TOKEN>' \
  --environment production \
  --team backend \
  --user-id example.1@example.com \
  --repository sample-docker-compose/llm-monitoring \
  --project llm-monitoring \
  --session-id session-e2e-dj-yoo-1 \
  --conversation-id conv-e2e-dj-yoo-1 \
  --model gpt-5.4 \
  --response-id resp-e2e-dj-yoo-1 \
  --tool web.search \
  --tool-call-id toolcall-e2e-dj-yoo-1 \
  --tool-duration-ms 420 \
  --tool-output-size 2048 \
  --fn-call-item-id toolcall-e2e-dj-yoo-1 \
  --fn-call-arguments '{"query":"grafana health check"}' \
  --api-request-duration-ms 280 \
  --api-request-status-code 200 \
  --input-tokens 1200 \
  --cached-input-tokens 300 \
  --output-tokens 240 \
  --reasoning-tokens 40 \
  --total-tokens 1440
```

- [ ] scheduler가 usage/tool/api 정규화를 수행했는지 로그로 확인했다.
- [ ] PostgreSQL에서 `dj.yoo-primary` 기준으로 canonical identity가 들어갔는지 확인했다.

```bash
docker compose exec -T postgres \
  psql -U codex -d codex_observability -At \
  -c "select response_id, observed_user_email, resolved_user_id, resolved_team, ingest_token_id, total_tokens from codex_usage_events_dashboard where ingest_token_id = 'dj.yoo-primary' order by event_time desc limit 10;"
```

기대값:

- `observed_user_email`은 alias 이메일
- `resolved_user_id = dj.yoo`
- `resolved_team = backend`
- `ingest_token_id = dj.yoo-primary`

---

## 8. 운영 메트릭 확인

- [ ] `ops-exporter /healthz`가 `200 OK`를 반환한다.
- [ ] `ops-exporter /metrics`에서 아래 메트릭이 노출된다.
  - `codex_ops_exporter_render_success`
  - `codex_team_budget_usage_ratio`
  - `codex_job_last_run_success`
  - `codex_store_usage_ratio`
- [ ] Prometheus target에서 `codex-ops-exporter`가 `up` 상태다.
- [ ] `Codex Operations Alerting` 대시보드에 freshness / cost / store usage 패널이 보인다.

---

## 9. 배포 후 점검

- [ ] `cron-scheduler`가 1회 이상 정상 루프를 수행했다.
- [ ] `compute-daily`가 성공해서 비용 집계가 갱신됐다.
- [ ] Grafana에서 dashboard 쿼리 에러가 없는지 확인했다.
- [ ] Alertmanager에 의도하지 않은 `firing` alert가 없는지 확인했다.

---

## 10. 롤백 포인트

- [ ] `~/.codex/config.toml` 변경 전 백업이 있다.
- [ ] ingest token 원문은 별도 비밀 저장소에 있다.
- [ ] 필요 시 `docker compose down` 후 이전 이미지/설정으로 되돌릴 수 있다.
- [ ] 필요 시 PostgreSQL volume 백업 또는 dump 복원 절차가 준비돼 있다.

> `ops-exporter`는 이제 Python HTTP 서버 기반이므로, 이전 `nc` 기반 구현으로 롤백하려면 이미지 정의와 compose 설정을 함께 되돌려야 한다.
