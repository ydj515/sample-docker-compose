ARG BASE_IMAGE=citusdata/citus:14.2.0-pg17@sha256:a8e720198e83d9f8bd3884a0aeb32aa1e2b426393fba96882587c9fe607d1417
FROM ${BASE_IMAGE}

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-cron=1.6.8-1.pgdg13+1 \
    && rm -rf /var/lib/apt/lists/*
