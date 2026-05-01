# TASK-6: Phase 5 - 운영 안정화 및 알림

## 목표

수집 파이프라인의 안정성을 높이고 비용/장애 알림을 구성한다.

현재 이 저장소에는 로컬 검증 가능한 alerting 구현이 포함되어 있다. `cron-scheduler`를 통해 usage/tool/API request 정규화와 비용 계산, retention job까지 주기 실행된다. 다만 운영 RBAC와 Collector HA는 후속 작업으로 남겨둔다.

---

## 알림 요구사항

### 비용 알림

| ID | 조건 | 알림 대상 |
|----|------|----------|
| ALERT-001 | 팀 월 예산의 70% 초과 | 팀 리드 |
| ALERT-002 | 팀 월 예산의 90% 초과 | 팀 리드, 관리자 |
| ALERT-003 | 특정 사용자의 일 비용이 임계치 초과 | 팀 리드 |
| ALERT-004 | 회사 전체 일 비용이 임계치 초과 | 관리자 |

### 품질/장애 알림

| ID | 조건 | 알림 대상 |
|----|------|----------|
| ALERT-005 | tool 실패율 10% 이상 | 플랫폼 담당자 |
| ALERT-006 | API 요청 실패율 5% 이상 | 플랫폼 담당자 |
| ALERT-007 | tool p95 duration 임계치 초과 | 플랫폼 담당자 |
| ALERT-008 | OTel Collector 수집 중단 | 플랫폼 담당자 |
| ALERT-009 | Loki/Prometheus/Mimir 저장 실패 | 플랫폼 담당자 |

### 현재 구현 상태

| Alert ID | 현재 상태 | 비고 |
|----------|----------|------|
| ALERT-001 | 구현 완료 | `CodexTeamBudgetWarning` |
| ALERT-002 | 구현 완료 | `CodexTeamBudgetCritical` |
| ALERT-003 | 구현 완료 | `CodexUserDailyCostHigh` |
| ALERT-004 | 구현 완료 | `CodexCompanyDailyCostHigh` |
| ALERT-005 | 구현 완료 | `CodexToolFailureRateHigh` |
| ALERT-006 | 구현 완료 | `CodexApiFailureRateHigh`, `codex_api_recent_failure_rate_ratio` |
| ALERT-007 | 구현 완료 | `CodexToolP95DurationHigh` |
| ALERT-008 | 구현 완료 | `OTelCollectorDown` 재사용 |
| ALERT-009 | 부분 구현 | Prometheus TSDB, Tempo retention, Loki retention stale 기준 구현. Mimir는 현재 스택 비포함 |

---

## 보안 정책 (운영 적용)

### 기본 원칙

- 프롬프트 원문은 기본 수집하지 않는다.
- tool output 원문도 기본 수집하지 않는다.
- token, model, tool, duration, success/failure 중심으로 수집한다.
- 사용자 식별자는 내부 ID 또는 해시값 사용을 우선한다.
- dashboard 접근 권한은 역할 기반으로 제한한다.
- 민감정보가 들어갈 수 있는 raw_event는 retention을 짧게 가져간다.

### 데이터 보관 기간

| 데이터 | 보관 기간 |
|--------|----------|
| Metrics | 6개월 |
| Aggregated Cost | 1년 |
| Raw Logs | 14일 ~ 30일 |
| Traces | 7일 ~ 14일 |
| Raw Prompt | 기본 미수집 |
| Redacted Event | 30일 |

### 저장소별 운영 적용 방식

| 저장소 | 적용 방식 | 목표 보관 기간 | 경보 기준 |
|--------|----------|---------------|----------|
| Loki | compactor retention | 14일 | 디스크 70% 경고, 85% 긴급 |
| Prometheus | TSDB retention flag | 180일 | 디스크 70% 경고, 85% 긴급 |
| Tempo | block retention | 7일 | 디스크 70% 경고, 85% 긴급 |
| PostgreSQL raw_event | purge/null job | 30일 | job 실패 시 즉시 알림 |
| PostgreSQL normalized rows | partition drop | 365일 | 파티션 생성/삭제 실패 알림 |

### 운영 체크포인트

- retention 설정값이 문서, 설정 파일, 실제 런타임 플래그에서 일치하는지 월 1회 점검
- backup 대상은 PostgreSQL의 정규화/집계 테이블로 제한하고 Loki/Tempo raw 저장소는 기본 백업 대상에서 제외
- retention job 실행 결과를 로그가 아니라 메트릭으로 노출해 알림 연동
- 운영자가 수동으로 raw 보관 기간을 늘릴 수 없도록 변경 절차를 문서화

---

## Dashboard 요구사항

### Overview Dashboard

회사 전체 Codex 사용 현황을 한눈에 확인한다.

**패널**

