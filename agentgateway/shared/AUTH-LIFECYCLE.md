# 인증 수단 갱신·회전·실패 비교

개별/통합 구성 비교는 [AUTH-COMPARISON.md](AUTH-COMPARISON.md)를 참고합니다.
인증서 갱신, 토큰 갱신, JWT 서명 키 회전은 서로 다른 작업입니다.
이번 JWKS 503 실험은 60초 안에 자동 복구되지 않았으며 Gateway 재시작으로 복구했습니다. 상세 조건은 실행 기록에 구분합니다.

| 항목 | 변경 대상 | 성공 조건 | 대표 실패 | 복구 |
| --- | --- | --- | --- | --- |
| 인증서 갱신 | 서버/클라이언트의 인증서·개인키 | trust·유효기간·용도·이름·키 일치, 실제 새 인증서 제시 | 잘못된 CA, 키 불일치, 만료, CA 잔여 수명 부족 | 적용 전 차단 또는 이전 파일 세대로 복원·재기동 |
| 사용자 토큰 갱신 | access token 및 refresh token | Keycloak refresh grant 성공, 새 access token으로 기존 권한 유지 | 위조 refresh token, 다른 client, logout된 세션 | 유효 세션이면 재시도, 세션 무효면 재로그인 |
| 서버용 토큰 재발급 | Client Credentials access token | 같은 client 자격 증명으로 token endpoint 재호출 | client secret 오류·인증 서버 장애 | 자격 증명/인증 서버 복구 후 재발급 |
| 서명 키 회전 | JWT 서명용 개인키와 공개 JWKS | 새 kid를 Gateway가 받아들임, 유예 후 구 kid 거부 | 새 키 미전파, 구 키 조기 제거, JWKS 조회 장애 | 구·신 키 겹침 구간 확보, JWKS 복구·캐시 갱신 확인 |

OAuth 단독에는 인증서 갱신 항목이 없고, mTLS 단독에는 토큰·JWT 서명 키 갱신 항목이 없습니다.
통합 샘플에서는 두 수단을 각각 관리합니다. access token을 갱신해도 인증서 오류를 해결하지 못하며,
인증서를 갱신해도 만료·무효 토큰을 사용할 수 없습니다.

## 인증서 갱신 실패

`validate-mtls.py`는 인증서/개인키 쌍, CA trust, 현재 유효기간, EKU 목적, 서버 SAN을 검사합니다.
기존 `rotate-mtls.py`도 이 검사를 Compose 적용 전에 수행합니다.
`prepare-mtls.py --renew-from`의 CA 잔여 수명 31일 검사를 유지합니다.
이 검사는 로컬 샘플의 예상 이름을 기준으로 하며 CRL/OCSP·운영 정책 전체를 검증하지 않습니다.

```bash
# 저장소 루트에서, 기존 v1 인증서가 준비된 상태
python3 agentgateway/shared/validate-mtls.py agentgateway/single/mtls-certs/v1

# 적용 전 실패 검사만 수행: 현재 실행 환경은 바꾸지 않음
python3 agentgateway/shared/test-certificate-renewal.py single agentgateway/single/mtls-certs/v1

# 통합 샘플의 실제 장애 주입과 rollback (single/ha 각각)
# 먼저 prepare-oidc.py <mode 폴더> --mtls로 통합 realm import 준비
python3 agentgateway/shared/test-certificate-renewal.py single agentgateway/single/mtls-certs/v1 --runtime --variant oidc-mtls
python3 agentgateway/shared/test-certificate-renewal.py ha agentgateway/ha/mtls-certs/v1 --runtime --variant oidc-mtls
```

`--runtime`은 정상 세대 기동 → preflight를 의도적으로 우회해 다른 CA의 서버 인증서 적용 →
클라이언트 TLS 검증 실패 → `finally`에서 정상 세대 복원 순서입니다.
복원 후 single/HA 직접 경로·Nginx의 서버 인증서 SHA-256 fingerprint를 확인합니다.
전체 로컬 Compose를 재생성하므로 중단이 있으며, 무중단 rolling 갱신 실험이 아닙니다.
종료 후 선택한 mTLS 또는 통합 설정이 실행 중입니다. 문서 마지막 복원 명령을 사용합니다.
원래 파일은 변경하지 않고 장애 자료는 `mtls-certs/failure-*` 아래에 보존합니다.

## 토큰 갱신과 로그아웃

