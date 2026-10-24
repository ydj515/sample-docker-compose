"""Exercise combined limits and OR authorization rules through the gateway."""

import json
import sys
import time
import urllib.error
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:3000/mcp'


def limit_text(payload):
    result = payload.get('result', {})
    texts = ' '.join(item.get('text', '') for item in result.get('content', []))
    return texts if result.get('isError') and 'rate limit exceeded' in texts else ''


class Client:
    def __init__(self, name, role):
        self.headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                        'x-demo-client': name, 'x-demo-role': role}
        self.seq = 0
        payload = self.rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
            'clientInfo': {'name': 'multi-policy-test', 'version': '1'}})
        self.headers['MCP-Protocol-Version'] = payload['result']['protocolVersion']
        self.rpc('notifications/initialized', {}, notification=True)

    def rpc(self, method, params, notification=False):
        self.seq += 1
        body = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if not notification:
            body['id'] = self.seq

        request = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=self.headers)

        try:
            response = urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as exc:
            response = exc

        with response:
            assert response.status in (200, 202, 400), response.status

            if response.headers.get('Mcp-Session-Id'):
                self.headers['Mcp-Session-Id'] = response.headers['Mcp-Session-Id']

            if notification:
                assert response.status == 202
                return {}

            if 'text/event-stream' in response.headers.get('Content-Type', ''):
                for line in response:
                    if line.startswith(b'data:'):
                        payload = json.loads(line[5:])
                        if payload.get('id') == self.seq:
                            return payload

                raise RuntimeError('Missing SSE response')

            return json.load(response)

    def echo(self):
        return self.rpc('tools/call', {'name': 'echo', 'arguments': {'message': 'multi-ok'}})


def success(payload, expected):
    assert not payload.get('error') and not payload['result'].get('isError'), payload
    assert payload['result']['content'][0]['text'] == expected, payload


time.sleep(11)
a = Client('client-a', 'viewer')
assert {t['name'] for t in a.rpc('tools/list', {})['result']['tools']} == {'echo'}

blocked = a.rpc('tools/call', {'name': 'add', 'arguments': {'a': 2, 'b': 3}})
assert blocked['error']['message'] == 'Unknown tool: add', blocked

success(a.echo(), 'multi-ok')
# Both replicas may have a bucket for the same client when testing HA.
for _ in range(80):
    payload = a.echo()
    text = limit_text(payload)
    if text:
        assert 'limit 20,' in text, text

        break

    success(payload, 'multi-ok')
else:
    raise AssertionError('Per-client limit did not trigger')

print('PASS: viewer echo allowed, add denied, client-a bucket exhausted', flush=True)

b = Client('client-b', 'calculator')
assert {t['name'] for t in b.rpc('tools/list', {})['result']['tools']} == {'echo', 'add'}

success(b.echo(), 'multi-ok')
success(b.rpc('tools/call', {'name': 'add', 'arguments': {'a': 2, 'b': 3}}), '5')
print('PASS: independent client-b bucket; calculator can use echo AND add (OR rules)', flush=True)

# Vary the key on the same connection/session to consume the shared bucket.
# This is an intentionally spoofable demo header, not authenticated identity.
for i in range(300):
    b.headers['x-demo-client'] = f'fresh-{i}'
    payload = b.echo()
    text = limit_text(payload)
    if text:
        assert 'limit 60,' in text, text

        break

    success(payload, 'multi-ok')
else:
    raise AssertionError('Aggregate limit did not trigger')

print('PASS: changing client keys cannot bypass the aggregate limit', flush=True)

time.sleep(11)
b.headers['x-demo-client'] = 'client-b'
success(b.echo(), 'multi-ok')
print('PASS: combined buckets recover after refill', flush=True)