- 전체 요청 수
- 전체 token 사용량
- 전체 추정 비용
- 모델별 token 사용량
- 모델별 추정 비용
- 팀별 추정 비용 Top 10
- 사용자별 사용량 Top 10
- tool 호출 수 Top 10
- tool 실패율 Top 10
- tool p95 duration Top 10

### Operations Alerting Dashboard

운영자가 alert 상태와 pipeline freshness를 한 화면에서 확인한다.

**패널**

- 현재 firing alert 수
- usage 마지막 이벤트 경과 시간
- tool 마지막 이벤트 경과 시간
- 오늘 회사 전체 추정 비용
- 팀별 예산 사용률
- 최근 tool 실패율
- 저장소 사용률
- retention job 마지막 성공 경과
- 현재 firing alert 상세

---

## 주요 Task

| Task ID | Task | 담당 | 우선순위 |
|---------|------|------|----------|
| P5-T01 | Collector HA 구성 | Platform | P1 |
| P5-T02 | Loki retention 설정 | Platform | P0 |
| P5-T03 | Metrics retention 설정 | Platform | P0 |
| P5-T04 | raw event retention 설정 | Security/Platform | P0 |
| P5-T05 | Grafana folder 권한 설정 | Platform/Security | P1 |
| P5-T06 | 팀별 dashboard 권한 분리 | Platform/Security | P1 |
| P5-T07 | 비용 임계치 alert 구성 | Platform | P1 |
| P5-T08 | token usage anomaly alert 구성 | Platform | P2 |
| P5-T09 | tool failure alert 구성 | Platform | P1 |
| P5-T10 | Collector down alert 구성 | Platform | P0 |
| P5-T11 | 데이터 누락 감지 alert 구성 | Platform | P1 |
| P5-T12 | 운영 runbook 작성 | Platform | P0 |
| P5-T13 | 저장소 디스크 사용률 alert 구성 | Platform | P0 |
| P5-T14 | PostgreSQL retention job 실패 alert 구성 | Platform | P0 |
| P5-T15 | retention 설정 drift 점검 절차 작성 | Platform | P1 |

---

## 산출물

- 운영용 Grafana dashboard
- alert rule
- retention policy
- access control policy
- 운영 runbook

### 현재 구현 산출물

- `configs/prometheus/rules/codex-operations-alerts.yml`
- `configs/postgres/init/005-ops-schema.sql`
- `configs/postgres/init/006-api-request-schema.sql`
- `scripts/task6_ops_exporter.sh`
- `scripts/normalize_api_request_events.py`
- `scripts/run_scheduler.py`
- `Dockerfile.scheduler`
- `configs/grafana/dashboards/operations-alerting.json`
- `docs/RUNBOOK-TASK-6.md`

---

## 완료 기준

- [x] Collector 장애 시 알림 rule이 구성되어 있다.
- [x] 팀 비용이 임계치를 넘으면 알림 rule이 발생할 수 있다.
- [x] tool 실패율이 임계치를 넘으면 알림 rule이 발생할 수 있다.
- [ ] dashboard 접근 권한이 분리된다.
- [x] retention 정책 값이 메트릭과 rule에 반영되어 있다.
- [x] 저장소별 사용률 alert가 동작한다.
- [x] PostgreSQL retention job 상태가 메트릭으로 노출되고 알림 rule이 구성되어 있다.
- [x] API 요청 실패율 alert가 동작한다.
- [ ] Collector HA가 구성되어 있다.

## 로컬 검증 결과

- `ops-exporter`가 `codex-ops-exporter` target으로 Prometheus에 scrape된다.
- `Codex Operations Alerting` 대시보드가 Grafana에 자동 프로비저닝된다.
- `compute-daily`, `purge-raw-events`, `drop-old-rows` 실행 후 `codex_job_last_run_success`, `codex_job_last_duration_seconds`가 노출된다.
- `cron-scheduler`가 5분 lookback 기준으로 usage/tool/API request 정규화를 자동 수행한다.
- `CodexUsageDataGapDetected`가 해소되고 usage/tool freshness 메트릭이 1분 이내로 유지되는 것을 확인했다.
- `codex_api_recent_failure_rate_ratio{request_type="websocket_request"} = 0.107143`이 계산되고 `CodexApiFailureRateHigh`가 `pending` 상태로 전환되는 것을 확인했다.

## 후속 보완

- Grafana folder/team RBAC 자동화
- Collector HA / Alertmanager receiver 연계
- 장기 historical backfill용 별도 배치 전략

---

이전 단계: [TASK-5.md](./TASK-5.md) - Phase 4: Cost 계산 및 정산용 데이터 모델 구축

다음 단계: [TASK-7.md](./TASK-7.md) - Phase 6: Trace 기반 병목 분석 고도화
