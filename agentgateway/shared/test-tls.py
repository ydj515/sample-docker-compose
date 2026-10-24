"""Compare HTTP/HTTPS ingress and MCP backends with verified TLS failures."""

import argparse
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('http_base')
parser.add_argument('https_base')
parser.add_argument('cert_dir')
args = parser.parse_args()
context = ssl.create_default_context(cafile=args.cert_dir + '/ca.crt')


def request(base, path, data=None, headers=None, ctx=context):
    req = urllib.request.Request(base + path, data=data, headers=headers or {})

    try:
        response = urllib.request.urlopen(req, context=ctx, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc

    with response:
        raw = response.read().decode()
        if 'text/event-stream' in response.headers.get('Content-Type', ''):
            raw = next(line[5:] for line in raw.splitlines() if line.startswith('data:'))

        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = raw

        return response.status, body


for base in [args.http_base, args.https_base]:
    for path in ['/mcp/plain', '/mcp/tls']:
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': '2025-03-26'}
        def rpc(method, params, identifier=1):
            body = {'jsonrpc': '2.0', 'method': method, 'params': params}
            if identifier is not None:
                body['id'] = identifier

            code, result = request(base, path, json.dumps(body).encode(), headers)
            assert code in (200, 202), (base, path, code, result)

            return result
        result = rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
            'clientInfo': {'name': 'tls-comparison', 'version': '1'}})
        assert 'result' in result, result

        rpc('notifications/initialized', {}, None)
        listed = rpc('tools/list', {})['result']['tools']
        names = [tool['name'] for tool in listed]
        echo = next(name for name in names if name == 'echo' or name.endswith('_echo'))
        add = next(name for name in names if name == 'add' or name.endswith('_add'))
        for name, arguments, expected in [(echo, {'message': 'TLS 비교'}, 'TLS 비교'), (add, {'a': 2, 'b': 3}, '5')]:
            result = rpc('tools/call', {'name': name, 'arguments': arguments})['result']
            assert not result.get('isError') and result['content'][0]['text'] == expected, result

        print(f'PASS: {base}{path}: initialize, list, echo, add')

    code, body = request(base, '/tls-check/good')
    assert code == 200 and body == {'status': 'ok'}, (code, body)

    for path in ['/tls-check/bad-ca', '/tls-check/bad-host']:
        code, body = request(base, path)
        assert code == 503 and 'invalid peer certificate' in str(body), (path, code, body)
        print(f'PASS: {base}{path}: backend TLS rejected with HTTP 503')

for ctx in [ssl.create_default_context(), ssl.create_default_context(cafile=args.cert_dir + '/wrong-ca.crt')]:
    try:
        request(args.https_base, '/tls-check/good', ctx=ctx)
    except urllib.error.URLError as exc:
        assert isinstance(exc.reason, ssl.SSLCertVerificationError), exc
    else:
        raise AssertionError('Untrusted frontend certificate accepted')

print('PASS: client rejects frontend certificate without the correct CA')

parsed = urllib.parse.urlparse(args.https_base)

try:
    with socket.create_connection((parsed.hostname, parsed.port), timeout=5) as sock:
        with context.wrap_socket(sock, server_hostname='wrong.invalid'):
            raise AssertionError('Wrong frontend hostname accepted')
except ssl.SSLCertVerificationError:
    print('PASS: client rejects frontend hostname mismatch')
