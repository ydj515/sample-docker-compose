# Redis 개발환경

이 디렉터리는 Redis 로컬 개발/학습용 Docker Compose 샘플을 정리한 폴더입니다.

## 구성

- `redis-single-simple`
  - Redis 단일 노드를 가장 단순하게 실행하는 구성입니다.
  - 빠르게 띄워보고 연결 테스트만 할 때 사용합니다.
- `redis-single`
  - Redis 단일 노드 + `redis.conf` + ACL 기반 사용자 설정
  - 설정 파일, AOF, 읽기/쓰기 사용자 분리까지 함께 확인할 수 있는 구성입니다.
- `redis-replica`
  - Redis Master 1대 + Replica 2대
  - `--replicaof` 기반의 가장 단순한 복제 구조를 확인할 때 사용합니다.
- `redis-sentinel`
  - Redis Master 1대 + Replica 2대 + Sentinel 3대
  - Sentinel 기반 failover 흐름을 로컬에서 확인할 때 사용합니다.
- `redis-cluster`
  - Redis Cluster 6노드(3 master + 3 replica)
  - cluster mode, `nodes.conf`, bus port, announce 설정까지 함께 확인할 수 있는 구성입니다.

## 사용 가이드

- 한 번에 한 폴더만 실행하는 것을 권장합니다.
- 모든 샘플은 `.env`를 기준으로 이미지 버전, 포트, 계정 정보를 관리합니다.
- `redis-single`, `redis-sentinel`, `redis-cluster`는 named volume을 사용하므로 `docker compose down`만으로는 데이터와 runtime 설정이 삭제되지 않습니다.
- 데이터를 초기화하려면 `docker compose down -v`를 사용합니다.
- `redis-single`, `redis-sentinel`, `redis-cluster`는 템플릿 설정 파일과 runtime 설정 파일을 분리하는 구조가 포함되어 있어, 설정 파일 수정 후에는 config volume 초기화가 필요할 수 있습니다.
- `redis-cluster`는 `docker compose up -d` 이후 `./scripts/create-cluster.sh`를 별도로 실행해야 클러스터가 완성됩니다.

## 실행 예시

### redis-single-simple

```bash
cd redis-single-simple
cp .env-sample .env
docker compose up -d
```

### redis-single

```bash
cd redis-single
cp .env-sample .env
docker compose up -d
```

### redis-replica

```bash
cd redis-replica
cp .env-sample .env
docker compose up -d
```

### redis-sentinel

```bash
cd redis-sentinel
cp .env-sample .env
docker compose up -d
```

### redis-cluster

```bash
cd redis-cluster
cp .env-sample .env
docker compose up -d
./scripts/create-cluster.sh
```

## 공통 포인트

- `redis-single`은 기본 `default` 사용자를 비활성화하고 ACL 사용자 계정을 `.env` 기준으로 생성합니다.
- `redis-replica`는 가장 단순한 복제 예제이고, failover 자동화는 포함하지 않습니다.
- `redis-sentinel`은 고정 IP와 Sentinel quorum 기반으로 failover를 자동 수행합니다.
- `redis-cluster`는 `nodes.conf`와 AOF 데이터를 volume에 영속화하므로 재기동 후에도 클러스터 메타데이터가 유지됩니다.
- 단순 연결 테스트는 `redis-single-simple`, ACL/설정 파일까지 같이 보려면 `redis-single`, 복제 흐름은 `redis-replica`, 자동 failover는 `redis-sentinel`, 클러스터 모드는 `redis-cluster`가 가장 적합합니다.
