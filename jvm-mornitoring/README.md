# jvm-mornitoring

단일 Spring Boot 애플리케이션을 로컬에서 실행한 상태로, `k6` 부하테스트 중 JVM 및 시스템 리소스를 함께 모니터링하기 위한 Docker Compose 구성입니다.

## 구성

- `prometheus`
  - Spring Boot Actuator Prometheus endpoint를 스크랩합니다.
  - `k6`가 Prometheus remote write로 밀어 넣는 메트릭도 함께 저장합니다.
- `grafana`
  - Prometheus를 데이터소스로 사용합니다.
  - JVM Micrometer 및 Node Exporter 대시보드를 프로비저닝합니다.
- `node-exporter`
  - 호스트 수준 CPU, Memory, Disk, Network 메트릭을 수집합니다.
- `cadvisor`
  - Docker 컨테이너 수준 CPU, Memory, Filesystem, Network 메트릭을 수집합니다.

## 전제 조건

- Spring Boot 앱은 Docker 밖에서 로컬 실행
- Spring Boot 앱의 Prometheus endpoint 노출
- Docker 및 Docker Compose 사용 가능
- `k6` 설치 완료

Spring Boot 앱은 기본적으로 `host.docker.internal:8081`에서 `/actuator/prometheus`를 노출한다고 가정합니다.

## 파일

- [docker-compose.yml](/Users/dongjin/dev/study/sample-docker-compose/jvm-mornitoring/docker-compose.yml)
- [prometheus/prometheus.yml](/Users/dongjin/dev/study/sample-docker-compose/jvm-mornitoring/prometheus/prometheus.yml)
- [.env-sample](/Users/dongjin/dev/study/sample-docker-compose/jvm-mornitoring/.env-sample)
- [load_test.js](/Users/dongjin/dev/study/sample-docker-compose/jvm-mornitoring/load_test.js)

## 환경 변수

기본값은 [.env-sample](/Users/dongjin/dev/study/sample-docker-compose/jvm-mornitoring/.env-sample)에 정리되어 있습니다.

```dotenv
# Docker image versions
PROMETHEUS_VERSION=v2.48.0
GRAFANA_VERSION=11.5.2
NODE_EXPORTER_VERSION=v1.9.1
CADVISOR_VERSION=v0.49.2

# Host ports
PROMETHEUS_PORT=9090
GRAFANA_PORT=3000
```

## Spring Boot 권장 설정

부하테스트 중 `p95`, `p99`, Tomcat thread, HikariCP 지표를 잘 보기 위해 아래 설정을 권장합니다.

```yaml
management:
  endpoints:
    web:
      exposure:
        include: health,info,prometheus,metrics

  metrics:
    tags:
      application: product-api

    distribution:
      percentiles-histogram:
        http.server.requests: true
      minimum-expected-value:
        http.server.requests: 5ms
      maximum-expected-value:
        http.server.requests: 10s
      slo:
        http.server.requests: 50ms,100ms,200ms,500ms,1s,3s

server:
  tomcat:
    mbeanregistry:
      enabled: true

spring:
  datasource:
    name: main
```

## 실행 방법

1. Spring Boot 앱 실행

```sh
./gradlew bootRun
```

Spring Boot 앱은 `8081` 포트에서 `/actuator/prometheus`를 노출해야 합니다.

2. 모니터링 스택 실행

```sh
cd /Users/dongjin/dev/study/sample-docker-compose/jvm-mornitoring
docker compose up -d
```

3. k6 부하테스트 실행

```sh
cd /Users/dongjin/dev/study/sample-docker-compose/jvm-mornitoring
K6_PROMETHEUS_RW_SERVER_URL=http://localhost:9090/api/v1/write \
k6 run -o experimental-prometheus-rw ./load_test.js
```

4. UI 확인

- Prometheus: [http://localhost:9090](http://localhost:9090)
- Grafana: [http://localhost:3000](http://localhost:3000)

## 주요 확인 포인트

- HTTP 요청
  - `http_server_requests_seconds_count`
  - `http_server_requests_seconds_sum`
  - `http_server_requests_seconds_bucket`
- JVM
  - `jvm_memory_used_bytes`
  - `jvm_gc_pause_seconds_*`
  - `jvm_threads_live_threads`
- Tomcat
  - `tomcat_threads_busy_threads`
  - `tomcat_threads_current_threads`
  - `tomcat_threads_config_max_threads`
- HikariCP
  - `hikaricp_connections_active`
  - `hikaricp_connections_idle`
  - `hikaricp_connections_pending`
- Host / Container
  - `node_cpu_seconds_total`
  - `node_memory_MemAvailable_bytes`
  - `container_cpu_usage_seconds_total`
  - `container_memory_working_set_bytes`
- k6
  - `k6_http_reqs`
  - `k6_http_req_duration_*`
  - `k6_vus`

## p95 / p99 예시 쿼리

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(http_server_requests_seconds_bucket{application="product-api"}[1m])
  )
)
```

```promql
histogram_quantile(
  0.99,
  sum by (le) (
    rate(http_server_requests_seconds_bucket{application="product-api"}[1m])
  )
)
```

## 문제 해결

### `spring-app` target이 DOWN인 경우

- Spring Boot 앱이 실제로 `8081` 포트에서 실행 중인지 확인
- `/actuator/prometheus` endpoint가 노출되는지 확인
- 앱이 외부 접근 가능한 주소로 바인딩되어 있는지 확인

`docker-compose.yml`의 `extra_hosts` 설정은 컨테이너 안의 `/etc/hosts`에 호스트 이름을 강제로 추가하는 용도입니다. 여기서는 `host.docker.internal`을 Docker 호스트 게이트웨이로 매핑해서, 로컬에서 실행 중인 Spring Boot 앱으로 접근하게 합니다.

### Tomcat 지표가 보이지 않는 경우

- `server.tomcat.mbeanregistry.enabled=true` 설정 확인
- Tomcat 기반 애플리케이션인지 확인

### HikariCP 지표가 보이지 않는 경우

- HikariCP를 실제로 사용 중인지 확인
- `spring-boot-starter-jdbc` 또는 JPA 사용 여부 확인
- `/actuator/metrics`에서 `hikaricp` 또는 `jdbc.connections` meter 존재 여부 확인

## 중지

```sh
docker compose down
```
