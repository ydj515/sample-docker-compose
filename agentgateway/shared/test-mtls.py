"""Validate mTLS ingress, backend enforcement, and optional certificate renewal."""

import argparse
import hashlib
import http.client
import json
from pathlib import Path
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

p = argparse.ArgumentParser()
p.add_argument('url')
p.add_argument('cert_dir', type=Path)
p.add_argument('--previous', type=Path)
a = p.parse_args()


def context(role='client', directory=a.cert_dir):
    ctx = ssl.create_default_context(cafile=str(directory / 'ca.crt'))
    if role:
        ctx.load_cert_chain(directory / role / 'tls.crt', directory / role / 'tls.key')

    return ctx


def request(path, ctx, payload=None):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
               'MCP-Protocol-Version': '2025-03-26'}
    req = urllib.request.Request(a.url + path, headers=headers,
                                 data=json.dumps(payload).encode() if payload else None)

    try:
        res = urllib.request.urlopen(req, context=ctx, timeout=10)
    except urllib.error.HTTPError as exc:
        res = exc

    with res:
        body = res.read().decode()
        if 'text/event-stream' in res.headers.get('Content-Type', ''):
            body = next(line[5:] for line in body.splitlines() if line.startswith('data:'))

        try: body = json.loads(body) if body else None
        except ValueError: pass

        return res.status, body


ctx = context()
assert request('/mtls-check/good', ctx) == (200, {'status': 'ok'})

for path in ['/mtls-check/no-client', '/mtls-check/bad-client']:
    code, body = request(path, ctx)
    assert code == 503, (code, body)
    print(f'PASS: backend rejects {path}: HTTP 503')

for role in [None, 'rogue-client', 'gateway-client']:
    try:
        code, body = request('/mtls-check/good', context(role))
        # Nginx rejects client certificates with an HTTP error after TLS handshake.
        assert code in (400, 403), (role, code, body)
    except urllib.error.URLError as exc:
        assert isinstance(exc.reason, (ssl.SSLError, ConnectionResetError)), exc
    except (ssl.SSLError, ConnectionResetError, http.client.RemoteDisconnected):
        pass

    print(f'PASS: ingress rejects client role {role}')


def rpc(method, params, identifier=1):
    payload = {'jsonrpc': '2.0', 'method': method, 'params': params}
    if identifier is not None: payload['id'] = identifier

    code, body = request('/mcp/mtls', ctx, payload)
    assert code in (200, 202), (code, body)

    return body


assert 'result' in rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
    'clientInfo': {'name': 'mtls-test', 'version': '1'}})

rpc('notifications/initialized', {}, None)
names = [t['name'] for t in rpc('tools/list', {})['result']['tools']]
for suffix, arguments, expected in [('echo', {'message': 'mTLS 확인'}, 'mTLS 확인'), ('add', {'a': 2, 'b': 3}, '5')]:
    name = next(n for n in names if n == suffix or n.endswith('_' + suffix))
    result = rpc('tools/call', {'name': name, 'arguments': arguments})['result']
    assert not result.get('isError') and result['content'][0]['text'] == expected, result

print('PASS: authenticated initialize, list, echo and add over both mTLS hops')

parsed = urllib.parse.urlparse(a.url)
with socket.create_connection((parsed.hostname, parsed.port), timeout=5) as sock:
    with ctx.wrap_socket(sock, server_hostname=parsed.hostname) as tls:
        presented = hashlib.sha256(tls.getpeercert(binary_form=True)).digest()

expected = ssl.PEM_cert_to_DER_cert((a.cert_dir / 'gateway/tls.crt').read_text())
assert presented == hashlib.sha256(expected).digest()
print('PASS: endpoint presents selected generation gateway certificate')

if a.previous:
    for name in ['ca', 'frontend-ca', 'backend-ca']:
        assert (a.cert_dir / f'{name}.crt').read_bytes() == (a.previous / f'{name}.crt').read_bytes()

    for role in ['gateway', 'backend', 'client', 'proxy-client', 'gateway-client', 'health-client']:
        new = ssl._ssl._test_decode_cert(str(a.cert_dir / role / 'tls.crt'))
        old = ssl._ssl._test_decode_cert(str(a.previous / role / 'tls.crt'))
        assert new['serialNumber'] != old['serialNumber']
        assert ssl.cert_time_to_seconds(new['notAfter']) > ssl.cert_time_to_seconds(old['notAfter'])

    assert request('/mtls-check/good', context(directory=a.previous)) == (200, {'status': 'ok'})
    print('PASS: new serials, extended expiry, stable CAs; previous client remains valid (not revoked)')
