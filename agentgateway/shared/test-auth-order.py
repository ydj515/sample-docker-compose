"""Compare authentication, authorization and rate-limit outcomes without logging keys."""

import json
from pathlib import Path
import secrets
import sys
import urllib.error
import urllib.request

URL = sys.argv[1]
keys = json.loads(Path(sys.argv[2]).read_text())


class Client:
    def __init__(self, name):
        self.key = keys[name]
        self.headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        self.seq = 0
        status, payload = self.rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
            'clientInfo': {'name': 'auth-order-test', 'version': '1'}})
        assert status == 200 and 'result' in payload, 'Authenticated initialize failed'

        self.headers['MCP-Protocol-Version'] = payload['result']['protocolVersion']
        status, _ = self.rpc('notifications/initialized', {}, notification=True)
        assert status == 202, 'Initialization notification failed'

    def rpc(self, method, params, notification=False, auth='valid', spoof=False):
        self.seq += 1
        body = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if not notification:
            body['id'] = self.seq

        headers = self.headers.copy()
        if auth != 'missing':
            headers['Authorization'] = 'Bearer ' + (self.key if auth == 'valid' else secrets.token_urlsafe(32))

        if spoof:
            headers['x-demo-role'] = 'calculator'

        request = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=headers)

        try:
            response = urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as exc:
            response = exc

        with response:
            status = response.status
            if response.headers.get('Mcp-Session-Id'):
                self.headers['Mcp-Session-Id'] = response.headers['Mcp-Session-Id']

            if status in (401, 403):
                return status, {}

            if notification:
                return status, {}

            if 'text/event-stream' in response.headers.get('Content-Type', ''):
                payload = next(json.loads(line[5:]) for line in response if line.startswith(b'data:'))
            else:
                payload = json.load(response)

            return status, payload

    def call(self, name='echo', **options):
        args = {'message': 'auth-ok'} if name == 'echo' else {'a': 2, 'b': 3}
        return self.rpc('tools/call', {'name': name, 'arguments': args}, **options)


def kind(result):
    status, payload = result
    if status in (401, 403):
        return f'http-{status}'

    if payload.get('error', {}).get('message') == 'Unknown tool: add':
        return 'tool-denied'

    result = payload.get('result', {})
    if result.get('isError'):
        text = ' '.join(x.get('text', '') for x in result.get('content', []))
        if 'rate limit exceeded' in text:
            return 'rate-limited'

        raise AssertionError('Unexpected MCP tool error')

    if result.get('content', [{}])[0].get('text') in ('auth-ok', '5'):
        return 'allowed'

    raise AssertionError(f'Unexpected response category (HTTP {status})')


def exhaust(client):
    accepted = 0
    for _ in range(30):
        category = kind(client.call())
        if category == 'rate-limited':
            return accepted

        assert category == 'allowed', category

        accepted += 1

    raise AssertionError('Rate limit did not trigger; restart gateway before this test')


# Separate keys isolate each experiment; initialization consumes quota in every group.
baseline = Client('baseline')
base_count = exhaust(baseline)
assert base_count > 0, 'Buckets already used; restart gateway before testing'

probe = Client('invalid')
for _ in range(5):
    assert kind(probe.call(auth='missing')) == 'http-401'
    assert kind(probe.call(auth='invalid')) == 'http-401'

# Compare against the baseline to detect whether rejected authentication spent quota.
invalid_count = exhaust(probe)
assert invalid_count == base_count, 'Invalid authentication affected another authenticated bucket'
assert kind(probe.call(auth='missing')) == 'http-401'
assert kind(probe.call(auth='invalid')) == 'http-401'
print(f'PASS: missing/invalid keys -> 401 before and after exhaustion; accepted calls {base_count}/{invalid_count}', flush=True)

viewer = Client('denied')
for _ in range(5):
    assert kind(viewer.call('add', spoof=True)) == 'tool-denied'

# Authenticated permission failures may consume quota even though the tool never runs.
denied_count = exhaust(viewer)
collision = kind(viewer.call('add'))
print(f'OBSERVED: baseline={base_count}, after 5 denied calls={denied_count}, denied+exhausted={collision}', flush=True)

assert collision == 'rate-limited', 'Unexpected permission/rate-limit collision result'
assert denied_count == base_count - 5, 'Denied calls did not consume the expected request budget'

calculator = Client('calculator')
assert kind(calculator.call('add')) == 'allowed'
assert kind(calculator.call()) == 'allowed'
print('PASS: verified key metadata grants calculator access; spoofed role header does not', flush=True)

print('PASS: 5 denied calls consume 5 units; rate limit wins the observed authorization collision', flush=True)
