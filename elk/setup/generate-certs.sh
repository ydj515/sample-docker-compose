#!/bin/bash

set -euo pipefail

CERTS_DIR="/usr/share/elasticsearch/config/certs"

if [ -f "${CERTS_DIR}/ca/ca.crt" ]; then
  echo "Certificates already exist."
  exit 0
fi

mkdir -p "${CERTS_DIR}"

cat > "${CERTS_DIR}/instances.yml" <<'YAML'
instances:
  - name: es-master01
    dns:
      - es-master01
  - name: es-master02
    dns:
      - es-master02
  - name: es-master03
    dns:
      - es-master03
  - name: es-data01
    dns:
      - es-data01
  - name: es-data02
    dns:
      - es-data02
  - name: es-ingest01
    dns:
      - es-ingest01
YAML

/usr/share/elasticsearch/bin/elasticsearch-certutil ca --silent --pem --out "${CERTS_DIR}/ca.zip"
unzip "${CERTS_DIR}/ca.zip" -d "${CERTS_DIR}"

/usr/share/elasticsearch/bin/elasticsearch-certutil cert \
  --silent \
  --pem \
  --in "${CERTS_DIR}/instances.yml" \
  --ca-cert "${CERTS_DIR}/ca/ca.crt" \
  --ca-key "${CERTS_DIR}/ca/ca.key" \
  --out "${CERTS_DIR}/certs.zip"

unzip "${CERTS_DIR}/certs.zip" -d "${CERTS_DIR}"

chown -R root:root "${CERTS_DIR}"
find "${CERTS_DIR}" -type d -exec chmod 750 {} \;
find "${CERTS_DIR}" -type f -exec chmod 640 {} \;

echo "Certificates generated."
