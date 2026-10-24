"""Verify shared HTTP quotas against real gateways, Envoy RLS and Redis."""

import argparse
import concurrent.futures
import os
from pathlib import Path
import subprocess
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

parser = argparse.ArgumentParser()
parser.add_argument('urls', nargs='*')
parser.add_argument('--lifecycle', type=Path, help='Compose directory; enables local service restart/outage checks')
args = parser.parse_args()
BASES = [url.rstrip('/') for url in args.urls] or ['http://127.0.0.1:14001', 'http://127.0.0.1:14002']


def get(base, client, path='/global-limit', timeout=40):
    req = urllib.request.Request(base + path, headers={'x-demo-client': client})

    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc

    with response:
        body = response.read()
        if response.status == 200:
            assert json.loads(body) == {'status': 'ok'}, body

        return response.status


def ready():
    for _ in range(30):
        try:
            if all(get(base, uuid.uuid4().hex, timeout=2) == 200 for base in BASES):
                return
        except (OSError, ValueError):
            pass

        time.sleep(0.5)

    raise AssertionError('Gateways/RLS not ready after 30 probes')


ready()
# Avoid the fixed hourly boundary during an exact-count experiment.
assert time.time() % 3600 < 3570, 'Rerun after the hourly bucket boundary'

# Isolate this run from earlier counters while sharing one identity across replicas.
client = uuid.uuid4().hex
codes = [get(BASES[i % len(BASES)], client) for i in range(7)]
assert codes == [200] * 5 + [429] * 2, codes
print('PASS: alternating gateways share five total requests, then both reject')

assert get(BASES[-1], uuid.uuid4().hex) == 200
print('PASS: another client has an independent bucket')

client = uuid.uuid4().hex
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
    codes = list(pool.map(lambda i: get(BASES[i % len(BASES)], client), range(12)))

assert codes.count(200) == 5 and codes.count(429) == 7, codes
print('PASS: 12 concurrent requests across gateways allow exactly five')

# Start early in a second so the three requests fit in one fixed window.
for attempt in range(3):
    client = uuid.uuid4().hex
    time.sleep(1.05 - time.time() % 1)
    start_window = int(time.time())
    codes = [get(BASES[i % len(BASES)], client, '/global-recovery') for i in range(3)]
    if int(time.time()) == start_window:
        break
else:
    raise AssertionError('Could not fit recovery probe in one window')

assert codes == [200, 200, 429], codes

time.sleep(1.1)
assert get(BASES[-1], client, '/global-recovery') == 200
print('PASS: shared short-window limit recovers after rollover')


if args.lifecycle:
    env = {**os.environ, 'AGENTGATEWAY_CONFIG': './config-global-ratelimit.yaml',
           'LOCAL_UID': str(os.getuid()), 'LOCAL_GID': str(os.getgid())}
    compose = ['docker', 'compose', '-f', 'docker-compose.yml', '-f', 'compose-global-ratelimit.yml']

    def service(*command):
        subprocess.run(compose + list(command), cwd=args.lifecycle, env=env, check=True)

    # Exhaust once, then reuse this identity across restarts to detect lost counters.
    client = uuid.uuid4().hex
    assert [get(BASES[0], client) for _ in range(5)] == [200] * 5

    service('restart', 'ratelimit')
    ready()
    assert all(get(base, client) == 429 for base in BASES)
    print('PASS: RLS restart preserves exhausted Redis bucket')

    service('restart', 'redis')
    ready()

    # Redis pool connections can fail transiently after restart; never accept a 200.
    for base in BASES:
        for attempt in range(10):
            code = get(base, client)
            if code != 500:
                break

            time.sleep(0.2)

        assert code == 429, ('Quota after Redis restart', code)

    print('PASS: graceful Redis restart preserves AOF-backed quota')

    gateway = 'gateway-1' if len(BASES) > 1 else 'agentgateway'
    service('restart', gateway)
    ready()
    assert all(get(base, client) == 429 for base in BASES)
    print('PASS: gateway restart does not reset shared quota')

    try:
        service('stop', 'ratelimit')
        start = time.monotonic()
        codes = [get(base, uuid.uuid4().hex) for base in BASES]
        assert codes == [500] * len(BASES), codes
        print(f'PASS: RLS unavailable returns HTTP 500 (explicit failClosed), total elapsed={time.monotonic() - start:.2f}s')
    finally:
        # Restore the dependency even if an outage assertion fails.
        service('start', 'ratelimit')
        ready()

    assert all(get(base, client) == 429 for base in BASES)
    print('PASS: RLS recovery permits new clients without resetting exhausted quota')
