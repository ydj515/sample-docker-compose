"""Verify one MCP quota shared across direct replica endpoints."""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

URLS = sys.argv[1:] or ['http://127.0.0.1:16001/mcp', 'http://127.0.0.1:16002/mcp']
assert time.time() % 3600 < 3570, "Rerun after hourly boundary"

client = uuid.uuid4().hex
sessions = {}


def rpc(index, method, params):
    payload = {'jsonrpc': '2.0', 'id': index + 1, 'method': method, 'params': params}
    endpoint = URLS[index % len(URLS)]
    headers = {
        'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
        'x-demo-client': client, 'MCP-Protocol-Version': '2025-03-26'}
    # A shared quota does not make MCP sessions interchangeable between endpoints.
    if endpoint in sessions:
        headers['Mcp-Session-Id'] = sessions[endpoint]

    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers)

    try:
        response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc

    with response:
        if response.headers.get('Mcp-Session-Id'):
            sessions[endpoint] = response.headers['Mcp-Session-Id']

        data = response.read().decode()
        if 'text/event-stream' in response.headers.get('Content-Type', ''):
            data = next(line[5:] for line in data.splitlines() if line.startswith('data:'))

        return response.status, json.loads(data) if data else {}


for i in range(len(URLS)):
    code, body = rpc(i, 'initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
        'clientInfo': {'name': 'global-limit-test', 'version': '1'}})
    assert code == 200 and 'result' in body, (code, body)

for i in range(12):
    code, body = rpc(i, 'tools/call', {'name': 'echo', 'arguments': {'message': 'shared quota'}})
    assert code == 200, (code, body)

    # Tool-level rejection is carried inside HTTP 200, so inspect the MCP result.
    result = body['result']
    # Each initialize already consumed one of the ten shared requests.
    if i < 10 - len(URLS):
        assert not result.get('isError') and result['content'][0]['text'] == 'shared quota', body
    else:
        assert result.get('isError') and 'rate limit exceeded' in result['content'][0]['text'], body

print(f'PASS: {len(URLS)} initializations + {10 - len(URLS)} tool calls exhaust one shared MCP bucket')

print('PASS: subsequent tool calls return HTTP 200 with isError=true on every endpoint')
