import os
import time
import requests
from prometheus_client import Gauge, start_http_server

limit_req_rate = Gauge(
    "apisix_limit_req_rate",
    "Current rate limit of limit-req plugin",
    ["route"],
)

ADMIN_API_URL = os.environ.get(
    "ADMIN_API_URL",
    "http://apisix1:9180/apisix/admin/routes",
)
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")
EXPORTER_PORT = int(os.environ.get("EXPORTER_PORT", "8000"))
SCRAPE_INTERVAL_SECONDS = float(os.environ.get("SCRAPE_INTERVAL_SECONDS", "1"))
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "5"))

def fetch_all_routes():
    headers = {"X-API-KEY": ADMIN_API_KEY}
    try:
        response = requests.get(
            ADMIN_API_URL,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("list", [])
    except Exception as e:
        print(f"[ERROR] Failed to fetch routes: {e}")
        return []

def update_metrics():
    routes = fetch_all_routes()
    for route in routes:
        route_id = route.get("value", {}).get("id")
        plugins = route.get("value", {}).get("plugins", {})

        if not route_id or "limit-req" not in plugins:
            continue

        try:
            rate = plugins["limit-req"]["rate"]
            limit_req_rate.labels(route=str(route_id)).set(rate)
            print(f"[OK] Route {route_id} - rate: {rate}")
        except Exception as e:
            print(f"[ERROR] Route {route_id} - failed to extract rate: {e}")

if __name__ == "__main__":
    start_http_server(EXPORTER_PORT)
    while True:
        update_metrics()
        time.sleep(SCRAPE_INTERVAL_SECONDS)
