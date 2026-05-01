# TASK-1: Phase 0 - 사전 검증 및 정책 정의

## 목표

Codex OTel에서 실제로 어떤 필드가 수집되는지 확인하고, 회사의 보안/수집 정책을 정의한다.

---

## 배경

이 Phase는 모든 개발의 전제 조건이다. Codex OTel이 실제로 어떤 payload를 내보내는지 확인하지 않으면, 이후 파이프라인/대시보드 설계가 잘못될 수 있다.

---

## 시스템 구성 (MVP 목표)

```text
Codex CLI
  |
  | OTLP HTTP / gRPC
  v
OpenTelemetry Collector
  |
  +--> Loki
  +--> Prometheus
  |
  v
Grafana
```

---

## 수집 대상 필드 (검증 필요)

### 기본 수집 필드

| 필드 | 설명 |
|------|------|
| event_time | 이벤트 발생 시각 |
| event_name | 이벤트 이름 (예: `codex.sse_event`, `codex.tool_result`) |
| event_kind | 하위 이벤트 종류 (예: `response.completed`) |
| environment | 환경 구분 |
| service_name | 서비스명 |
| codex_version | Codex CLI 버전 |
| user_id | 사용자 식별자 |
| team | 팀 구분 |
| repository | 저장소 경로 |
| project | 프로젝트명 |
| session_id | 세션 ID |
| conversation_id | 대화 ID |
| model | 모델명 |
| auth_mode | 인증 방식 |
| originator | 요청 발신자 |
| approval_policy | 승인 정책 |
| sandbox_policy | 샌드박스 정책 |

### Token Usage 필드 (수집 가능 여부 확인 필요)

| 필드 | 비고 |
|------|------|
| input_tokens | 필수 확인 |
| cached_input_tokens | payload 존재 여부 확인 필요 |
| output_tokens | 필수 확인 |
| reasoning_tokens | payload 존재 여부 확인 필요 |
| total_tokens | 필수 확인 |

> cached_input_tokens, reasoning_tokens는 Codex OTel 이벤트 payload에서 실제 제공되는지 먼저 확인해야 한다. 제공되지 않는 경우 MVP에서는 null로 저장하고, 추후 수집 가능해졌을 때 확장한다.

> OpenAI 공식 문서 기준으로 token 카운트는 `codex.sse_event`에서 `kind=response.completed`일 때 포함될 수 있다. 따라서 `response.completed`를 최상위 event_name으로 가정하면 안 된다.

### Tool Usage 필드

| 필드 | 비고 |
|------|------|
| tool_name | 필수 확인 |
| tool_call_id | 확인 |
| tool_success | 필수 확인 |
| tool_duration_ms | 필수 확인 |
| tool_error_code | 확인 |
| tool_error_message | 확인 |
| tool_output_size | 확인 |

---

## 보안 및 수집 정책

### 기본 원칙

- 프롬프트 원문은 기본 수집하지 않는다.
- tool output 원문도 기본 수집하지 않는다.
- token, model, tool, duration, success/failure 중심으로 수집한다.
- 사용자 식별자는 내부 ID 또는 해시값 사용을 우선한다.
- dashboard 접근 권한은 역할 기반으로 제한한다.
- 민감정보가 들어갈 수 있는 raw_event는 retention을 짧게 가져간다.

### 프롬프트 수집 정책

| 수집 모드 | 설명 | 기본값 |
|----------|------|--------|
| Disabled | 프롬프트 원문 미수집 | 기본 |
| Length Only | 프롬프트 길이만 수집 | 권장 |
| Sampled Raw | 일부 샘플만 원문 수집 | 제한적 허용 |
| Full Raw | 전체 원문 수집 | 비권장 |

### 데이터 보관 기간

| 데이터 | 보관 기간 |
|--------|----------|
| Metrics | 6개월 |
| Aggregated Cost | 1년 |
| Raw Logs | 14일 기본, 최대 30일 |
| Traces | 7일 기본, 최대 14일 |
| Raw Prompt | 기본 미수집 |
| Redacted Event | 30일 |

