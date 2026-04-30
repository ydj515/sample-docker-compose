#!/usr/bin/env python3
"""Serve the generated Prometheus metrics file over HTTP."""

from __future__ import annotations

import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


METRICS_FILE = Path(os.getenv("METRICS_FILE", "/var/www/metrics"))
PORT = int(os.getenv("EXPORTER_PORT", "9107"))
REFRESH_SECONDS = int(os.getenv("EXPORTER_REFRESH_SECONDS", "60"))
HEALTH_MAX_AGE_SECONDS = int(
    os.getenv(
        "EXPORTER_HEALTH_MAX_AGE_SECONDS",
        str(max(REFRESH_SECONDS * 3, REFRESH_SECONDS + 30)),
    )
)


def build_health_payload() -> tuple[int, bytes]:
    exists = METRICS_FILE.exists()
    now = time.time()
    last_modified_epoch = METRICS_FILE.stat().st_mtime if exists else None
    age_seconds = (now - last_modified_epoch) if last_modified_epoch is not None else None
    is_fresh = exists and age_seconds is not None and age_seconds <= HEALTH_MAX_AGE_SECONDS
    status_code = HTTPStatus.OK if is_fresh else HTTPStatus.SERVICE_UNAVAILABLE
    payload = {
        "status": "ok" if is_fresh else "stale",
        "metrics_file": str(METRICS_FILE),
        "metrics_file_exists": exists,
        "refresh_seconds": REFRESH_SECONDS,
        "health_max_age_seconds": HEALTH_MAX_AGE_SECONDS,
        "metrics_age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "last_modified_epoch": round(last_modified_epoch, 3) if last_modified_epoch is not None else None,
    }
    return status_code, (json.dumps(payload) + "\n").encode("utf-8")


class MetricsHandler(BaseHTTPRequestHandler):
    server_version = "codex-ops-exporter/1.0"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        if self.path == "/healthz":
            status_code, body = build_health_payload()
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path not in ("/metrics", "/"):
            self.send_error(HTTPStatus.NOT_FOUND, "not found")
            return

        body = METRICS_FILE.read_bytes() if METRICS_FILE.exists() else b""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), MetricsHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
