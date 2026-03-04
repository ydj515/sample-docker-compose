#!/bin/sh
set -eu

NODES="
redis-node-1:7001
redis-node-2:7002
redis-node-3:7003
redis-node-4:7004
redis-node-5:7005
redis-node-6:7006
"

echo "Redis Cluster 상태 확인"

for node in $NODES
do
  host="${node%:*}"
  port="${node#*:}"

  echo ""
  echo "[$host:$port] 상태 점검"

  status="$(docker exec "$host" redis-cli -p "$port" PING)"
  if [ "$status" = "PONG" ]; then
    echo "연결 상태: 정상"
  else
    echo "연결 상태: 비정상"
    continue
  fi

  docker exec "$host" redis-cli -p "$port" cluster nodes
done

echo ""
echo "Redis Cluster 상태 확인 완료"