### 저장소별 적용 기준

| 저장소 | 저장 대상 | 기본 보관 기간 | 삭제 주체 | 추가 정책 |
|--------|----------|---------------|----------|----------|
| Loki | raw OTel logs | 14일 | Loki compactor | prompt/tool output 원문 미저장 |
| Prometheus | metrics | 180일 | TSDB retention flag | label cardinality 주기 점검 |
| Tempo | traces | 7일 | Tempo block retention | Phase 6 이전에는 선택 적용 가능 |
| PostgreSQL | normalized usage rows | 365일 | partition drop + purge job | 월 파티션 권장 |
| PostgreSQL | `raw_event` JSON | 30일 | purge job 또는 null 처리 | redaction 이후 저장 |

### 정책 결정 시 반드시 확정할 항목

- `raw_event`를 별도 테이블로 분리할지, 동일 row 내 JSON 컬럼으로 유지할지
- `raw_event` 30일 경과 후 row 삭제가 아니라 컬럼 null 처리로 갈지 여부
- 팀/사용자 매핑 원본을 Collector 외부 저장소에서 조회할지 여부
- 로컬 개발 환경과 운영 환경의 retention 값을 동일하게 둘지 여부
- 백업 대상에서 제외할 데이터와 반드시 백업할 데이터를 구분할지 여부

---

## 주요 Task

| Task ID | Task | 담당 | 우선순위 |
|---------|------|------|----------|
| P0-T01 | Codex OTel 설정 방식 확인 | Platform | P0 |
| P0-T02 | 샘플 Codex OTel 이벤트 수집 | Platform | P0 |
| P0-T03 | `codex.sse_event`의 `kind=response.completed` payload 확인 | Platform | P0 |
| P0-T04 | token 필드 구조 확인 | Platform | P0 |
| P0-T05 | cached token 필드 존재 여부 확인 | Platform | P0 |
| P0-T06 | reasoning token 필드 존재 여부 확인 | Platform | P1 |
| P0-T07 | tool call 이벤트 구조 확인 | Platform | P0 |
| P0-T08 | model metadata 구조 확인 | Platform | P0 |
| P0-T09 | 사용자/팀 식별 방식 결정 | Platform, Security | P0 |
| P0-T10 | 프롬프트 원문 수집 정책 결정 | Security | P0 |
| P0-T11 | retention 정책 정의 | Security, Platform | P0 |
| P0-T12 | 접근 권한 정책 정의 | Security | P1 |
| P0-T13 | event_name 카탈로그 정의 | Platform | P0 |
| P0-T14 | 저장소별 retention 적용 방식 정의 | Platform, Security | P0 |
| P0-T15 | `raw_event` redaction 규칙 정의 | Security | P0 |
| P0-T16 | purge job owner 및 실패 알림 owner 정의 | Platform | P1 |

---

## 산출물

- Codex OTel sample event 문서
- 수집 가능 필드 목록
- 수집 불가능/확인 필요 필드 목록
- 보안 정책 초안
- 사용자/팀 식별 정책
- 저장소별 retention matrix
- `raw_event` redaction 규칙

---

## 완료 기준

- [ ] 실제 Codex OTel 이벤트를 Loki 또는 파일로 수집했다.
- [ ] 모델명과 token usage 수집 가능 여부를 확인했다.
- [ ] cached token 수집 가능 여부를 확인했다.
- [ ] tool call 이벤트 수집 가능 여부를 확인했다.
- [ ] 프롬프트 원문 수집 기본 정책을 확정했다.
- [ ] 저장소별 retention 기간과 삭제 주체를 문서로 확정했다.
- [ ] `raw_event` 30일 경과 시 처리 방식(null 처리 또는 row 삭제)을 결정했다.

---

다음 단계: [TASK-2.md](./TASK-2.md) - Phase 1: MVP 수집 파이프라인 구축
