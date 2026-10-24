# agentgateway

agentgateway v1.6.0으로 MCP 프록시, 정책, 인증과 연결 보안을 실습합니다.
MCP·Mock A2A 서버는 저장소의 소스로 직접 빌드합니다. 실제 LLM 정책 검증은 보류 상태입니다.

## 시작하기

| 모드 | 구성 | 기본 MCP | UI |
| --- | --- | --- | --- |
| [single 실행](single/README.md) | Gateway 1개 + MCP 서버 | `localhost:3000/mcp` | `localhost:4000/ui` |
| [HA 실행](ha/README.md) | Nginx + Gateway 2개 + MCP 서버 | `localhost:13000/mcp` | `localhost:14001/ui`, `localhost:14002/ui` |

처음에는 각 모드 README의 준비·기동·검증 순서대로 실행합니다.
정책 실습으로 전환하려면 [Compose 파일 선택 안내](docs/COMPOSE.md)에서 설정과 추가 파일 조합을 고릅니다.
두 모드는 Compose 프로젝트명과 기본 포트가 달라 동시에 실행할 수 있습니다. 같은 모드 안의 실습은 전환 실행합니다.

HA는 Gateway 프로세스 1개 장애를 실습합니다. 단일 호스트·Nginx·MCP 서버는 각각 단일 장애 지점입니다.

## 실습 권장 순서

single 기본 → 정책·API Key → 요청 처리 → HA·공유 제한 → TLS·mTLS → 외부 인가·OAuth → 통합 인증 → 갱신·장애 순서로 진행합니다.
각 단계의 선행 조건과 통과 기준은 [실습 권장 순서](docs/LEARNING-PATH.md)를 참고하세요.

## 목적별 문서

| 확인할 내용 | 문서 |
| --- | --- |
| Compose 파일의 용도, 조합 순서, 포트, 복원 | [Compose 안내](docs/COMPOSE.md) |
| 완료·보류 상태와 검증 범위 | [정책 실습 로드맵](POLICY-ROADMAP.md) |
| Rate limit·도구 권한·복합 정책 | [정책 실습](shared/POLICIES.md) |
| 조건부 선택·적용 단계·API Key 충돌 | [선택 순서](docs/POLICY-ORDER.md), [적용 단계](docs/POLICY-STAGES.md), [API Key](docs/API-KEY.md) |
| Timeout·Retry·변환·미러링 | [Timeout·Retry](docs/RESILIENCE.md), [요청 처리](docs/REQUEST-PROCESSING.md) |
| HA 인스턴스 간 공유 카운터 | [전역 Rate Limit](docs/GLOBAL-RATELIMIT.md) |
| TLS·mTLS·외부 인가 | [HTTP·HTTPS](docs/TLS.md), [mTLS·갱신](docs/MTLS.md), [외부 인가](docs/EXTAUTHZ.md) |
| Keycloak 로그인·토큰 검증 | [OAuth / OIDC](docs/OIDC.md) |
| OAuth와 mTLS의 개별·통합 동작 | [인증 비교](shared/AUTH-COMPARISON.md) |
| 인증서 실패·토큰 갱신·JWKS 회전 | [갱신·회전 비교](shared/AUTH-LIFECYCLE.md) |
| 외부 모델 없는 A2A 메시지·정책 비교 | [Mock A2A](shared/A2A.md) |

## 디렉터리 구성

```text
agentgateway/
├── README.md           # 시작점과 문서 안내
├── POLICY-ROADMAP.md    # 단계별 상태·남은 범위
├── docs/               # Compose 선택 안내·단계별 실행과 검증 기록
├── single/             # 기본 Compose·추가 Compose·정책 설정·실행 안내
├── ha/                 # 기본 Compose·추가 Compose·정책 설정·Nginx·장애 전환 테스트
└── shared/             # 공통 서버·준비/검증 스크립트·정책/인증/A2A 안내
```

상세 문서의 실행 기록은 2026-10-18~19에 수행한 로컬 검증 결과입니다.
운영 환경의 성능·가용성 보장이나 현재 실행 상태를 뜻하지 않습니다.
