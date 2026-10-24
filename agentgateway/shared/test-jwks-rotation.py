"""Observe actual Gateway key-cache transitions against a local signing fixture.

Only fixture control state and local Gateway processes are changed. Tokens remain in memory.
"""

import argparse
import json
import os
from pathlib import Path
import ssl
import subprocess
import time
import urllib.error
import urllib.request

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('root', type=Path)
p.add_argument('cert_dir', type=Path)
p.add_argument('--recovery-only', action='store_true', help='Resume after a published A+B recovery with cached B only')
a = p.parse_args()
root = a.root.resolve()
assert root.name in ('single', 'ha')

fixture = f'http://localhost:{18090 if root.name == "single" else 28090}'
ports = [3443] if root.name == 'single' else [14401, 14402, 13443]
urls = [f'https://localhost:{port}/mcp/mtls' for port in ports]
ctx = ssl.create_default_context(cafile=str(a.cert_dir / 'ca.crt'))
ctx.load_cert_chain(a.cert_dir / 'client/tls.crt', a.cert_dir / 'client/tls.key')


def request(url, body=None, token=None):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
    if token: headers['Authorization'] = 'Bearer ' + token

    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)

    try:
        r = urllib.request.urlopen(req, timeout=10, context=ctx if url.startswith('https:') else None)
    except urllib.error.HTTPError as exc:
        r = exc

    with r:
        raw = r.read()
        if 'text/event-stream' in r.headers.get('Content-Type', ''):
            raw = next(line[5:] for line in raw.splitlines() if line.startswith(b'data:'))

        try: data = json.loads(raw)
        except ValueError: data = {}

        return r.status, data


def control(keys, unavailable=False):
    assert request(fixture + '/control', {'published': keys, 'unavailable': unavailable})[0] == 200


def statuses(token):
    results = []
    for url in urls:
        status, payload = request(url, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'key-rotation', 'version': '1'}}}, token)
        if status == 200: assert 'result' in payload, 'Unexpected MCP initialize response'

        results.append(status)

    return results


def wait_for(label, predicate, timeout=180, required=True):
    start = time.monotonic()
    next_report = 0
    while time.monotonic() - start < timeout:
        elapsed = time.monotonic() - start
        if predicate():
            print(f'PASS: {label}, observed after {elapsed:.1f}s', flush=True)
            return True

        if elapsed >= next_report:
            print(f'Waiting: {label} ({elapsed:.0f}s)', flush=True)
            next_report += 20

        time.sleep(2)

    if required:
        raise AssertionError(f'Timed out: {label}')

    return False


if not a.recovery_only:
    control(['A'])

compose = ['docker', 'compose', '-f', str(root / 'docker-compose.yml'), '-f', str(root / 'compose-mtls.yml'),
           '-f', str(root / 'compose-jwks-rotation.yml')]
env = {**os.environ, 'LOCAL_UID': str(os.getuid()), 'LOCAL_GID': str(os.getgid()),
       'MTLS_CERT_DIR': str(a.cert_dir.resolve()), 'AGENTGATEWAY_CONFIG': './config-jwks-rotation.yaml'}
gateways = ['agentgateway'] if root.name == 'single' else ['gateway-1', 'gateway-2']
if not a.recovery_only:
    subprocess.run(compose + ['restart', *gateways], env=env, check=True, capture_output=True)

tokens = {}
for kid in ('A', 'B'):
    status, payload = request(fixture + '/token?kid=' + kid, {})
    assert status == 200

    tokens[kid] = payload['access_token']

try:
    if a.recovery_only:
        assert statuses(tokens['A']) == [401] * len(urls) and statuses(tokens['B']) == [200] * len(urls), 'Recovery-only requires cached B and rejected A'

    if not a.recovery_only:
        # Readiness retries do not turn TLS validation failures into successful checks.
        def ready():
            try: return statuses(tokens['A']) == [200] * len(urls)
            except (urllib.error.URLError, ConnectionError): return False
        wait_for('initial A accepted on every endpoint', ready, 30)
        assert statuses(tokens['B']) == [401] * len(urls)

        control(['A', 'B'])
        immediate = statuses(tokens['B'])
        print('OBSERVED: new kid immediately after publication -> ' + ','.join(map(str, immediate)), flush=True)

        wait_for('overlap A+B: new B accepted', lambda: statuses(tokens['B']) == [200] * len(urls))
        assert statuses(tokens['A']) == [200] * len(urls), 'Old token rejected during overlap'

        control(['B'])
        print('OBSERVED: A immediately after removal -> ' + ','.join(map(str, statuses(tokens['A']))), flush=True)

        wait_for('retired A rejected', lambda: statuses(tokens['A']) == [401] * len(urls))
        assert statuses(tokens['B']) == [200] * len(urls)

        failures = request(fixture + '/stats')[1]['failures']
        control(['B'], True)
        wait_for('background JWKS refresh encounters HTTP 503', lambda: request(fixture + '/stats')[1]['failures'] > failures)
        assert statuses(tokens['B']) == [200] * len(urls), 'Last-known-good B unavailable during outage'
        assert statuses(tokens['A']) == [401] * len(urls), 'Retired key returned during outage'
        print('PASS: outage retains cached B; retired A remains denied', flush=True)

    control(['A', 'B'])
    if not wait_for('automatic JWKS recovery reloads A', lambda: statuses(tokens['A']) == [200] * len(urls), 60, required=False):
        print('LIMITATION: HTTP 503/no-store recovery not reflected within 60s; restarting local Gateways', flush=True)

        subprocess.run(compose + ['restart', *gateways], env=env, check=True, capture_output=True)
        def recovered():
            try: return statuses(tokens['A']) == [200] * len(urls)
            except (urllib.error.URLError, ConnectionError): return False
        wait_for('restart recovery reloads A on every endpoint', recovered, 30)

    assert statuses(tokens['B']) == [200] * len(urls)
finally:
    control(['A', 'B'])

print('PASS: selected key lifecycle checks completed; automatic and restart recovery are reported separately', flush=True)
