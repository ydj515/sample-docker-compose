#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
for node in citus-coordinator citus-worker-1 citus-worker-2; do
  docker compose exec -T "$node" sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS citus;"'
done
docker compose exec -T citus-coordinator sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' <<'SQL'
SELECT citus_set_coordinator_host('citus-coordinator', 5432);
SELECT citus_add_node('citus-worker-1', 5432)
WHERE NOT EXISTS (SELECT 1 FROM pg_dist_node WHERE nodename = 'citus-worker-1' AND nodeport = 5432);
SELECT citus_add_node('citus-worker-2', 5432)
WHERE NOT EXISTS (SELECT 1 FROM pg_dist_node WHERE nodename = 'citus-worker-2' AND nodeport = 5432);
SET citus.enable_ddl_propagation = off;
CREATE EXTENSION IF NOT EXISTS pg_cron;
RESET citus.enable_ddl_propagation;
SELECT nodeid, nodename, nodeport, isactive FROM pg_dist_node ORDER BY nodeid;
SQL
