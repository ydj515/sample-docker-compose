# MongoDB Sharded Cluster

MongoDB Sharded Cluster를 로컬에서 학습하고 테스트하기 위한 최소 Docker Compose 예제입니다.

## 구성

- Config Server Replica Set 3대
- Shard Replica Set 1개
- Shard 데이터 노드 3대
- `mongos` 라우터 1대
- 초기화: `cluster-init` 서비스가 Config Server, Shard Replica Set, `sh.addShard()`를 자동 실행

## 실행 방법

1. 예제 폴더로 이동합니다.

```bash
cd mongodb/mongodb-sharded-cluster
```

2. 환경 변수 파일을 준비합니다.

```bash
cp .env-sample .env
```

3. 컨테이너를 실행합니다.

```bash
docker compose up -d
```

4. 초기화 완료 상태를 확인합니다.

```bash
docker compose ps
docker compose logs -f cluster-init
```

## 접속 정보

- `mongos`: `localhost:27017`
- 인증: 이 예제는 기본적으로 인증을 사용하지 않습니다.
- 기본 계정/비밀번호 예시: 없음

애플리케이션은 샤드 노드가 아니라 `mongos`로 접속해야 합니다.

## 자주 쓰는 명령어

### Shard 상태 확인

```bash
docker compose exec mongos mongosh --eval "sh.status()"
```

### 샤딩 활성화 예시

```bash
docker compose exec mongos mongosh --eval 'sh.enableSharding("sampledb")'
docker compose exec mongos mongosh --eval 'sh.shardCollection("sampledb.orders", { _id: "hashed" })'
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

- `cluster-init` 로그에 `sharded cluster initialized`가 출력되면 정상입니다.
- `sh.status()`에서 `configReplSet`과 `shard1ReplSet`이 보여야 합니다.
- 애플리케이션 연결 대상은 `mongos`입니다.
- 기본 계정/비밀번호 없이 접속되는 로컬 학습용 예제입니다.

## 주의사항

> - 이 예제는 로컬 학습용 최소 구성이라 인증과 키파일 설정을 생략했습니다.
> - 운영 환경에서는 Config Server, Shard, `mongos`에 대한 인증과 네트워크 제어를 반드시 추가해야 합니다.
> - 현재는 샤드 1개만 포함하므로 샤딩 구조 학습용으로는 충분하지만, 분산 확장 예제로는 최소 구성입니다.
