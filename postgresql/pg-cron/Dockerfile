ARG BASE_IMAGE=postgres:17.11-bookworm@sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652
FROM ${BASE_IMAGE}

# PostgreSQL 메이저 버전에 맞는 pg_cron 패키지 설치
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-cron=1.6.8-1.pgdg12+1 \
    && rm -rf /var/lib/apt/lists/*
