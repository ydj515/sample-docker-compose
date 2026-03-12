#!/usr/bin/env bash

set -euo pipefail

mongo_uri() {
  local host="$1"
  printf 'mongodb://%s:%s@%s:27017/admin?directConnection=true' \
    "$MONGO_ROOT_USERNAME" \
    "$MONGO_ROOT_PASSWORD" \
    "$host"
}

wait_for_mongo() {
  local host="$1"

  until mongosh "$(mongo_uri "$host")" --quiet --eval "db.adminCommand('ping').ok" >/dev/null 2>&1; do
    echo "waiting for $host"
    sleep 2
  done
}

wait_for_mongo "mongo1"
wait_for_mongo "mongo2"
wait_for_mongo "mongo3"

status="$(mongosh "$(mongo_uri "mongo1")" --quiet --eval "try { rs.status().ok } catch (e) { print(0) }")"

if [ "$status" != "1" ]; then
  mongosh "$(mongo_uri "mongo1")" --quiet --eval '
    rs.initiate({
      _id: "rs0",
      members: [
        { _id: 0, host: "mongo1:27017", priority: 2 },
        { _id: 1, host: "mongo2:27017", priority: 1 },
        { _id: 2, host: "mongo3:27017", priority: 1 }
      ]
    })
  '
fi

until mongosh "$(mongo_uri "mongo1")" --quiet --eval "rs.status().members.filter(member => member.stateStr === 'PRIMARY').length" | grep 1 >/dev/null 2>&1; do
  echo "waiting for replica set election"
  sleep 2
done

echo "replica set initialized"
