# docker-compose-sample

A collection of `docker-compose` setups

## Gateway

- [apisix](./apisix/README.md) : nginx, apisix, etcd, redis, prometheus, grafana
- [agentgateway](./agentgateway/README.md) : single / ha, MCP demo server built from source (Docker Compose)

## Database

- [postgresql](./postgresql/README.md) : postgresql 17, postgis, pgvector, pg-search, timescaledb, citus(single / multi-node), pg-cron, pg-stat-statements, pg-trgm
- [mysql](./mysql/README.md) : mysql 8.4
- [mongodb](./mongodb/README.md) : mongodb-single, replica set, sharded cluster
- [redis](./redis/README.md) : redis-single, redis-replica, redis-sentinel, redis-cluster

## Messaging

- [kafka](./kafka/README.md) : kRaft cluster, zookeeper cluster, single kafka

## Logging / Monitoring

- [elk](./elk/README.md) : elasticsearch logstash, kibana, metricbeat
- [opentelemetry](./opentelemetry/README.md) : opentelemetryCollector, jaeger, loki, prometheus, tempo, promtail, grafana
- [llm-monitoring](./llm-monitoring/README.md) : opentelemetryCollector, jaeger, loki, prometheus, tempo, promtail, grafana, postgresql, redis for codex monitoring
- [jvm-monitoring](./jvm-monitoring/README.md) : prometheus, grafana, node-exporter, cadvisor for spring boot + k6 load test

## Load Test

- [k6-dashboard](./k6-dashboard/README.md) : influxdb, grafana, nginx
