"""Check tool authorization, CORS, and HTTP request rate limits."""

import json
import sys
import time
import urllib.error
import urllib.request

url = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:3000/mcp'
origin = sys.argv[2] if len(sys.argv) > 2 else 'http://localhost:4000'
headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}


def rpc(method, params, identifier):
    body = {'jsonrpc': '2.0', 'method': method, 'params': params}
    if identifier is not None:
        body['id'] = identifier

    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)

    try:
        response = urllib.request.urlopen(request, timeout=15)
    except urllib.error.HTTPError as exc:
        with exc:
            body = exc.read().decode()

            try:
                return exc.code, json.loads(body)
            except ValueError:
                return exc.code, {"httpError": body}

    with response:
        if response.headers.get('Mcp-Session-Id'):
            headers['Mcp-Session-Id'] = response.headers['Mcp-Session-Id']

        if identifier is None:
            return response.status, None

        if 'text/event-stream' in response.headers.get('Content-Type', ''):
            for line in response:
                if line.startswith(b'data:'):
                    payload = json.loads(line[5:])
                    if payload.get('id') == identifier:
                        return response.status, payload

            raise RuntimeError('Missing SSE result')

        return response.status, json.load(response)


# Refill buckets so this test can be repeated after a prior burst.
time.sleep(11)
status, payload = rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                   'clientInfo': {'name': 'policy-test', 'version': '1'}}, 1)
assert status == 200 and 'result' in payload, (status, payload)

headers['MCP-Protocol-Version'] = payload['result']['protocolVersion']
status, _ = rpc('notifications/initialized', {}, None)
assert status == 202, status

status, payload = rpc('tools/list', {}, 2)
assert status == 200, status

names = {tool['name'] for tool in payload['result']['tools']}
assert names == {'echo'}, names

status, payload = rpc('tools/call', {'name': 'echo', 'arguments': {'message': 'policy-ok'}}, 3)
assert status == 200 and payload['result']['content'][0]['text'] == 'policy-ok', (status, payload)

status, payload = rpc('tools/call', {'name': 'add', 'arguments': {'a': 1, 'b': 2}}, 4)
assert status in (200, 400) and payload.get('error', {}).get('code') == -32602 and payload['error']['message'] == 'Unknown tool: add', (status, payload)
print('PASS: echo visible/allowed; add hidden/denied', flush=True)

request = urllib.request.Request(url, method='OPTIONS', headers={
    'Origin': origin, 'Access-Control-Request-Method': 'POST',
    'Access-Control-Request-Headers': 'content-type,mcp-protocol-version',
})
with urllib.request.urlopen(request, timeout=15) as response:
    assert response.headers.get('Access-Control-Allow-Origin') == origin, dict(response.headers)

print('PASS: configured browser origin allowed by CORS', flush=True)

limited = 0
accepted = 0
for identifier in range(100, 200):
    status, payload = rpc('tools/call', {'name': 'echo', 'arguments': {'message': 'burst'}}, identifier)
    assert status in (200, 429), (status, payload)

    if status == 429:
        limited += 1
    elif payload.get('result', {}).get('isError'):
        texts = [item.get('text', '') for item in payload['result']['content']]
        assert any('rate limit exceeded' in text for text in texts), payload

        limited += 1
    else:
        assert payload['result']['content'][0]['text'] == 'burst', payload

        accepted += 1

assert limited > 0 and accepted > 0, (limited, accepted)
print(f'PASS: rate limited {limited}/100 calls; accepted {accepted}', flush=True)

time.sleep(11)
status, payload = rpc('tools/call', {'name': 'echo', 'arguments': {'message': 'refilled'}}, 201)
assert status == 200 and not payload['result'].get('isError') and payload['result']['content'][0]['text'] == 'refilled', (status, payload)
print('PASS: request accepted after token refill', flush=True)
