# Kafka 개발환경

이 디렉터리는 Kafka 로컬 개발/학습용 Docker Compose 샘플을 정리한 폴더입니다.

## 구성

- `single-kafka-with-zookeeper`
  - Zookeeper + Kafka Broker 1대 + Kafka UI
  - 가장 단순한 로컬 테스트용 구성입니다.
- `kafka-cluster-with-zookeeper`
  - Zookeeper 3대 ensemble + Kafka Broker 3대 + Kafka UI
  - Zookeeper quorum 기반 클러스터 동작을 확인할 때 사용합니다.
- `kafka-cluster-with-KRaft`
  - KRaft 기반 Kafka Broker/Controller 3대 + Kafka UI
  - 신규 Kafka 구성 연습용으로 권장하는 샘플입니다.

## 사용 가이드

- 한 번에 한 폴더만 실행하는 것을 권장합니다.
- 세 샘플 모두 `.env`를 기준으로 포트와 이미지 버전을 관리합니다.
- 각 샘플은 `healthcheck`와 `depends_on.condition: service_healthy`를 사용해 초기 기동 순서를 안정화했습니다.
- 모든 샘플은 named volume을 사용하므로 `docker compose down`만으로는 데이터가 삭제되지 않습니다.
- 데이터를 초기화하려면 `docker compose down -v`를 사용합니다.

## 실행 예시

### single-kafka-with-zookeeper

```bash
cd single-kafka-with-zookeeper
cp .env-sample .env
docker compose up -d
```

### kafka-cluster-with-zookeeper

```bash
cd kafka-cluster-with-zookeeper
cp .env-sample .env
docker compose up -d
```

### kafka-cluster-with-KRaft

```bash
cd kafka-cluster-with-KRaft
cp .env-sample .env
docker compose --env-file .env up -d
```

## 공통 포인트

- Kafka UI는 세 샘플 모두 브로커가 준비된 뒤에 실행됩니다.
- `container_name`은 제거되어 Compose 프로젝트 단위 이름 격리가 유지됩니다.
- 이미지 버전과 노출 포트는 `.env`에서 관리합니다.
- KRaft 샘플은 내부 브로커 포트를 고정하고, 외부 노출 포트만 `.env`에서 조정할 수 있게 정리했습니다.
