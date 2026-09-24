# citus / single-node

확장 소개 글의 독립 실행 예제입니다. [공통 사용법과 이미지 호환성](../../README.md)을 먼저 확인합니다.

## 실행

이 디렉터리에서 Bash로 실행합니다.

```bash
# 최초 한 번만 복사합니다. 기존 .env가 있으면 유지합니다.
cp -n .env.example .env
# .env의 POSTGRES_PASSWORD를 입력하고 필요한 계정·DB·포트를 수정합니다.
# 편집기로 .env를 저장한 다음 아래 명령을 실행합니다.
docker compose config --quiet
docker compose up -d --build --wait
docker compose exec citus sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

```sql
SELECT version();
SELECT extname, extversion FROM pg_extension ORDER BY extname;
```

초기화 SQL은 새 볼륨에서만 자동 실행합니다. 기존 볼륨에서는 접속한 DB에 `CREATE EXTENSION IF NOT EXISTS citus;`를 직접 실행해야 합니다.

```bash
# 컨테이너만 중지하고 데이터는 유지합니다.
docker compose stop
```

Compose는 같은 디렉터리의 `.env`를 변수 치환에 사용하고, `env_file`로 컨테이너에도 전달합니다. 셸에 같은 변수가 export되어 있으면 `.env`보다 우선하므로 이전 실습의 값을 해제하고 실행하세요. 계정·DB·비밀번호 변경은 기존 볼륨의 초기화 정보를 바꾸지 않습니다. `POSTGRES_IMAGE` 변경 시 PG 메이저 버전·OS·확장 호환성을 유지해야 합니다.
