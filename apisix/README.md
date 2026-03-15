# apisix docker compose

apisix gateway docker compose

## 개발환경

이제 `apisix/.env` 기준으로 전체 스택을 관리합니다.

- 예시 파일: `apisix/.env.example`
- 실제 실행 파일: `apisix/.env`
- 실행 위치: `apisix` 디렉터리

```bash
cd apisix
docker compose up -d --build
```

`APISIX_ADMIN_KEY` 는 APISIX 설정 템플릿, exporter, Admin API 호출 시 모두 같은 값을 사용해야 합니다.

## 구성

현재 redis는 single node, ETCD는 3노드 cluster로 구성되어있습니다.

- `backend` : APISIX 샘플 upstream 의 기본 대상으로 사용하는 내부 API 서비스입니다. `/api/health` 와 `/api/*` 를 200으로 응답합니다.
- `nginx` : user의 HTTP request를 round robbin으로 apisix * 2에 전달합니다.
- `apisix` : gateway로써 라우팅정보를 바탕으로 받은 요청을 upstream으로 전달합니다. Java plugin 실행을 위해 `apache/apisix:3.11.0-debian` 기반 이미지에 Java와 `envsubst` 를 추가하고, 시작 시 `.env` 값을 기준으로 실제 APISIX 설정 파일을 렌더링합니다.
- `redis` : rate limit을 공유하기 위한 storage로 사용됩니다.
- `etcd` : apisix의 설정정보를 공유하기위한 3노드 cluster storage입니다.
- `prometheus` : metric 수집 및 저장하는 TSDB입니다.
- `limit_req_exporter` : apisix의 라우터들의 rate limit 정보를 scrap하여 prometheus에 metric을 저장합니다.
- `grafana` : 수집된 metric정보를 시각화 하는 dashboard입니다.

```mermaid
graph TD
  user[User]
  entry["Nginx<br>(Entry Point)"]

  subgraph "APISIX Cluster"
    apisix1[APISIX 1]
    apisix2[APISIX 2]
  end

  subgraph "Redis Cluster"
    redis_service["Redis<br>(Rate Limit Shared Storage)"]
  end

  subgraph "ETCD Cluster"
    etcd_service["ETCD<br>(Config Store)"]
  end

  subgraph "Monitoring"
    prometheus["Prometheus<br>(Metrics Collector)"]
    grafana["Grafana<br>(Dashboard)"]
    exporter["limit_req_exporter<br>(Rate Limit Exporter)"]
  end

  user -->|HTTP Request| entry
  entry --> apisix1
  entry --> apisix2

  apisix1 -->|Rate limit data| redis_service
  apisix2 -->|Rate limit data| redis_service

  apisix1 -->|Fetch configuration| etcd_service
  apisix2 -->|Fetch configuration| etcd_service

  exporter -->|Expose metrics| prometheus
  exporter -->|Scrape rate limits| apisix1
  exporter -->|Scrape rate limits| apisix2

  prometheus -->|Scrape metrics| apisix1
  prometheus -->|Scrape metrics| apisix2

  grafana -->|Visualize metrics| prometheus
```

### 설정 구조

- `docker-compose.yml` : 포트, 볼륨, 재시작 정책, 이미지 버전, 컨테이너별 환경변수 정의
- `.env` : 사용자가 조정할 운영값
- `backend/nginx.conf` : backend 서비스의 기본 API/health 응답 설정
- `apisix/config.template.yaml` : APISIX 공통 템플릿
- `scripts/render-apisix-config.sh` : 컨테이너 시작 시 템플릿을 실제 `config.yaml` 로 생성
- `scripts/apisix-admin-sample.sh` : `.env` 기반 APISIX Admin API 샘플 스크립트
- `scripts/etcd-cluster-status.sh` : ETCD cluster 상태 확인 스크립트

### APISIX Admin API 샘플 스크립트

```bash
cd apisix

# 현재 .env 기준으로 어떤 값이 적용되는지 확인
./scripts/apisix-admin-sample.sh show-env

# upstream 등록
./scripts/apisix-admin-sample.sh put-upstream

# route 등록
./scripts/apisix-admin-sample.sh put-route

# upstream + route 한 번에 등록
./scripts/apisix-admin-sample.sh put-all

# 등록 확인
./scripts/apisix-admin-sample.sh get-routes
./scripts/apisix-admin-sample.sh get-upstreams

# compose 내부 backend 서비스 자체 확인
curl -i http://127.0.0.1:8081/api/health
```

`.env` 에서 아래 값을 바꾸면 스크립트도 같이 반영됩니다.

- `APISIX_ADMIN_BASE_URL`
- `APISIX_CLUSTER_ADMIN_API_URL`
- `APISIX_SAMPLE_ROUTE_ID`
- `APISIX_SAMPLE_UPSTREAM_ID`
- `APISIX_SAMPLE_ROUTE_URI`
- `APISIX_SAMPLE_UPSTREAM_HOST`
- `APISIX_SAMPLE_UPSTREAM_PORT`
- `APISIX_SAMPLE_HEALTH_CHECK_URL`

기본값은 compose 내부 `backend:8080` 을 upstream 으로 사용하고, 호스트에서는 `http://127.0.0.1:8081` 로 backend 자체를 바로 확인할 수 있습니다.

### apisix plugin

