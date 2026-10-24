"""Exercise discovery, mock messages, errors, API keys and per-replica limits."""

import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('root', type=Path)
parser.add_argument('urls', nargs='+')
args = parser.parse_args()
keys = json.loads((args.root / 'data/auth-keys.json').read_text())
payload = {'jsonrpc': '2.0', 'id': 'demo', 'method': 'message/send', 'params': {'message': {
    'kind': 'message', 'role': 'user', 'messageId': 'test-1', 'parts': [{'kind': 'text', 'text': 'hello A2A'}]}}}


def call(url, data=None, key=keys['baseline']):
    headers = {'Content-Type': 'application/json'}
    if key is not None:
        headers['Authorization'] = 'Bearer ' + key

    req = urllib.request.Request(url, data=data, headers=headers)

    try:
        response = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc

    with response:
        body = response.read()

        try:
            body = json.loads(body)
        except ValueError:
            body = None

        return response.status, body


for base in args.urls:
    base = base.rstrip('/')
    # Fresh buckets also make reruns deterministic; limits are not cluster-wide.
    time.sleep(11)
    for key in [None, 'invalid-demo-key']:
        assert call(base + '/a2a', json.dumps(payload).encode(), key)[0] == 401

    for route in ['a2a', 'raw']:
        status, card = call(base + '/' + route + '/.well-known/agent-card.json')
        assert status == 200, status

        expected = base + '/a2a' if route == 'a2a' else 'http://a2a-demo:3010/a2a'
        assert card['url'].rstrip('/') == expected, card['url']
        assert card['capabilities']['streaming'] is False

    status, result = call(base + '/a2a', json.dumps(payload).encode())
    assert status == 200 and result['result']['parts'][0]['text'] == 'Mock LLM: hello A2A'
    assert result['result']['metadata']['networkCalls'] == 0

    for data, code in [(b'{', -32700), (json.dumps({**payload, 'method': 'message/stream'}).encode(), -32601),
                       (json.dumps({**payload, 'params': {}}).encode(), -32602)]:
        status, body = call(base + '/a2a', data)
        assert status == 200 and body['error']['code'] == code

    statuses = [call(base + '/a2a', json.dumps(payload).encode())[0] for _ in range(45)]
    assert 200 in statuses and 429 in statuses and set(statuses) <= {200, 429}, statuses
    assert call(base + '/a2a', json.dumps(payload).encode(), keys['calculator'])[0] == 200

    time.sleep(11)
    assert call(base + '/a2a', json.dumps(payload).encode())[0] == 200
    print(f'PASS {base}: card rewrite vs raw, mock RPC, protocol errors, auth, limit/isolation/refill')
