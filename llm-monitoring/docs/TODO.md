# PRD: Codex 사용 통계 및 비용 관측 시스템

Codex CLI 사용량, 모델별 토큰 사용량, tool 사용 패턴, 팀별 비용을 중앙에서 관측하는 시스템.

---

## Task 목록

개발 순서에 따라 순차적으로 진행한다.

| 순서 | 파일 | Phase | 내용 | 우선순위 | 현재 상태 |
|------|------|-------|------|----------|----------|
| 1 | [TASK-1.md](./TASK-1.md) | Phase 0 | 사전 검증 및 정책 정의 | P0 | 문서 정리 완료 |
| 2 | [TASK-2.md](./TASK-2.md) | Phase 1 | MVP 수집 파이프라인 구축 | P0 | 로컬 기술 검증 완료 |
| 3 | [TASK-3.md](./TASK-3.md) | Phase 2 | Token Usage 정규화 및 Dashboard 구축 | P0 | 로컬 기술 검증 완료 |
| 4 | [TASK-4.md](./TASK-4.md) | Phase 3 | Tool Usage 및 병목 분석 | P0 | 로컬 기술 검증 완료 |
| 5 | [TASK-5.md](./TASK-5.md) | Phase 4 | Cost 계산 및 정산용 데이터 모델 구축 | P1 | 로컬 기술 검증 완료 |
| 6 | [TASK-6.md](./TASK-6.md) | Phase 5 | 운영 안정화 및 알림 | P1 | 로컬 alerting 및 scheduler 검증 완료, RBAC/HA 후속 |
| 7 | [TASK-7.md](./TASK-7.md) | Phase 6 | Trace 기반 병목 분석 고도화 | P2 | 로컬 기술 검증 및 sampling/approval 정책 정의 완료 |
| 8 | [TASK-8.md](./TASK-8.md) | Phase 7 | 프롬프트 개선 분석 고도화 | P2 | 로컬 기술 검증 완료, local helper fan-out/approval hook 후속 |

---

## MVP 범위 (TASK-1 ~ TASK-4)

반드시 제공해야 하는 기능:

- Codex OTel 수집
- 사용자/팀 식별
- 모델별 요청 수 및 token 사용량
- 팀별 token 사용량
- tool별 호출 수, 실패율, p95 duration
- raw event 검색
- 프롬프트 원문 미수집

---

## TASK-8 후속 Local Helper 고도화

`TASK-7`과 `TASK-8`의 본 구현은 완료했지만, local helper는 아래 항목을 후속 고도화로 계속 추적한다.

- `notify` fan-out 또는 wrapper
  - 기존 `notify = [...]` 사용자 환경을 덮어쓰지 않도록 개선
- approval lifecycle hook
  - `approval_requested`, `approval_completed`, `approval_outcome`
- human approval wait time 계산
  - helper lifecycle pair가 쌓인 뒤 Phase 6/7 대시보드와 연결
- opt-in prompt snippet sampling 검토
  - 기본 비활성 유지
  - redaction 정책과 접근 제어가 선행되어야 함

---

## 로컬 참조 스택

문서와 함께 제공하는 `docker-compose.yml`은 로컬 검증용 기준 환경이다.

| 서비스 | 역할 | 기본 포트 | 영속 볼륨 | 비고 |
|--------|------|----------|----------|------|
| OTel Collector | OTLP 수집 및 fan-out | 4317, 4318, 13133 | 없음 | Codex CLI 진입점 |
| Loki | raw log 검색 | 3100 | `loki-data` | Phase 1 필수 |
| Prometheus | metrics 저장/조회 | 9090 | `prometheus-data` | remote write receiver 활성화 필요 |
| Grafana | 통합 조회 UI | 3000 | `grafana-data` | datasource 자동 프로비저닝 |
| Alertmanager | alert 확인 | 9093 | `alertmanager-data` | Phase 1 로컬 검증용 포함 |
| Tempo | trace 저장/조회 | 3200 | `tempo-data` | 로컬 검증 편의를 위해 포함, 운영 필수는 Phase 6부터 |
| PostgreSQL | 정규화/비용 데이터 저장 | 5432 | `postgres17-data` | 운영 필수는 Phase 4부터 |
| Operations Exporter | 운영 메트릭 노출 | 9107 | 없음 | Phase 5 alert rule용 |

---

## 데이터 저장 및 Retention 기준

| 데이터 분류 | 저장소 | 기본 보관 기간 | 삭제 방식 | 백업 정책 |
|------------|--------|---------------|----------|----------|
| Raw OTel 로그 | Loki | 14일 | Loki compactor retention | 백업 없음 |
| Metrics | Prometheus | 180일 | TSDB retention flag | 필요 시 snapshot |
| Traces | Tempo | 7일 | Tempo block retention | 백업 없음 |
| 정규화 usage row | PostgreSQL | 365일 | 일 단위 purge job + 월 파티션 drop | 일 1회 logical backup |
| `raw_event` JSON | PostgreSQL | 30일 | column null 처리 또는 별도 raw table purge | 백업 제외 권장 |
| 일별/월별 비용 집계 | PostgreSQL | 365일 | 월 단위 purge | 일 1회 logical backup |
| 프롬프트 원문 | 저장 안 함 | 0일 | 수집 금지 | 해당 없음 |

### 운영 기준

- `raw_event`는 redaction 이후에만 저장한다.
- `raw_event`와 정규화 row의 보관 기간은 분리한다.
- Loki, Prometheus, Tempo는 로컬 디스크 사용률 70%에서 경고, 85%에서 긴급 알림을 건다.
- PostgreSQL은 월 파티션 기준으로 운영하고, retention job 실패 자체도 알림 대상으로 본다.
- 비용 집계 데이터는 정산 재현성을 위해 가격 정책 버전과 함께 보관한다.

---

## 비목표

- OpenAI 공식 billing system 대체 불가
- 실제 청구 금액과 100% 일치하는 정산 시스템
- 사용자별 Codex 사용 실시간 차단
- 팀별 예산 초과 시 자동 차단 (초기 제외)
- Codex 내부 동작 수정

---

## 리스크 요약

| 리스크 | 설명 | 대응 |
|--------|------|------|
| cached token 미수집 | Codex OTel payload에 cached token이 없을 수 있음 | MVP에서는 unknown 처리, 추후 확장 |
| cost 불일치 | 실제 OpenAI 청구 금액과 추정 비용이 다를 수 있음 | Estimated로 명시, 추후 billing data와 reconcile |
| 프롬프트 민감정보 유출 | 프롬프트 원문에 내부 정보 포함 가능 | 기본 미수집, redaction, 접근 제한 |
| 사용자 식별 어려움 | Codex 기본 metadata만으로 사용자 구분이 어려울 수 있음 | OTLP token별 user/team mapping |
| metric cardinality 증가 | user/repo/tool label 증가로 metric 폭증 가능 | label 제한, cost 데이터는 DB 집계 |
| raw log 비용 증가 | Loki 저장량 증가 가능 | retention 단축, sampling |
| 가격표 변경 | 모델 가격 변경 시 과거 비용 재계산 필요 | price policy version 관리 |
| retention 미적용 | 저장소별 삭제 주체가 달라 실제 보관 기간이 정책과 어긋날 수 있음 | 저장소별 retention 설정값과 purge job owner를 명시 |
