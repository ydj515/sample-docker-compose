"""Check policy stages and MCP target overrides without exposing credentials."""

import json
import sys
import urllib.request

base = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:4000').rstrip('/')
request = urllib.request.Request(base + '/inspect-headers', headers={'x-policy-winner': 'client'})
with urllib.request.urlopen(request, timeout=10) as response:
    observed = json.load(response)

assert observed == {'x-policy-gateway': 'gateway', 'x-policy-route': 'gateway>route',
                    'x-policy-backend': 'backend', 'x-policy-winner': 'backend'}, observed
print('PASS: gateway marker read by route; backend overwrites same header; all markers survive')


def rpc(method, params, identifier):
    request = urllib.request.Request(base + '/mcp-inheritance', data=json.dumps({
        'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params,
    }).encode(), headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                        'MCP-Protocol-Version': '2025-03-26'})
    with urllib.request.urlopen(request, timeout=15) as response:
        if 'text/event-stream' in response.headers.get('Content-Type', ''):
            payload = next(json.loads(line[5:]) for line in response if line.startswith(b'data:'))
        else:
            payload = json.load(response)

    assert payload.get('id') == identifier and 'error' not in payload, payload

    return payload['result']

names = {tool['name'] for tool in rpc('tools/list', {}, 1)['tools']}
assert names == {'inherited_inspect_headers', 'overridden_inspect_headers'}, names

for identifier, target in enumerate(('inherited', 'overridden'), 2):
    result = rpc('tools/call', {'name': f'{target}_inspect_headers', 'arguments': {}}, identifier)
    assert not result.get('isError'), result

    observed = json.loads(result['content'][0]['text'])
    print(target, observed)

    assert observed['x-policy-winner'] == ('common' if target == 'inherited' else 'target'), observed

    if target == 'inherited':
        assert observed['x-policy-common'] == 'common-only', observed
    else:
        assert 'x-policy-common' not in observed, observed

print('PASS: MCP target-specific header value overrides the common backend value')
