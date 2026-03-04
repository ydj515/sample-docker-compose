#!/bin/sh
set -eu

docker exec redis-node-1 redis-cli --cluster create \
  172.31.0.11:7001 \
  172.31.0.12:7002 \
  172.31.0.13:7003 \
  172.31.0.14:7004 \
  172.31.0.15:7005 \
  172.31.0.16:7006 \
  --cluster-replicas 1 \
  --cluster-yes
