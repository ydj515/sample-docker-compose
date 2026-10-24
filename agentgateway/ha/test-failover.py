"""Stop each gateway in turn and verify requests through the load balancer."""

import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:13000/mcp'


def compose(*args):
    subprocess.run(['docker', 'compose', *args], cwd=ROOT, check=True)


def probe():
    request = urllib.request.Request(URL, data=json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': 'echo', 'arguments': {'message': 'ha-probe'}},
    }).encode(), headers={
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
        'MCP-Protocol-Version': '2025-03-26',
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        assert response.headers.get('Mcp-Session-Id') is None, 'Expected stateless MCP'

        if 'text/event-stream' in response.headers.get('Content-Type', ''):
            payload = next(json.loads(line[5:]) for line in response if line.startswith(b'data:'))
        else:
            payload = json.load(response)

        assert payload['result']['content'][0]['text'] == 'ha-probe', payload

        # A failed connection followed by a successful retry lists both addresses.
        return response.headers['X-Gateway-Upstream'].split(',')[-1].strip()


def wait_for_both():
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            backends = {probe() for _ in range(6)}
            if len(backends) == 2:
                return backends
        except (OSError, ValueError, KeyError):
            pass

        time.sleep(1)

    raise RuntimeError('Both gateway instances did not become available')


def wait_for_survivor():
    started = time.monotonic()
    failures = 0
    while time.monotonic() - started < 30:
        try:
            # Require six consecutive successes; a single response can hide unstable failover.
            backends = {probe() for _ in range(6)}
            if len(backends) == 1:
                print(f'Recovered in {time.monotonic() - started:.1f}s; transient failures: {failures}', flush=True)
                return next(iter(backends))
        except OSError:
            failures += 1

        time.sleep(1)

    raise RuntimeError('Failover did not recover within 30 seconds')


if __name__ == '__main__':
    print('Both gateways:', sorted(wait_for_both()), flush=True)

    subprocess.run([sys.executable, str(ROOT / '../shared/smoke-test.py'), URL], check=True)
    survivors = []
    for gateway in ('gateway-1', 'gateway-2'):
        try:
            compose('stop', gateway)
            survivors.append(wait_for_survivor())
            subprocess.run([sys.executable, str(ROOT / '../shared/smoke-test.py'), URL], check=True)
            print(f'PASS: {gateway} stopped; 6 echo calls and full smoke test passed', flush=True)
        finally:
            # Restore both replicas before testing the opposite failure direction.
            compose('start', gateway)
            wait_for_both()

    assert len(set(survivors)) == 2, 'Expected different surviving gateways'
    print('PASS: load distribution, failover in both directions, and recovery')
