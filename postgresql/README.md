# PostgreSQL 개발환경

이 디렉터리는 PostgreSQL 로컬 개발/학습용 Docker Compose 샘플을 정리한 폴더입니다. 기본 단일 노드와 공간 검색, 벡터 검색, 전문 검색, 시계열 데이터, 분산 처리 등의 확장 구성을 제공합니다.

## 구성

| 디렉터리                                               | 구성 및 용도                                           | 기본 호스트 포트 |
|----------------------------------------------------|---------------------------------------------------|-----------|
| [postgresql-17](postgresql-17/)                    | PostgreSQL 단일 노드 + 설정 파일 + 초기화 SQL                | 5432      |
| [postgis](postgis/README.md)                       | 공간 데이터 저장, 거리·반경·영역 검색                            | 5541      |
| [pgvector](pgvector/README.md)                     | 임베딩 벡터 저장과 유사도 검색                                 | 5542      |
| [pg-search](pg-search/README.md)                   | ParadeDB 기반 전문 검색과 BM25 랭킹                        | 5543      |
| [timescaledb](timescaledb/README.md)               | 시계열 데이터를 hypertable로 관리                           | 5544      |
| [citus/single-node](citus/single-node/README.md)   | 단일 노드에서 분산 테이블과 샤드 구조 확인                          | 5545      |
| [citus/multi-node](citus/multi-node/README.md)     | coordinator 1대 + worker 2대 + coordinator의 pg_cron | 5434      |
| [pg-cron](pg-cron/README.md)                       | SQL 예약 실행과 실행 이력 확인                               | 5546      |
| [pg-stat-statements](pg-stat-statements/README.md) | 쿼리별 누적 실행 통계 확인                                   | 5548      |
| [pg-trgm](pg-trgm/README.md)                       | 문자열 유사도와 부분 일치 검색                                 | 5549      |

## 사용 가이드

- 실행할 폴더로 이동한 뒤 `.env.example`을 `.env`로 복사합니다.
- `.env`에서 이미지, 호스트 포트, 계정, 비밀번호, DB 이름, 시간대를 조정합니다. 확장 예제는 비밀번호 입력이 필요합니다.
- `.env`는 Git 추적에서 제외됩니다. 셸에 같은 변수를 export한 경우 `.env`보다 우선 적용됩니다.
- 각 구성은 별도의 named volume을 사용합니다. `docker compose down`만으로는 데이터가 삭제되지 않습니다.
- 초기화 SQL은 빈 볼륨에서 처음 시작할 때만 실행합니다. 기존 볼륨의 계정·DB·비밀번호는 `.env` 수정만으로 변경되지 않습니다.
- 확장 예제는 확장 활성화까지만 자동 처리합니다. 샘플 데이터 입력이나 cron 작업 예약은 별도로 실행합니다.
- Citus 다중 노드는 컨테이너 실행 후 `bash setup.sh`까지 실행해야 노드 등록과 coordinator의 pg_cron 활성화가 완료됩니다.

## 실행 예시

각 예시는 이 `postgresql` 디렉터리에서 시작합니다. `.env` 복사 후 편집기로 비밀번호와 필요한 값을 설정합니다.

### 기본 PostgreSQL

```bash
cd postgresql-17
cp -n .env.example .env
# .env의 계정·비밀번호·DB·포트를 설정합니다.
docker compose config --quiet
docker compose up -d
docker compose exec postgres sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

### 확장 단일 노드

PostGIS 예시입니다. 다른 확장은 해당 폴더의 README에 있는 서비스 이름으로 접속합니다.

```bash
cd postgis
cp -n .env.example .env
# .env의 POSTGRES_PASSWORD를 입력합니다.
docker compose config --quiet
docker compose up -d --build --wait
docker compose exec postgis sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

```sql
SELECT version();
SELECT extname, extversion FROM pg_extension ORDER BY extname;
```

### Citus 다중 노드

