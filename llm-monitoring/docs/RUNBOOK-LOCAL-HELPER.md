# RUNBOOK: Codex Local Helper 설치 및 운영

## 목적

Codex telemetry만으로 직접 수집하기 어려운 로컬 컨텍스트를 `local helper`로 보강한다.

현재 MVP helper의 목적은 아래 두 가지다.

- repository / git context / turn summary를 중앙 OTLP stack으로 보강
- 향후 approval lifecycle 정밀 측정을 위한 로컬 확장 지점을 마련

---

## 현재 구현 범위

- `notify` payload를 받아 `codex.local_helper_context` OTLP log를 전송한다.
- `~/.codex/config.toml`의 OTel logs endpoint와 `x-codex-ingest-token` header를 재사용한다.
- prompt 원문, assistant 원문, tool output 원문은 수집하지 않는다.

현재 MVP는 `notify` 기반이므로 `agent-turn-complete` 요약 이벤트 수집에 초점을 둔다.

정밀 approval lifecycle은 후속 단계에서 같은 helper에 experimental hooks 또는 별도 로컬 이벤트 소스를 연결해 확장한다.

---

## 설치 파일

- helper script: `scripts/codex_local_helper.py`
- install script: `scripts/install_codex_local_helper.sh`
- helper config 예시: `examples/codex.local-helper.toml.example`

---

## 수집 항목

### 기본 수집 항목

| 항목 | 설명 |
|------|------|
| `notification_type` | 현재 notify payload type |
| `thread_id` | Codex thread 식별자 |
| `turn_id` | Codex turn 식별자 |
| `cwd` | 현재 작업 디렉터리, 기본값은 `$HOME` 축약 처리 |
| `is_git` | git 저장소 내부 실행 여부 |
| `repo_root` | 저장소 루트 경로, 기본값은 `$HOME` 축약 처리 |
| `repo_name` | 저장소 이름 |
| `git_branch` | 현재 branch |
| `git_remote_slug` | remote URL 원문이 아닌 `org/repo` slug |
| `host_name` | 로컬 호스트명 |
| `input_message_count` | turn 입력 메시지 개수 |
| `input_message_char_count` | 입력 메시지 총 문자 수 |
| `last_assistant_message_char_count` | 마지막 assistant 메시지 문자 수 |
| `helper_version` | helper 버전 |

### 기본 미수집 항목

| 항목 | 정책 |
|------|------|
| prompt 원문 | 미수집 |
| assistant 원문 | 미수집 |
| tool output 원문 | 미수집 |
| 파일 내용 | 미수집 |
| remote URL 원문 | 미수집, slug만 수집 |

### 후속 수집 예정 항목

| 항목 | 비고 |
|------|------|
| `approval_requested_at` | notify만으로는 부족, hook 또는 별도 로컬 이벤트 필요 |
| `approval_completed_at` | 동일 |
| `approval_outcome` | 동일 |
| `approval_wait_ms` | 위 두 이벤트가 모두 있어야 계산 가능 |

---

## 설치 절차

### 1. helper 설치

```bash
bash scripts/install_codex_local_helper.sh
```

기본 설치 위치:

- helper script: `~/.codex/local-helper/codex-local-helper.py`
- helper config: `~/.codex/codex-local-helper.toml`
- notify fan-out script: `~/.codex/local-helper/codex-notify-fanout.py`
- notify fan-out config: `~/.codex/codex-notify-fanout.json`

### 2. helper 설정 검토

설치 후 아래 파일을 확인한다.

```bash
sed -n '1,120p' ~/.codex/codex-local-helper.toml
```

기본값은 privacy 우선이다.

- `include_raw_cwd = false`
- `redact_home_prefix = true`
- `include_git_remote_slug = true`

### 3. Codex notify 설정 추가

install script가 출력한 top-level `notify = [...]` snippet을 `~/.codex/config.toml`에 추가한다.

예시:

```toml
notify = [
  "/usr/bin/env",
  "python3",
  "/Users/you/.codex/local-helper/codex-notify-fanout.py",
  "--config",
  "/Users/you/.codex/codex-notify-fanout.json",
]
```

현재 install script는 기존 `notify = [...]`를 읽어 `codex-notify-fanout.json`에 함께 넣는다. 따라서 기존 notifier와 local helper를 동시에 유지하는 것이 기본 경로다.

### 4. Codex 세션 재시작

새로운 Codex 세션을 시작해야 notify 설정이 반영된다.

### 5. dry-run 확인

실제 전송 전에 helper가 어떤 OTLP payload를 만들지 보고 싶으면:

```bash
python3 ~/.codex/local-helper/codex-local-helper.py \
  --config ~/.codex/codex-local-helper.toml \
  --dry-run \
  '{"type":"agent-turn-complete","thread-id":"thread-demo","turn-id":"turn-demo","cwd":"'"$PWD"'","input-messages":["hello"],"last-assistant-message":"done"}'
```

### 6. 전송 확인

위 `--dry-run`에서 `--dry-run`을 빼고 실행하면 실제 OTLP logs endpoint로 helper event를 보낸다.

Loki에서 아래 문자열로 검색하면 된다.

```text
codex.local_helper_context
```

예시 query:

```bash
curl -sS 'http://localhost:3100/loki/api/v1/query_range?query=%7Bservice_name%3D%22codex-local-helper%22%7D&limit=20&since=5m'
```

확인 포인트:

- `event_name=codex.local_helper_context`
- `resolved_user_id`
- `resolved_team`
- `repo_name`
- `git_branch`
- `input_message_count`

---

## 운영 메모

- helper는 `~/.codex/config.toml`의 logs endpoint와 `x-codex-ingest-token` header를 재사용한다.
- 따라서 Codex와 helper는 같은 `resolved_user_id`, `resolved_team` identity 경로를 공유할 수 있다.
- helper 전송 실패가 Codex 본체 실행을 막으면 안 되므로 기본 동작은 fail-open이다.
- strict 모드가 필요하면 `--strict`로 실행해 non-zero 종료를 받을 수 있다.

---

## 현재 한계

- 현재 MVP는 `notify` 기반 `agent-turn-complete` 수집만 구현한다.
- 따라서 human approval wait time은 아직 직접 계산할 수 없다.
- 정확한 approval lifecycle은 같은 helper에 hook 기반 또는 별도 로컬 이벤트 수집 경로를 추가해야 한다.

---

## 참고 문서

- OpenAI Codex Advanced Configuration
  - Notifications / Hooks / project config 관련 설명 참고
  - https://developers.openai.com/codex/config-advanced
