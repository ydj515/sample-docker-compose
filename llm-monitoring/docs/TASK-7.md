# TASK-7: Phase 6 - Trace 기반 병목 분석 고도화

## 목표

Tempo와 PostgreSQL trace 정규화 레이어를 결합해 Codex 세션 단위 병목을 trace로 분석한다.

---

## 시스템 구성

```text
Codex CLI
  -> OTLP Ingest Gateway
  -> OTel Collector
  -> Tempo
  -> Trace Normalizer
  -> PostgreSQL
  -> Grafana
```

### 현재 구현 범위

- `ingest-gateway`가 trace exporter 경로에도 `resolved_user_id`, `resolved_team`, `ingest_token_id`를 주입한다.
- Loki log normalizer가 `trace_id`, `span_id`를 usage/tool/api/fn_call 정규화 row에 저장한다.
- `normalize_trace_spans.py`가 Tempo recent trace를 읽어 `codex_trace_spans`로 적재한다.
- `codex_trace_log_correlation_dashboard`가 log event와 trace span을 `trace_id/span_id` 우선, 같은 trace fallback 방식으로 연결한다.
- `codex_trace_sessions_dashboard`가 trace 단위 세션 집계와 slowest span 요약을 제공한다.
- `codex_trace_approval_spans_dashboard`가 `op.dispatch.*_approval` span을 별도로 조회할 수 있게 한다.
- Grafana `Codex Trace Analysis` 대시보드가 세션/병목/API/tool/fn_call correlation과 approval span을 조회한다.

### Trace 저장 정책

- 기본 trace retention: 7일
- 운영 상한: 14일
- 현재 Phase 6 운영 정책은 `Tempo raw trace 100% 수집 + PostgreSQL trace 정규화 100% 적재`를 기본값으로 둔다.
- 샘플링 완화 검토 트리거:
  - 일 trace span 100만 건 초과
  - Tempo 저장소 사용률 24시간 이상 70% 초과
  - `normalize-trace-spans` 잡 실행 시간이 3회 연속 300초 초과
- 위 트리거가 발생하면 PostgreSQL 정규화 단계부터 선택적 샘플링을 적용한다.
- 샘플링을 하더라도 아래 trace는 100% 보존한다.
  - `op.dispatch.*_approval` span 포함 trace
  - `codex.tool_result` 실패 trace
  - 세션 duration 30초 이상 trace
  - slowest span duration 3초 이상 trace
  - API failure alert 발생 시간대 trace

### Approval 분석 범위

- 현재 trace에서 실제로 관찰되는 approval span은 아래 두 종류다.
  - `op.dispatch.exec_approval`
  - `op.dispatch.patch_approval`
- 현재 Phase 6에서 측정 가능한 값:
  - approval span 발생 횟수
  - approval span duration
  - approval span이 포함된 trace의 사용자/팀/세션 컨텍스트
- 현재 Phase 6에서 측정 불가능한 값:
  - 사용자가 승인 UI를 본 뒤 실제로 클릭하기까지의 human wait time
  - 거절, 취소, timeout 사유별 대기 시간
  - approval prompt 노출 시각과 승인 완료 시각의 pair metric
- 해석 원칙:
  - 지금의 approval span duration은 사람 대기 시간이 아니라 runtime dispatch overhead로 본다.
  - human wait time 분석은 explicit `approval_requested` / `approval_completed` span pair 또는 별도 local helper event가 있어야 가능하다.
  - 이 저장소는 후속 보강 경로로 `local helper`를 채택한다. 현재 helper MVP는 `notify` 기반 turn-complete context 수집까지 구현하고, approval pair event는 후속 hook 연동 범위로 둔다.

---

## 주요 Task

| Task ID | Task | 담당 | 우선순위 |
|---------|------|------|----------|
| P6-T01 | Tempo 배포 | Platform | P2 | 완료 |
| P6-T02 | trace exporter 구성 | Platform | P2 | 완료 |
| P6-T03 | trace id와 log correlation 구성 | Platform | P2 | 완료 |
| P6-T04 | session 단위 trace 조회 구성 | Platform | P2 | 완료 |
| P6-T05 | slow session dashboard 구성 | Platform | P2 | 완료 |
| P6-T06 | API request span 분석 | Platform | P2 | 완료 |
| P6-T07 | tool call span 분석 | Platform | P2 | 완료 |
| P6-T08 | approval 대기 시간 분석 가능 여부 확인 | Platform | P2 | 완료 |
| P6-T09 | trace sampling 정책 정의 | Platform | P2 | 완료 |
| P6-T10 | trace retention 7일 적용 검증 | Platform | P2 | 완료 |

---

## 산출물

- Tempo datasource
- `codex_trace_spans`, `codex_trace_sync_state`
- `codex_trace_spans_dashboard`
- `codex_trace_log_correlation_dashboard`
- `codex_trace_sessions_dashboard`
- `codex_trace_approval_spans_dashboard`
- Grafana `Codex Trace Analysis`
- `scripts/normalize_trace_spans.py`
- [RUNBOOK-TASK-7.md](./RUNBOOK-TASK-7.md)

---

## 완료 기준

- [x] 특정 Codex 세션의 trace를 조회할 수 있다.
- [x] 느린 세션에서 어떤 단계가 병목인지 확인할 수 있다.
- [x] tool call과 API request의 duration을 span 단위로 확인할 수 있다.
- [x] approval span의 발생 여부와 runtime approval overhead를 구분해 확인할 수 있다.
- [x] trace sampling 운영 정책과 완화 트리거를 문서화했다.

## 검증 메모

- 실제 Codex 세션 trace가 Tempo Search API에서 `service.name=codex_cli_rs` 기준으로 조회됐다.
- 최근 trace span `13,000+`건을 PostgreSQL `codex_trace_spans`로 적재했다.
- `codex_trace_sessions_dashboard` 기준 최근 세션 `30+`건이 조회됐다.
- `codex_trace_log_correlation_dashboard` 기준 tool correlation `155`건, api correlation `42`건이 조회됐다.
- 현재 검증 구간의 `fn_call` correlation은 `0건`이다. 이 구간에서는 실제 `response.function_call_arguments.*` 이벤트가 관찰되지 않았다.
- 실제 approval span `6건`이 조회됐고, duration은 `0~3ms` 범위였다. 따라서 현재는 human wait time이 아니라 dispatch overhead 지표로 해석한다.
- exact span match가 없을 때는 같은 trace 안에서 가장 가까운 span을 fallback으로 매칭한다.

---

이전 단계: [TASK-6.md](./TASK-6.md) - Phase 5: 운영 안정화 및 알림

다음 단계: [TASK-8.md](./TASK-8.md) - Phase 7: 프롬프트 개선 분석 고도화