```bash
cd citus/multi-node
cp -n .env.example .env
# .env의 POSTGRES_PASSWORD를 입력합니다.
docker compose config --quiet
docker compose up -d --build --wait
bash setup.sh
docker compose exec citus-coordinator sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

### 종료 및 초기화

실행한 폴더에서 사용합니다.

```bash
# 컨테이너와 네트워크 종료. 데이터 볼륨은 유지합니다.
docker compose down

# 데이터를 모두 초기화할 때만 실행합니다.
docker compose down -v
```

## 값 변경 위치

| 항목                                  | 변경 위치                                                                                                             |
|-------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| 이미지 또는 빌드 기반 이미지                    | 각 폴더의 `.env` → `POSTGRES_IMAGE`                                                                                   |
| 호스트 공개 포트                           | `.env` → `POSTGRES_PORT`                                                                                          |
| 계정·비밀번호·DB 이름                       | `.env` → `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`                                                      |
| 컨테이너 시간대                            | `.env` → `TZ`                                                                                                     |
| 기본 PostgreSQL 서버 설정                 | [postgresql-17/conf.d/postgresql.conf](postgresql-17/conf.d/postgresql.conf)                                      |
| 확장 preload, pg_cron 실행 방식, worker 수 | 각 폴더의 `docker-compose.yml` → `command`                                                                            |
| 초기 확장 활성화                           | 각 폴더의 `initdb.d/99-enable-extension.sql`                                                                          |
| pg_cron 패키지 버전                      | [pg-cron/Dockerfile](pg-cron/Dockerfile), [Citus coordinator Dockerfile](citus/multi-node/coordinator/Dockerfile) |
| Citus 노드 등록과 coordinator 확장 활성화     | [citus/multi-node/setup.sh](citus/multi-node/setup.sh)                                                            |

확장 예제의 Compose는 `.env`로 변수를 치환하고 `env_file`로 컨테이너에도 전달합니다. healthcheck, pg_cron 대상 DB, Citus 등록 스크립트도 설정한 계정과 DB를 사용합니다.

## 이미지와 확장 버전

| 구성                          | PostgreSQL   | 확장                                             |
|-----------------------------|--------------|------------------------------------------------|
| postgresql-17               | 17.9 Alpine  | 기본 구성                                          |
| postgis                     | 17.11        | PostGIS 3.6.4                                  |
| pgvector                    | 17.11        | pgvector 0.8.6                                 |
| pg-search                   | 17.11        | ParadeDB 0.25.10                               |
| timescaledb                 | 17.11        | TimescaleDB 2.30.1                             |
| citus                       | 17.10        | Citus 14.2.0, 다중 노드 coordinator에 pg_cron 1.6.8 |
| pg-cron                     | 17.11        | pg_cron 1.6.8                                  |
| pg-stat-statements, pg-trgm | 17.11 Alpine | PostgreSQL contrib                             |

확장 예제는 이미지 digest와 pg_cron 패키지 버전을 고정합니다. 이미지별 태그·digest·아키텍처는 [image-versions.json](image-versions.json)에 기록되어 있습니다. PostGIS와 Citus는 amd64 이미지로, ARM 호스트에서는 에뮬레이션을 사용합니다.

## 공통 포인트

- `pg_trgm`과 `pg_stat_statements`는 기본 PostgreSQL 이미지에 포함된 contrib 모듈입니다. 대상 DB에서 `CREATE EXTENSION`으로 활성화하며, `pg_stat_statements`는 preload 설정과 서버 재시작도 필요합니다.
- 나머지 예제는 확장 전용 이미지 또는 Dockerfile을 사용합니다. `POSTGRES_IMAGE`를 기본 `postgres` 이미지로 바꾸는 것만으로 해당 확장이 설치되지는 않습니다.
- pg_cron을 설치하는 Dockerfile은 Debian용입니다. Alpine으로 바꾸려면 패키지 설치·빌드 방법도 변경해야 합니다.
- PostgreSQL 메이저 버전이 다른 데이터 볼륨을 재사용하지 않습니다. 기존 데이터를 옮길 때는 별도 이전 절차가 필요합니다.
- Citus 다중 노드의 `trust` 인증과 TLS 비활성화 설정은 로컬 실습용입니다. worker 2대는 고가용성 복제본 2개를 뜻하지 않습니다.
