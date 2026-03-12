#!/bin/sh

set -eu

: "${REDIS_APP_USERNAME:?REDIS_APP_USERNAME is required}"
: "${REDIS_APP_PASSWORD:?REDIS_APP_PASSWORD is required}"
: "${REDIS_READONLY_USERNAME:?REDIS_READONLY_USERNAME is required}"
: "${REDIS_READONLY_PASSWORD:?REDIS_READONLY_PASSWORD is required}"

cp /seed/redis/redis.conf /usr/local/etc/redis/redis.conf

cat > /usr/local/etc/redis/users.acl <<EOF
user default off sanitize-payload resetchannels -@all
user ${REDIS_APP_USERNAME} on >${REDIS_APP_PASSWORD} ~* &* +@all
user ${REDIS_READONLY_USERNAME} on >${REDIS_READONLY_PASSWORD} ~* &* -@all +@read +ping +info
EOF

exec redis-server /usr/local/etc/redis/redis.conf