[통합 구성](AUTH-COMPARISON.md#준비와-실행) 또는 [OAuth 단독 구성](../docs/OIDC.md)을 먼저 실행합니다.

```bash
# single/ 또는 ha/에서: 기존 OAuth 단독
python3 ../shared/test-oidc.py . --refresh

# single/ 통합
python3 ../shared/test-oidc.py . --mtls-cert-dir ./mtls-certs/v1 --refresh

# ha/ 통합: 두 Gateway 및 Nginx
python3 ../shared/test-oidc.py . \
  https://localhost:14401/mcp/mtls https://localhost:14402/mcp/mtls https://localhost:13443/mcp/mtls \
  --mtls-cert-dir ./mtls-certs/v1 --refresh
```

테스트는 PKCE 로그인으로 얻은 refresh token을 사용합니다. 비밀번호 grant나 관리자 API를 사용하지 않습니다.
Client Credentials 응답에는 refresh token이 없고, grant를 다시 요청해 새 access token을 얻습니다.
잘못된 refresh token·다른 client로 갱신하면 `invalid_grant`를 검사합니다.
성공한 갱신 access token으로 viewer 권한을 검사하고, 로그아웃 후 refresh가 거부되는지 검사합니다.
로그아웃 전 발급된 access token은 Gateway의 로컬 JWT 검증에서 즉시 폐기되지 않는지도 구분합니다.

현재 realm은 `Revoke Refresh Token`을 켜지 않았으므로 기존 refresh token 재사용이 허용됩니다.
이는 일회용 refresh token rotation/reuse detection 설정의 검증이 아닙니다.
refresh token 자연 만료·인증 서버 장기 장애·클라이언트 자동 갱신 구현도 이번 범위에 포함하지 않습니다.
`--expiry`와 함께 사용하면 기존 access token 만료 후 initialize 거부도 별도로 검사합니다.

## JWT 서명 키 회전과 JWKS 장애

이 실험은 **Keycloak의 관리자 키 회전이 아니라, 로컬 RSA/JWKS fixture와 실제 Gateway의 검증·캐시 동작**을 비교합니다.
Node 내장 crypto로 A/B 키를 생성하고 개인키는 프로세스 메모리에만 유지합니다.
fixture 재시작 시 키가 바뀝니다. 임의 토큰 발급·제어 API가 있어 loopback 전용이며 운영 인증 서버로 사용할 수 없습니다.
설정은 기존 OAuth+mTLS 구성과 분리된 `config-jwks-rotation.yaml`입니다.

```bash
# single/ 또는 ha/에서
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
export MTLS_CERT_DIR=./mtls-certs/v1
export AGENTGATEWAY_CONFIG=./config-jwks-rotation.yaml
docker compose -f docker-compose.yml -f compose-mtls.yml -f compose-jwks-rotation.yml config --quiet
docker compose -f docker-compose.yml -f compose-mtls.yml -f compose-jwks-rotation.yml up -d --build --wait
python3 ../shared/test-jwks-rotation.py . "$MTLS_CERT_DIR"
```

fixture 포트는 single 18090 / HA 28090입니다. 단독 OAuth나 통합 Keycloak realm은 변경하지 않습니다.
테스트 시작 시 Gateway를 재시작하여 A만 있는 캐시에서 시작하며, 이후 자동 갱신을 관찰합니다.
`Cache-Control: max-age=60`을 사용합니다. 각 전이의 실제 관찰 시간을 출력하며 전체 수 분이 걸립니다. 자동 복구와 재시작 복구는 결과에 별도로 표시합니다.

1. A만 공개: A 허용, 아직 공개하지 않은 B는 401.
2. A+B 공개: B 허용으로 전환되는 시간 확인, 아직 만료하지 않은 A도 허용.
3. B만 공개: A가 401로 전환되는 시간 확인, B는 유지.
4. JWKS HTTP 503 주입: 실제 백그라운드 조회 실패를 확인하고 마지막 정상 B 캐시의 동작 검사.
5. A+B 복구: 60초 동안 자동 반영을 관찰. 반영되지 않으면 제한을 출력하고 Gateway 재시작으로 복구 확인.

키 제거와 token 만료를 혼동하지 않도록 fixture 토큰 수명은 15분입니다.
구 키를 제거하면 아직 만료하지 않은 구 토큰도 새 JWKS가 적용된 뒤 거부될 수 있습니다.
정상 회전은 구 토큰 최대 수명·clock skew·각 Gateway의 갱신 시간을 고려해 구·신 키 겹침 기간을 잡아야 합니다.
테스트에서는 비교를 위해 구 키를 조기에 제거합니다. 이 제거 순서를 운영 기본값으로 사용하지 않습니다.

## 원래 실행 상태로 복원

```bash
# single/ 또는 ha/에서
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
AGENTGATEWAY_CONFIG=./config-multi-policies.yaml docker compose up -d --wait
docker compose -f docker-compose.yml -f compose-mtls.yml -f compose-jwks-rotation.yml -f compose-oidc-mtls.yml stop jwks-fixture keycloak mcp-mtls
unset AGENTGATEWAY_CONFIG MTLS_CERT_DIR
```

- 제약: 실제 Gateway v1.6.0과 로컬 Keycloak을 검사하지만, 서명 키 회전 발급자는 테스트 fixture입니다. 실제 Keycloak key-provider 우선순위 변경·관리자 API·키 폐기는 미검증입니다.
- 위험: CA와 JWT 서명 키를 성급히 제거하면 기존 인증서/토큰이 모두 거부될 수 있습니다. JWKS 장애 시 캐시 유지도 폐기된 키를 즉시 차단한다는 의미가 아닙니다.
- 예외: 인증서 적용 rollback은 프로세스가 `finally`까지 실행된 경우입니다. 강제 종료·호스트 장애에서는 수동 복원이 필요합니다. 인증서·로그인·서명 키의 무중단 회전은 보장하지 않습니다.

공식 근거: [Keycloak OIDC endpoints](https://www.keycloak.org/securing-apps/oidc-layers),
[Keycloak server administration](https://www.keycloak.org/docs/latest/server_admin/index.html),
[agentgateway v1.6.0 resource manager](https://github.com/agentgateway/agentgateway/blob/v1.6.0/crates/agentgateway/src/resource_manager.rs).

## 실행 기록 — 2026-10-19

인증서 실패 검사는 single/HA 모두 키 불일치·다른 CA·고정된 과거 날짜의 만료 인증서·CA 수명 부족을 거부했습니다.
과거 날짜 fixture로 만료 조건을 재현했으며 시스템 시간을 변경하거나 실제 만료일까지 기다리지 않았습니다.
preflight를 우회한 다른 CA 서버 인증서 적용 시 single·HA 두 Gateway·Nginx에서 TLS 검증이 실패했고,
rollback 후 원래 fingerprint가 복구됐습니다. 원본 v1 파일 hash는 보존됐고 정상 v2 세대도 preflight를 통과했습니다.

실제 Keycloak의 통합 샘플에서 refresh 성공·기존 viewer 권한 유지·Client Credentials 재발급을 확인했습니다.
잘못된 refresh token과 다른 client의 요청은 HTTP 400 `invalid_grant`, logout 이후 refresh도 같은 오류였습니다.
logout 직후 기존 access token의 initialize는 네 경로 모두 200이었습니다.
이 realm의 기본값에서는 이전 refresh token 재사용도 200이므로 일회용 재사용 차단으로 해석하지 않습니다.
기존 authorization code 재사용 실험이 로그인 세션을 무효화할 수 있어, refresh 검사는 새 PKCE 로그인으로 분리했습니다.

### JWKS 장애에서 확인한 제한 (v1.6.0)

HTTP 503 + `Cache-Control: no-store` + JSON 오류 본문을 반환했을 때 v1.6.0 로그는
`Failed to reload config: failed to load JWKS: missing field keys`였습니다.
기존 설정의 B 토큰은 계속 허용되고 이미 제거된 A는 401로 유지됐습니다.
따라서 이 실패는 서명 검증을 생략하는 동작이 아니라 마지막 정상 설정이 남는 동작입니다.

소스의 HTTP resource fetch는 이 응답 본문을 읽으며, `no-store`일 때 TTL 계산은 기본값을 사용합니다.
JWKS 기본값은 15분입니다. 이 경로를 네트워크 오류용 15초 retry와 동일하게 해석하면 안 됩니다.
이번에는 복구 관찰을 중단한 뒤 별도 `--recovery-only` 단계로 60초 자동 반영 여부와 재시작 복구를 확인했습니다.
15분이 지난 뒤의 자동 복구, 연결 거절·timeout 장애, 최초 기동 시 JWKS 장애는 검증하지 않았습니다.
운영 관측에는 HTTP 상태뿐 아니라 Gateway의 JWKS 설정 재적용 오류와 새 kid 검증 성공 여부를 포함해야 합니다.

| JWKS 관찰 항목 | single | HA (두 Gateway·Nginx 모두) |
| --- | --- | --- |
| 새 B 공개 직후 | 401 | 401 |
| B 허용 전환 | 58.4초 | 61.0초 |
| A 제거 직후 | 200 | 200 |
| A 거부 전환 | 60.4초 | 59.2초 |
| HTTP 503 발생 확인 | 약 60.2초 | 약 60.2초 |
| 장애 중 B/A | B=200, A=401 | B=200, A=401 |
| 복구 단계에서 60초 자동 반영 관찰 | 반영 안 됨 | 반영 안 됨 |
| Gateway restart 명령 완료 후 A/B 복구 | 약 2초 | 약 2초 |

2초 간격으로 관찰한 로컬 결과이며 지연 SLA나 성능 비교 수치가 아닙니다.
JWKS 단계는 A/B 전환·장애 검사와 별도의 복구 단계로 나누어 실행했습니다.
인증서의 실제 장애 주입은 OAuth+mTLS 통합 설정에서 수행했습니다.
mTLS 단독용 `--variant mtls` 실행 경로는 제공하지만 이번 기록의 runtime 검증 대상은 통합 설정입니다.

OAuth 단독 single·HA 두 Gateway·Nginx에서도 `--refresh` 회귀 검증을 통과했습니다.
통합 샘플과 동일하게 refresh 성공, 잘못된/다른 client의 refresh 거부, 기본 refresh 재사용 허용,
logout 후 refresh 거부와 기존 access token의 즉시 폐기 미지원 동작을 확인했습니다.

마무리에는 single/HA를 기존 복합 정책으로 복원하고 Keycloak·JWKS fixture·mcp-mtls를 정지했습니다.
세 Gateway의 설정 mount 복원과 권한·독립/전체 rate limit·refill 회귀 테스트를 확인했습니다.
자격 증명·인증서·실패 fixture·DB volume은 보존했습니다.
