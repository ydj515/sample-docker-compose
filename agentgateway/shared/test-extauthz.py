"""Verify authenticated external authorization and backend non-delivery."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

p = argparse.ArgumentParser()
p.add_argument('http_base')
p.add_argument('mcp_url')
p.add_argument('keys', type=Path)
p.add_argument('--lifecycle', type=Path)
a = p.parse_args()
keys = json.loads(a.keys.read_text())


def request(url, role='baseline', data=None, extra=None):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
               'MCP-Protocol-Version': '2025-03-26'}
    if role: headers['Authorization'] = 'Bearer ' + keys[role]

    headers.update(extra or {})

    try:
        response = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc

    with response:
        raw = response.read().decode()
        if 'text/event-stream' in response.headers.get('Content-Type', ''):
            raw = next(line[5:] for line in raw.splitlines() if line.startswith('data:'))

        try: body = json.loads(raw) if raw else None
        except ValueError: body = raw

        return response.status, body


def probe(label, expected, role='baseline', data=None, path='/processing/authz', extra=None):
    identifier = uuid.uuid4().hex
    start = time.monotonic()
    code, body = request(a.http_base + path + '?id=' + identifier, role, data, extra)
    elapsed = time.monotonic() - start
    count = request(a.http_base + '/authz-stats?id=' + identifier, None)[1]['count']
    assert code == expected, (label, code, body)
    assert count == (1 if expected == 200 else 0), (label, count)

    if code == 200:
        assert body['headers']['x-policy-winner'] == 'external-authz', body
        assert body['body'] == (data.decode() if data else ''), body

    print(f'PASS: {label}: HTTP {code}, backend receipts={count}, elapsed={elapsed:.3f}s')

    return identifier


probe('viewer GET allowed', 200)
probe('viewer POST denied', 403, data=b'{}')
probe('calculator POST allowed', 200, 'calculator', b'{"value":1}')
probe('missing API key', 401, role=None)
probe('forged role cannot elevate viewer', 403, data=b'{}', extra={'x-authz-role':'calculator','x-demo-role':'calculator'})
probe('authz response overwrites forged decision header', 200, extra={'x-policy-winner':'forged'})
probe('oversized body rejected', 413, 'calculator', b'x' * 1025)
probe('authz service error', 503, path='/processing/error')
slow_id = probe('authz timeout', 403, path='/processing/slow')
time.sleep(0.6)
assert request(a.http_base + '/authz-stats?id=' + slow_id, None)[1]['count'] == 0


def rpc(role, method, params, identifier=1):
    payload = {'jsonrpc':'2.0', 'method':method, 'params':params}
    if identifier is not None: payload['id'] = identifier
    return request(a.mcp_url, role, json.dumps(payload).encode())


for role in ['baseline','calculator']:
    code, body = rpc(role, 'initialize', {'protocolVersion':'2025-03-26', 'capabilities':{},
        'clientInfo':{'name':'extauthz-test','version':'1'}})
    assert code == 200 and 'result' in body, (code, body)
    assert rpc(role, 'notifications/initialized', {}, None)[0] == 202

    code, body = rpc(role, 'tools/list', {})
    assert code == 200 and {t['name'] for t in body['result']['tools']} == {'echo','add'}, (code,body)

    code, body = rpc(role, 'tools/call', {'name':'echo','arguments':{'message':'external authz'}})
    assert code == 200 and body['result']['content'][0]['text'] == 'external authz', (code,body)

    code, body = rpc(role, 'tools/call', {'name':'add','arguments':{'a':2,'b':3}})
    if role == 'baseline':
        assert code == 403, (code, body)
    else:
        assert code == 200 and body['result']['content'][0]['text'] == '5', (code,body)

    print(f'PASS: MCP initialization/list/echo/add authorization for {role}')

if a.lifecycle:
    env = {**os.environ,'AGENTGATEWAY_CONFIG':'./data/config-extauthz.yaml',
           'LOCAL_UID':str(os.getuid()),'LOCAL_GID':str(os.getgid())}
    command = ['docker','compose','-f','docker-compose.yml','-f','compose-extauthz.yml']
    def service(action): subprocess.run(command+[action,'authz'],cwd=a.lifecycle,env=env,check=True)

    try:
        service('stop')
        probe('stopped authz fails closed', 403)
    finally:
        service('start')

    for _ in range(30):
        code, _ = request(a.http_base+'/processing/authz?id='+uuid.uuid4().hex)
        if code == 200: break

        time.sleep(0.2)

    probe('authz recovery',200)
