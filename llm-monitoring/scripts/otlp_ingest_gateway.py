#!/usr/bin/env python3
"""OTLP HTTP ingress gateway.

x-codex-ingest-token 헤더를 검증해 canonical identity attribute를 주입한 뒤
내부 OTel Collector로 전달한다.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from runtime_common import add_postgres_args, load_identity_maps, resolve_postgres_target


IDENTITY_SOURCE = "ingest_token"


def parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def now_monotonic() -> float:
    return time.monotonic()


class IdentityCache:
    def __init__(self, *, cache_seconds: int, accept_token_id_header: bool, postgres_args: list[str]) -> None:
        self.cache_seconds = cache_seconds
        self.accept_token_id_header = accept_token_id_header
        self.postgres_args = postgres_args
        self._lock = threading.Lock()
        self._loaded_at = 0.0
        self._maps = None

    def _load_maps(self):
        parser = self._build_parser()
        args = parser.parse_args(self.postgres_args)
        target = resolve_postgres_target(args)
        return load_identity_maps(target)

    @staticmethod
    def _build_parser():
        import argparse

        parser = argparse.ArgumentParser(add_help=False)
        add_postgres_args(parser)
        return parser

    def _ensure_maps(self):
        with self._lock:
            stale = self._maps is None or (now_monotonic() - self._loaded_at) >= self.cache_seconds
            if stale:
                self._maps = self._load_maps()
                self._loaded_at = now_monotonic()
            return self._maps

    def resolve(self, raw_token: str | None) -> dict[str, str] | None:
        if not raw_token:
            return None
        maps = self._ensure_maps()
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token_entry = maps.token_hash_mappings.get(token_hash.lower())
        if token_entry is None and self.accept_token_id_header:
            token_entry = maps.token_mappings.get(raw_token)
        if token_entry is None:
            return None
        ingest_token_id = token_entry.get("ingest_token_id")
        resolved_user_id = token_entry.get("resolved_user_id")
        resolved_team = token_entry.get("resolved_team")
        payload = {}
        if ingest_token_id:
            payload["ingest_token_id"] = ingest_token_id
        if resolved_user_id:
            payload["resolved_user_id"] = resolved_user_id
        if resolved_team:
            payload["resolved_team"] = resolved_team
        if payload:
            payload["identity_source"] = IDENTITY_SOURCE
        return payload or None


def json_attr(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def upsert_json_attributes(container: dict[str, Any], values: dict[str, str]) -> None:
    attributes = container.setdefault("attributes", [])
    if not isinstance(attributes, list):
        attributes = []
        container["attributes"] = attributes
    attr_index: dict[str, dict[str, Any]] = {}
    for item in attributes:
        if isinstance(item, dict) and "key" in item:
            attr_index[str(item["key"])] = item
    for key, value in values.items():
        existing = attr_index.get(key)
        if existing is None:
            item = json_attr(key, value)
            attributes.append(item)
            attr_index[key] = item
        else:
            existing["value"] = {"stringValue": value}


def inject_json_identity(endpoint: str, payload: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    if endpoint == "/v1/logs":
        for resource_log in payload.get("resourceLogs", []):
            resource = resource_log.setdefault("resource", {})
            upsert_json_attributes(resource, values)
            for scope_log in resource_log.get("scopeLogs", []):
                for log_record in scope_log.get("logRecords", []):
                    upsert_json_attributes(log_record, values)
        return payload

    if endpoint == "/v1/metrics":
        for resource_metric in payload.get("resourceMetrics", []):
            resource = resource_metric.setdefault("resource", {})
            upsert_json_attributes(resource, values)
            for scope_metric in resource_metric.get("scopeMetrics", []):
                for metric in scope_metric.get("metrics", []):
                    for field_name in (
                        "sum",
                        "gauge",
                        "histogram",
                        "exponentialHistogram",
                        "summary",
                    ):
                        metric_body = metric.get(field_name)
                        if not isinstance(metric_body, dict):
                            continue
                        for data_point in metric_body.get("dataPoints", []):
                            upsert_json_attributes(data_point, values)
        return payload

    if endpoint == "/v1/traces":
        for resource_span in payload.get("resourceSpans", []):
            resource = resource_span.setdefault("resource", {})
            upsert_json_attributes(resource, values)
            for scope_span in resource_span.get("scopeSpans", []):
                for span in scope_span.get("spans", []):
                    upsert_json_attributes(span, values)
        return payload

    return payload


def upsert_proto_attributes(attributes, values: dict[str, str]) -> None:
    index = {item.key: item for item in attributes}
    for key, value in values.items():
        item = index.get(key)
        if item is None:
            item = attributes.add()
            item.key = key
            index[key] = item
        item.value.string_value = value


def inject_logs_proto(body: bytes, values: dict[str, str]) -> bytes:
    request = logs_service_pb2.ExportLogsServiceRequest()
    request.ParseFromString(body)
    for resource_log in request.resource_logs:
        upsert_proto_attributes(resource_log.resource.attributes, values)
        for scope_log in resource_log.scope_logs:
            for record in scope_log.log_records:
                upsert_proto_attributes(record.attributes, values)
    return request.SerializeToString()


def inject_metrics_proto(body: bytes, values: dict[str, str]) -> bytes:
    request = metrics_service_pb2.ExportMetricsServiceRequest()
    request.ParseFromString(body)
    for resource_metric in request.resource_metrics:
        upsert_proto_attributes(resource_metric.resource.attributes, values)
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.HasField("sum"):
                    for point in metric.sum.data_points:
                        upsert_proto_attributes(point.attributes, values)
                if metric.HasField("gauge"):
                    for point in metric.gauge.data_points:
                        upsert_proto_attributes(point.attributes, values)
                if metric.HasField("histogram"):
                    for point in metric.histogram.data_points:
                        upsert_proto_attributes(point.attributes, values)
                if metric.HasField("exponential_histogram"):
                    for point in metric.exponential_histogram.data_points:
                        upsert_proto_attributes(point.attributes, values)
                if metric.HasField("summary"):
                    for point in metric.summary.data_points:
                        upsert_proto_attributes(point.attributes, values)
    return request.SerializeToString()


def inject_traces_proto(body: bytes, values: dict[str, str]) -> bytes:
    request = trace_service_pb2.ExportTraceServiceRequest()
    request.ParseFromString(body)
    for resource_span in request.resource_spans:
        upsert_proto_attributes(resource_span.resource.attributes, values)
        for scope_span in resource_span.scope_spans:
            for span in scope_span.spans:
                upsert_proto_attributes(span.attributes, values)
    return request.SerializeToString()


def maybe_decompress(body: bytes, encoding: str | None) -> tuple[bytes, bool]:
    if encoding and "gzip" in encoding.lower():
        return gzip.decompress(body), True
    return body, False


def maybe_recompress(body: bytes, compressed: bool) -> bytes:
    if not compressed:
        return body
    return gzip.compress(body)


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "codex-ingest-gateway/1.0"

    def do_GET(self) -> None:
        if self.path != "/healthz":
            self.send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        body = json.dumps({"status": "ok"}).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path not in {"/v1/logs", "/v1/metrics", "/v1/traces"}:
            self.send_error(HTTPStatus.NOT_FOUND, "unsupported path")
            return

        raw_token = self.headers.get("x-codex-ingest-token")
        if self.server.require_token and not raw_token:
            self._write_error(HTTPStatus.UNAUTHORIZED, "x-codex-ingest-token header is required")
            return

        identity_values = self.server.identity_cache.resolve(raw_token)
        if raw_token and identity_values is None and not self.server.allow_unmapped:
            self._write_error(HTTPStatus.FORBIDDEN, "unknown ingest token")
            return

        body_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(body_length)
        content_encoding = self.headers.get("Content-Encoding")
        decoded_body, was_compressed = maybe_decompress(raw_body, content_encoding)
        content_type = self.headers.get("Content-Type", "application/x-protobuf")
        outgoing_body = decoded_body

        if identity_values:
            if "json" in content_type.lower():
                payload = json.loads(decoded_body.decode("utf-8"))
                payload = inject_json_identity(self.path, payload, identity_values)
                outgoing_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            else:
                if self.path == "/v1/logs":
                    outgoing_body = inject_logs_proto(decoded_body, identity_values)
                elif self.path == "/v1/metrics":
                    outgoing_body = inject_metrics_proto(decoded_body, identity_values)
                else:
                    outgoing_body = inject_traces_proto(decoded_body, identity_values)

        forwarded_body = maybe_recompress(outgoing_body, was_compressed)
        forward_url = f"{self.server.forward_base_url}{self.path}"
        forward_headers = {}
        for key, value in self.headers.items():
            lowered = key.lower()
            if lowered in {"host", "content-length", "x-codex-ingest-token"}:
                continue
            forward_headers[key] = value
        forward_headers["Content-Length"] = str(len(forwarded_body))

        request = urllib.request.Request(
            forward_url,
            data=forwarded_body,
            headers=forward_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.server.forward_timeout_seconds) as response:
                response_body = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() in {"transfer-encoding", "content-length", "connection"}:
                        continue
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)
        except urllib.error.HTTPError as error:
            response_body = error.read()
            self.send_response(error.code)
            self.send_header("Content-Type", error.headers.get("Content-Type", "text/plain"))
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
        except urllib.error.URLError as error:
            self._write_error(HTTPStatus.BAD_GATEWAY, f"collector forward failed: {error.reason}")

    def log_message(self, format: str, *args: object) -> None:
        print(
            "%s - - [%s] %s"
            % (self.address_string(), self.log_date_time_string(), format % args),
            flush=True,
        )

    def _write_error(self, status: HTTPStatus, message: str) -> None:
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GatewayServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        handler_cls,
        *,
        forward_base_url: str,
        identity_cache: IdentityCache,
        require_token: bool,
        allow_unmapped: bool,
        forward_timeout_seconds: int,
    ) -> None:
        super().__init__(address, handler_cls)
        self.forward_base_url = forward_base_url.rstrip("/")
        self.identity_cache = identity_cache
        self.require_token = require_token
        self.allow_unmapped = allow_unmapped
        self.forward_timeout_seconds = forward_timeout_seconds


def main() -> int:
    port = int(os.getenv("INGEST_GATEWAY_PORT", "4318"))
    cache_seconds = int(os.getenv("INGEST_GATEWAY_CACHE_SECONDS", "30"))
    require_token = parse_bool_env("INGEST_GATEWAY_REQUIRE_TOKEN", False)
    allow_unmapped = parse_bool_env("INGEST_GATEWAY_ALLOW_UNMAPPED", True)
    accept_token_id_header = parse_bool_env("INGEST_GATEWAY_ACCEPT_TOKEN_ID_HEADER", False)
    forward_base_url = os.getenv("INGEST_GATEWAY_FORWARD_BASE_URL", "http://otel-collector:4318")
    forward_timeout_seconds = int(os.getenv("INGEST_GATEWAY_FORWARD_TIMEOUT_SECONDS", "15"))

    postgres_args = []
    for key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_HOST", "POSTGRES_PORT"):
        value = os.getenv(key)
        if value:
            postgres_args.extend([f"--{key.lower().replace('_', '-')}", value])

    server = GatewayServer(
        ("0.0.0.0", port),
        GatewayHandler,
        forward_base_url=forward_base_url,
        identity_cache=IdentityCache(
            cache_seconds=cache_seconds,
            accept_token_id_header=accept_token_id_header,
            postgres_args=postgres_args,
        ),
        require_token=require_token,
        allow_unmapped=allow_unmapped,
        forward_timeout_seconds=forward_timeout_seconds,
    )
    print(
        f"OTLP ingest gateway listening on 0.0.0.0:{port}, "
        f"forward_base_url={server.forward_base_url}, "
        f"require_token={require_token}, allow_unmapped={allow_unmapped}",
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
