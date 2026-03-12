# MongoDB 개발환경

이 디렉터리는 MongoDB 로컬 개발/학습용 Docker Compose 샘플을 정리한 폴더입니다.

## 구성

- `mongodb-single-simple`
  - MongoDB 단일 노드만 가장 단순하게 실행하는 구성입니다.
  - 빠르게 띄워보고 연결 테스트만 할 때 사용합니다.
- `mongodb-single`
  - MongoDB 단일 노드 + `mongo-express`
  - 관리자 계정, healthcheck, `mongod.conf` 기반 설정 파일을 함께 확인할 수 있는 구성입니다.
- `mongodb-replica-set`
  - MongoDB 3노드 Replica Set + 자동 초기화 서비스
  - 로컬에서 primary / secondary 동작과 replica set 연결 문자열을 확인할 때 사용합니다.
- `mongodb-sharded-cluster`
  - Config Server Replica Set + Shard Replica Set + `mongos`
  - 샤딩 구조와 `mongos` 라우팅 흐름을 학습할 때 사용하는 최소 구성입니다.

## 사용 가이드

- 한 번에 한 폴더만 실행하는 것을 권장합니다.
- 모든 샘플은 `.env`를 기준으로 이미지 버전, 포트, 계정 정보를 관리합니다.
- `mongodb-single`, `mongodb-replica-set`, `mongodb-sharded-cluster`는 named volume을 사용하므로 `docker compose down`만으로는 데이터가 삭제되지 않습니다.
- 데이터를 초기화하려면 `docker compose down -v`를 사용합니다.
- `mongodb-single`, `mongodb-replica-set`는 `mongod.conf`를 사용하므로, 설정 파일을 수정한 뒤에는 컨테이너 재시작이 필요합니다.
- Replica Set이나 Sharded Cluster는 초기화 스크립트가 한 번 실행된 뒤 기존 볼륨이 남아 있으면 구성이 그대로 유지됩니다.

## 실행 예시

### mongodb-single-simple

```bash
cd mongodb-single-simple
cp .env-sample .env
docker compose up -d
```

### mongodb-single

```bash
cd mongodb-single
cp .env-sample .env
docker compose up -d
```

### mongodb-replica-set

```bash
cd mongodb-replica-set
cp .env-sample .env
docker compose up -d
```

### mongodb-sharded-cluster

```bash
cd mongodb-sharded-cluster
cp .env-sample .env
docker compose up -d
```

## 공통 포인트

- `mongodb-single`은 `mongo-express`가 MongoDB healthcheck 이후에 실행됩니다.
- `mongodb-replica-set`은 `replica-set-init` 서비스가 `rs.initiate()`를 자동 실행합니다.
- `mongodb-sharded-cluster`는 `cluster-init` 서비스가 config server, shard, `sh.addShard()` 초기화를 자동 수행합니다.
- 단일 노드 예제는 `localhost:27017`로 바로 확인할 수 있지만, 샤딩 예제는 반드시 shard 노드가 아니라 `mongos`로 접속해야 합니다.
- 단순 연결 테스트는 `mongodb-single-simple`, 설정 파일과 운영 포인트까지 같이 보려면 `mongodb-single`, 복제와 선출을 보려면 `mongodb-replica-set`, 분산 구조를 보려면 `mongodb-sharded-cluster`가 가장 적합합니다.
