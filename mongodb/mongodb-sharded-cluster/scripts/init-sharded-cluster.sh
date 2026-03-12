#!/usr/bin/env bash

set -euo pipefail

wait_for_ping() {
  local host="$1"
  local port="$2"

  until mongosh --host "$host" --port "$port" --quiet --eval "db.adminCommand('ping').ok" >/dev/null 2>&1; do
    echo "waiting for $host:$port"
    sleep 2
  done
}

wait_for_repl_ready() {
  local host="$1"
  local port="$2"

  until mongosh --host "$host" --port "$port" --quiet --eval "db.hello().isWritablePrimary || db.hello().secondary" | grep true >/dev/null 2>&1; do
    echo "waiting for replica set readiness on $host:$port"
    sleep 2
  done
}

wait_for_ping "configsvr1" "27019"
wait_for_ping "configsvr2" "27019"
wait_for_ping "configsvr3" "27019"
wait_for_ping "shard1-1" "27018"
wait_for_ping "shard1-2" "27018"
wait_for_ping "shard1-3" "27018"

config_status="$(mongosh --host configsvr1 --port 27019 --quiet --eval "try { rs.status().ok } catch (e) { print(0) }")"
if [ "$config_status" != "1" ]; then
  mongosh --host configsvr1 --port 27019 --quiet --eval '
    rs.initiate({
      _id: "configReplSet",
      configsvr: true,
      members: [
        { _id: 0, host: "configsvr1:27019" },
        { _id: 1, host: "configsvr2:27019" },
        { _id: 2, host: "configsvr3:27019" }
      ]
    })
  '
fi

wait_for_repl_ready "configsvr1" "27019"

shard_status="$(mongosh --host shard1-1 --port 27018 --quiet --eval "try { rs.status().ok } catch (e) { print(0) }")"
if [ "$shard_status" != "1" ]; then
  mongosh --host shard1-1 --port 27018 --quiet --eval '
    rs.initiate({
      _id: "shard1ReplSet",
      members: [
        { _id: 0, host: "shard1-1:27018", priority: 2 },
        { _id: 1, host: "shard1-2:27018", priority: 1 },
        { _id: 2, host: "shard1-3:27018", priority: 1 }
      ]
    })
  '
fi

wait_for_repl_ready "shard1-1" "27018"
wait_for_ping "mongos" "27017"

if ! mongosh --host mongos --port 27017 --quiet --eval "sh.status()" | grep "shard1ReplSet" >/dev/null 2>&1; then
  mongosh --host mongos --port 27017 --quiet --eval 'sh.addShard("shard1ReplSet/shard1-1:27018,shard1-2:27018,shard1-3:27018")'
fi

echo "sharded cluster initialized"
