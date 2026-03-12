# MongoDB Replica Set

MongoDB 3노드 Replica Set을 로컬에서 빠르게 실행하는 Docker Compose 예제입니다.

## 구성

- MongoDB 데이터 노드 3대
- Replica Set 이름: `rs0`
- 데이터 영속성: Docker named volume 3개
- 인증: root 계정 + keyfile 기반 내부 인증
- 초기화: `replica-set-init` 서비스가 `rs.initiate()` 자동 실행

## 실행 방법

1. 예제 폴더로 이동합니다.

```bash
cd mongodb/mongodb-replica-set
```

2. 환경 변수 파일을 준비합니다.

```bash
cp .env-sample .env
```

3. [`.env`](./.env) 파일에서 관리자 계정과 비밀번호를 변경합니다.

- `MONGO_ROOT_USERNAME`
- `MONGO_ROOT_PASSWORD`

4. 컨테이너를 실행합니다.

```bash
docker compose up -d
```

5. 초기화 완료 상태를 확인합니다.

```bash
docker compose ps
docker compose logs -f replica-set-init
```

## 접속 정보

- `mongo1`: `localhost:27017`
- `mongo2`: `localhost:27018`
- `mongo3`: `localhost:27019`
- 관리자 사용자명 예시: `root`
- 관리자 비밀번호 예시: `root`

Replica Set 연결 문자열 예시:

```text
mongodb://root:root@localhost:27017,localhost:27018,localhost:27019/admin?replicaSet=rs0
```

## 자주 쓰는 명령어

### Replica Set 상태 확인

```bash
docker compose exec mongo1 sh -lc 'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "rs.status()"'
```

### Primary 확인

```bash
docker compose exec mongo1 sh -lc 'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "db.hello()"'
```

### 종료

```bash
docker compose down
```

### 종료 후 볼륨까지 삭제

```bash
docker compose down -v
```

## 확인 포인트

- `mongo1`, `mongo2`, `mongo3`가 모두 `healthy` 상태인지 확인합니다.
- `replica-set-init` 로그에 `replica set initialized`가 출력되면 정상입니다.
- `rs.status()`에서 1개의 PRIMARY와 2개의 SECONDARY가 보여야 합니다.
- 기본 예제 계정은 `root/root`입니다.

## 주의사항

> - 이 예제의 keyfile은 로컬 개발 편의를 위한 고정값입니다. 운영 환경에서는 안전한 값으로 교체하고 별도 비밀 관리 수단을 사용해야 합니다.
> - 기존 볼륨이 남아 있는 상태에서 계정 정보나 Replica Set 구성을 바꾸면 기대와 다르게 동작할 수 있습니다.
> - `docker compose down -v`를 실행하면 기존 데이터가 삭제됩니다.
