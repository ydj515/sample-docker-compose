# TASK-8: Phase 7 - 프롬프트 개선 분석 고도화

## 목표

프롬프트 원문을 저장하지 않더라도, local helper와 기존 usage/tool/api/cost/trace 데이터를 결합해 프롬프트 개선에 필요한 간접 지표를 제공한다.

---

## 시스템 구성

```text
Codex CLI
  -> local helper (notify)
  -> OTLP Ingest Gateway
  -> OTel Collector
  -> Loki
  -> Local Helper Normalizer
  -> PostgreSQL
  -> Grafana
```

### 현재 구현 범위

- `codex.local_helper_context` 이벤트를 Loki에서 PostgreSQL `codex_local_helper_events`로 정규화한다.
- helper의 `thread_id`를 Codex telemetry의 `conversation_id`와 같은 turn window로 묶어 프롬프트 간접 지표를 계산한다.
- `codex_prompt_turns_dashboard`가 turn 단위 prompt length, token, cost, tool failure, API retry proxy를 제공한다.
- `codex_prompt_sessions_dashboard`가 세션 단위 고비용 / 고실패 패턴을 제공한다.
- `codex_prompt_optimization_candidates_dashboard`가 개선 후보 turn을 휴리스틱으로 추린다.
- Grafana `Codex Prompt Efficiency` 대시보드가 bucket 분석, 고비용 세션, 반복 실패 패턴을 조회한다.
- prompt 원문은 여전히 저장하지 않는다.

### 프롬프트 간접 지표 정의

- `prompt length`
  - local helper의 `input_message_char_count`
- `output token`
  - `codex_usage_events_with_cost.output_tokens`
- `tool failure`
  - 같은 turn window의 `codex.tool_result` 실패 건수
- `retry 횟수`
  - 같은 turn window의 `request_type`별 중복 API request를 합산한 proxy
- `high cost session`
  - 세션 단위 `total_estimated_cost_usd`
- `long duration session`
  - 같은 세션에 연결된 trace의 `session_max_trace_duration_ms`

### 해석 원칙

- 현재 `prompt length`는 문자 수 기반 proxy다.
- `estimated_retry_count`는 정확한 SDK retry count가 아니라, 같은 turn window 안에서 반복된 API request 수를 기반으로 한 근사치다.
- turn 상관분석은 `thread_id = conversation_id`와 `이전 helper 이벤트 ~ 현재 helper 이벤트` 윈도우를 사용한다.
- prompt 원문은 저장하지 않으므로 내용 품질은 직접 평가하지 않고, 간접 지표와 패턴만 본다.

### Local Helper 후속 고도화 항목

아래 항목은 `TASK-7`/`TASK-8`의 후속 local helper 고도화로 추적한다.

- `notify` fan-out 또는 wrapper 도입
  - 기존 `notify = [...]` 사용 환경을 덮어쓰지 않도록 개선
- approval lifecycle hook 추가
  - `approval_requested`, `approval_completed`, `approval_outcome`
- human approval wait time 계산
  - 위 lifecycle event가 쌓인 뒤 `approval_wait_ms` 계산
- opt-in prompt snippet sampling 검토
  - 기본값은 계속 비활성
  - 명시적 opt-in과 redaction 정책이 선행되어야 함

---

## 주요 Task

| Task ID | Task | 담당 | 우선순위 | 상태 |
|---------|------|------|----------|------|
| P7-T01 | prompt length 수집 | Backend/Platform | P2 | 완료 |
| P7-T02 | prompt length와 output token 상관관계 분석 | Data/Platform | P2 | 완료 |
| P7-T03 | prompt length와 tool failure 상관관계 분석 | Data/Platform | P2 | 완료 |
| P7-T04 | 반복 실패 패턴 분석 | Data/Platform | P2 | 완료 |
| P7-T05 | 고비용 세션 패턴 분석 | Data/Platform | P2 | 완료 |
| P7-T06 | prompt 원문 샘플링 정책 검토 | Security | P3 | 후속 |
| P7-T07 | redaction pipeline 구현 | Platform/Security | P3 | 후속 |
| P7-T08 | prompt 개선 가이드 작성 | Developer Experience | P2 | 완료 |
| P7-T09 | local helper notify fan-out | Platform | P3 | 후속 |
| P7-T10 | approval pair event hook | Platform | P3 | 후속 |

---

## 산출물

- `configs/postgres/init/011-task8-prompt-efficiency-schema.sql`
- `scripts/normalize_local_helper_events.py`
- `codex_local_helper_events`, `codex_local_helper_sync_state`
- `codex_prompt_turns_dashboard`
- `codex_prompt_sessions_dashboard`
- `codex_prompt_optimization_candidates_dashboard`
- Grafana `Codex Prompt Efficiency`
- [RUNBOOK-TASK-8.md](./RUNBOOK-TASK-8.md)
- [PROMPT-WRITING-GUIDE.md](./PROMPT-WRITING-GUIDE.md)

---

## 완료 기준

- [x] prompt length와 token 사용량 관계를 bucket 단위로 확인할 수 있다.
- [x] 고비용 세션 패턴을 세션 테이블에서 확인할 수 있다.
- [x] 실패율 높은 사용 패턴과 retry proxy를 확인할 수 있다.
- [x] 프롬프트 개선 가이드 초안이 작성된다.
- [x] prompt 원문을 저장하지 않는다는 기본 정책이 유지된다.

## 검증 메모

- local helper 이벤트가 PostgreSQL `codex_local_helper_events`에 중복 없이 적재된다.
- `codex_prompt_turns_dashboard`가 helper turn과 usage/tool/api/cost를 같은 window로 묶는다.
- `Codex Prompt Efficiency` 대시보드가 Grafana에 자동 프로비저닝된다.
- high cost session, 반복 실패 turn, optimization candidate를 SQL view에서 직접 조회할 수 있다.
- `prompt length`는 raw text가 아니라 `input_message_char_count` proxy라는 점을 문서에 명시했다.

---

이전 단계: [TASK-7.md](./TASK-7.md) - Phase 6: Trace 기반 병목 분석 고도화