- `active_health_control.lua` : apisix에서 라우팅되는 upstream을 active 방식으로 health check하는 plugin 입니다.
- `utli.lua` : 기존 util.lua를 ovveride하는 plugin입니다. 현재 dynamic_throttling plugin이 rate limit을 변경하면서 `modifiedIndex`의 값에 따라서 생기는 redis에 rate limit 관련 key에 대해 ttl을 추가하기 위한 plugin 입니다.
  - rate limit 관련 redis key : `limit_req:{routeId}route{modifiedIndex}excess`, `limit_req:{routeId}route{modifiedIndex}last`
- `apisix-demo-jar-with-dependencies.jar` : `ext-plugin-pre-req` 으로써 springboot로 작업되어있습니다. header 체크를 한다던지의 추가 기능을 수행할 수 있습니다.
  - route 설정시 PluginFilter 이름과 동일하게 설정합니다.
    - route 설정
      ```json
      "ext-plugin-pre-req":{
        "conf":[
          {
            "name":"DemoFilter",
            "value":""
          }
        ]
      }
      ```
    - spring PluginFilter name (**class명과는 상관없습니다.**)
      ```java
      @Override
      public String name() {
          return "DemoFilter";
      }
      ```

```shell
curl -i -X PUT http://127.0.0.1:9280/apisix/admin/routes/1 \
-H "X-API-KEY: {ADMIN_API_KEY}" \
-H "Content-Type: application/json" \
-d '{
  "uri": "/api/*",
  "plugins": {
    "prometheus":{},
    "active_health_control": {
      "health_check_enabled": true,
      "admin_api_url": "http://apisix1:9180",
      "admin_api_token": "{ADMIN_API_KEY}",
      "health_check_path": "http://{HEALTH_CHECK_FOR_HOST}/api/health",
      "expected_status": 200,
      "interval": 5
    },
    "limit-req":{
      "rate": 200,
      "burst": 20,
      "key": "route_id",
      "policy": "redis",
      "redis_host": "redis",
      "redis_port": 6379,
      "redis_timeout": 1000,
      "rejected_code": 429
    },
    "ext-plugin-pre-req":{
      "conf":[
        {
          "name":"DemoFilter",
          "value":""
        }
      ]
    }
  },
  "methods": ["GET", "POST"],
  "upstream": {
    "type": "roundrobin",
    "nodes": {
      "{UPSTREAM_HOST}:{UPSTREAM_PORT}": 1
    }
  }
}'
```

## command
### etcd cluster 명령어 확인

```bash
./scripts/etcd-cluster-status.sh member-list
```

```bash
./scripts/etcd-cluster-status.sh endpoint-status
```

```bash
./scripts/etcd-cluster-status.sh endpoint-health
```

### etcd 설정 확인

```bash
docker compose exec etcd1 etcdctl --endpoints=http://etcd1:2379,http://etcd2:2379,http://etcd3:2379 get / --prefix --keys-only --write-out=json
```

### etcd 현재 revision값 확인

```bash
docker compose exec etcd1 etcdctl --endpoints=http://etcd1:2379,http://etcd2:2379,http://etcd3:2379 endpoint status --write-out=table
```

### defrag 하기

```bash
docker compose exec etcd1 etcdctl --endpoints=http://etcd1:2379,http://etcd2:2379,http://etcd3:2379 defrag
```

### 디스크 용량 확인

```bash
du -sh /bitnami/etcd/data/member
```

### route 설정 확인

```bash
curl -i -X GET http://127.0.0.1:9280/apisix/admin/routes \
-H "X-API-KEY: edd1c9f034335f136f87ad84b625c8f1"
```

### redis 값 확인

> 위에서 modifiedIndex값에 해당하는 route{id}로 잡힘. 즉, route 정보가 업데이트 된다면 이미 공유되던 ratelimit 값이 바뀜을 주의.

"limit_req:3route32last" => 1742868395840 : 마지막 요청이 처리된 타임스탬프
1) "limit_req:3route32excess" => integer : 버스트(burst) 제한을 초과한 요청 개수를 나타냄. 현재 bucket에 누적된 초과 요청 수. excess 값은 10이 됨 -> "10개의 요청이 rate+burst를 넘어서 차단됐다"는 뜻

### redis cluster 적용

route 설정 시 redis cluster를 사용하게 된다면 아래처럼 route를 구성해야합니다.

- as-is

  ```json
  "limit-req":{
    "rate": 200,
    "burst": 20,
    "key": "route_id",
    "policy": "redis",
    "redis_host": "redis",
    "redis_port": 6379,
    "redis_timeout": 1000,
    "rejected_code": 429
  }
  ```

- to-be

  ```json
  "limit-req": {
    "rate": 200,
    "burst": 20,
    "key": "route_id",
    "policy": "redis-cluster",
    "redis_cluster_nodes": [
      "redis-node-1:7001",
      "redis-node-2:7002",
      "redis-node-3:7003",
      "redis-node-4:7004",
      "redis-node-5:7005",
      "redis-node-6:7006"
    ],
    "redis_cluster": true,
    "redis_timeout": 1000,
    "rejected_code": 429
  }
  ```

### etcd cluster 적용

`apisix.yaml`에 아래 설정을 적용해야함.

```yml
deployment:
  etcd:
    host:
      - "http://etcd1:2379"
      - "http://etcd2:2379"
      - "http://etcd3:2379"
```

### etcd cluster 확인
docker compose exec etcd1 etcdctl --endpoints=http://etcd1:2379,http://etcd2:2379,http://etcd3:2379 member list

### etcd cluster 리더 노드 확인
docker compose exec etcd1 etcdctl --endpoints=http://etcd1:2379,http://etcd2:2379,http://etcd3:2379 endpoint status --write-out=table
