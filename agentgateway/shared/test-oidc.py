"""Local OAuth/OIDC protocol tests. Credentials, authorization codes and tokens are never logged."""

import argparse
import base64
import hashlib
import http.client
import ssl
from html.parser import HTMLParser
import http.cookiejar
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('root', type=Path)
parser.add_argument('urls', nargs='*', help='MCP endpoints; defaults to the public endpoint')
parser.add_argument('--wait-only', action='store_true')
parser.add_argument('--mtls-cert-dir', type=Path, help='Use the separate OAuth+mTLS realm and HTTPS endpoints')
parser.add_argument('--refresh', action='store_true', help='Test refresh grant, reuse and logout rejection')
parser.add_argument('--expiry', action='store_true', help='Wait for token expiry plus 61 seconds of clock tolerance')
args = parser.parse_args()
root = args.root.resolve()
assert root.name in ('single', 'ha'), 'Specify single or ha'

issuer = f'http://localhost:{18080 if root.name == "single" else 28080}/realms/agentgateway'
resource = f'http://localhost:{3000 if root.name == "single" else 13000}/mcp'
variant = 'oidc'
if args.mtls_cert_dir:
    variant = 'oidc-mtls'
    issuer += '-mtls'
    resource = f'https://localhost:{3443 if root.name == "single" else 13443}/mcp/mtls'


def tls_context(role='client'):
    ctx = ssl.create_default_context(cafile=str(args.mtls_cert_dir / 'ca.crt'))
    if role:
        ctx.load_cert_chain(args.mtls_cert_dir / role / 'tls.crt', args.mtls_cert_dir / role / 'tls.key')

    return ctx


mtls_context = tls_context() if args.mtls_cert_dir else None
urls = args.urls or [resource]
for url in urls:
    parsed = urllib.parse.urlparse(url)
    assert parsed.scheme == ('https' if args.mtls_cert_dir else 'http') and parsed.hostname in ('localhost', '127.0.0.1'), 'Local endpoints with the selected transport only'
    assert parsed.path == ('/mcp/mtls' if args.mtls_cert_dir else '/mcp') and not parsed.query and not parsed.fragment, 'Expected /mcp endpoint'


def request(url, data=None, headers=None, opener=None, context=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})

    try:
        response = opener.open(req, timeout=15) if opener else urllib.request.urlopen(
            req, timeout=15, context=(context or mtls_context) if url.startswith('https:') else None)
    except urllib.error.HTTPError as exc:
        response = exc

    with response:
        return response.status, response.headers, response.read()


def form(url, values, opener=None):
    return request(url, urllib.parse.urlencode(values).encode(),
                   {'Content-Type': 'application/x-www-form-urlencoded'}, opener)


def decode_part(token):
    part = token.split('.')[1]
    return json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))


for attempt in range(90):
    try:
        status, _, body = request(issuer + '/.well-known/openid-configuration')
        if status == 200:
            discovery = json.loads(body)
            assert discovery['issuer'] == issuer, 'Discovery issuer mismatch'

            break
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        pass

    if attempt % 15 == 0:
        print('Waiting for local Keycloak discovery', flush=True)

    time.sleep(2)
else:
    raise SystemExit('Keycloak discovery did not become ready')

print('PASS: Keycloak discovery ready; public issuer matches', flush=True)

if args.wait_only:
    raise SystemExit(0)

credentials = json.loads((root / 'data' / variant / 'credentials.json').read_text())
endpoint = discovery['token_endpoint']
tokens = {}
for name in ('viewer', 'calculator', 'wrong-audience'):
    status, _, body = form(endpoint, {'grant_type': 'client_credentials', 'client_id': name,
                                    'client_secret': credentials[name]})
    assert status == 200, f'{name} token issuance failed (HTTP {status})'

    issued = json.loads(body)
    assert 'refresh_token' not in issued, 'Unexpected service account refresh token'

    tokens[name] = issued['access_token']

status, _, _ = form(endpoint, {'grant_type': 'client_credentials', 'client_id': 'viewer',
                              'client_secret': secrets.token_urlsafe(32)})
assert status == 401, 'Invalid client credentials accepted'
print('PASS: OAuth Client Credentials issued; invalid client secret rejected', flush=True)


class NoCallbackRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl.startswith('http://127.0.0.1:18765/callback'):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.hidden = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form' and attrs.get('id') == 'kc-form-login':
            self.action = attrs.get('action')

        if tag == 'input' and attrs.get('type') == 'hidden' and attrs.get('name'):
            self.hidden[attrs['name']] = attrs.get('value', '')


def authorize():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    query = {'response_type': 'code', 'client_id': 'browser', 'redirect_uri': 'http://127.0.0.1:18765/callback',
             'scope': 'openid', 'state': state, 'nonce': nonce, 'code_challenge': challenge,
             'code_challenge_method': 'S256'}
    # Match localhost browser cookie behavior; all login destinations are constrained to this local issuer.
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar(
        policy=http.cookiejar.DefaultCookiePolicy(secure_protocols=('https', 'wss', 'http')))),
                                        NoCallbackRedirect())
    status, _, body = request(discovery['authorization_endpoint'] + '?' + urllib.parse.urlencode(query), opener=opener)
    assert status == 200, 'Authorization page unavailable'

    login = LoginForm()
    login.feed(body.decode())
    assert login.action, 'Expected Keycloak login form'
    # Never send credentials to a form outside the configured local issuer.
    assert login.action.startswith(issuer + '/'), 'Unexpected login form destination'

    values = {**login.hidden, 'username': 'demo-viewer', 'password': credentials['login-password']}
    status, headers, _ = form(login.action, values, opener)

    assert status == 302, f'Login failed (HTTP {status})'

    callback = urllib.parse.urlparse(headers['Location'])
    assert callback.scheme == 'http' and callback.netloc == '127.0.0.1:18765' and callback.path == '/callback'

    params = urllib.parse.parse_qs(callback.query)
    assert params.get('state') == [state], 'OAuth state mismatch'
    assert params.get('iss') == [issuer], 'Authorization response issuer mismatch'
    assert 'code' in params and 'error' not in params, 'Authorization code missing'

    return {'grant_type': 'authorization_code', 'client_id': 'browser', 'code': params['code'][0],
            'redirect_uri': 'http://127.0.0.1:18765/callback', 'code_verifier': verifier}, nonce


exchange, nonce = authorize()
status, _, body = form(endpoint, exchange)
assert status == 200, 'PKCE token exchange failed'

login_tokens = json.loads(body)
status, _, body = request(discovery['jwks_uri'])
assert status == 200

verification = {'token': login_tokens['id_token'], 'jwks': json.loads(body), 'issuer': issuer, 'nonce': nonce}
source = (Path(__file__).parent / 'verify-oidc.mjs').read_text()
command = ['docker', 'compose', '-f', str(root / 'docker-compose.yml'), 'exec', '-T', 'mcp-demo',
           'node', '--input-type=module', '-e', source]
result = subprocess.run(command, input=json.dumps(verification), text=True, capture_output=True)
assert result.returncode == 0, 'ID token signature/claim verification failed'
print(result.stdout.strip(), flush=True)

# Validate that the verifier also rejects a mismatched nonce and a forged signature.
for key in ('nonce', 'token'):
    invalid = verification.copy()
    invalid[key] = secrets.token_urlsafe(24) if key == 'nonce' else verification['token'][:-8] + 'AAAAAAAA'
    check = subprocess.run(command, input=json.dumps(invalid), text=True, capture_output=True)
    assert check.returncode != 0, 'ID token negative validation failed'

status, _, _ = form(endpoint, exchange)
assert status == 400, 'Authorization code reuse accepted'

exchange, _ = authorize()
exchange['code_verifier'] = secrets.token_urlsafe(48)
status, _, _ = form(endpoint, exchange)
assert status == 400, 'Invalid PKCE verifier accepted'
print('PASS: OIDC login + S256 PKCE; code reuse, bad verifier, forged ID token and wrong nonce rejected', flush=True)


if args.refresh:
    # Code replay above can invalidate its login session. Start a fresh session for refresh tests.
    refresh_exchange, _ = authorize()
    status, _, body = form(endpoint, refresh_exchange)
    assert status == 200, 'Fresh login for refresh test failed'

    login_tokens = json.loads(body)
    refresh_values = {'grant_type': 'refresh_token', 'client_id': 'browser',
                      'refresh_token': login_tokens['refresh_token']}
    for changes in ({'refresh_token': secrets.token_urlsafe(48)}, {'client_id': 'viewer', 'client_secret': credentials['viewer']}):
        status, _, body = form(endpoint, {**refresh_values, **changes})
        assert status == 400 and json.loads(body).get('error') == 'invalid_grant', 'Invalid refresh grant accepted'

    status, _, body = form(endpoint, refresh_values)
    assert status == 200, 'Refresh token grant failed'

    refreshed = json.loads(body)
    assert decode_part(refreshed['access_token'])['sub'] == decode_part(login_tokens['access_token'])['sub']
    assert decode_part(refreshed['access_token'])['demo_role'] == 'viewer'

    status, _, _ = form(endpoint, refresh_values)
    assert status == 200, 'Default sample refresh reuse behavior changed'

    login_tokens = refreshed
    status, _, body = form(endpoint, {'grant_type': 'client_credentials', 'client_id': 'calculator',
                                     'client_secret': credentials['calculator']})
    assert status == 200 and 'refresh_token' not in json.loads(body)

    tokens['calculator'] = json.loads(body)['access_token']
    print('PASS: refresh grant and client-credentials reacquisition; bad/wrong-client refresh rejected; default refresh reuse accepted', flush=True)

sessions = {}
sequence = 0

def rpc(url, token, method, params):
    global sequence
    sequence += 1
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
               'MCP-Protocol-Version': '2025-03-26', 'x-demo-role': 'calculator'}
    if method != 'initialize' and (url, token) in sessions:
        headers['Mcp-Session-Id'] = sessions[(url, token)]

    if token:
        headers['Authorization'] = 'Bearer ' + token

    message = {'jsonrpc': '2.0', 'method': method, 'params': params}
    if not method.startswith('notifications/'):
        message['id'] = sequence

    status, response_headers, body = request(url, json.dumps(message).encode(), headers)
    if response_headers.get('Mcp-Session-Id'):
        sessions[(url, token)] = response_headers['Mcp-Session-Id']

    payload = {}
    if status in (200, 400):
        if 'text/event-stream' in response_headers.get('Content-Type', ''):
            payload = next(json.loads(line[5:]) for line in body.splitlines() if line.startswith(b'data:'))
        else:
            payload = json.loads(body)

    return status, response_headers, payload


for url in urls:
    init = {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'oidc-test', 'version': '1'}}
    status, headers, _ = rpc(url, None, 'initialize', init)
    assert status == 401 and 'resource_metadata=' in headers.get('WWW-Authenticate', ''), 'Missing token challenge failed'

    for token in (tokens['wrong-audience'], tokens['viewer'][:-8] + 'AAAAAAAA'):
        assert rpc(url, token, 'initialize', init)[0] == 401, 'Invalid token was accepted'

    for token, can_add in ((tokens['viewer'], False), (tokens['calculator'], True), (login_tokens['access_token'], False)):
        status, _, payload = rpc(url, token, 'initialize', init)
        assert status == 200 and 'result' in payload, 'Authenticated initialization failed'
        assert rpc(url, token, 'notifications/initialized', {})[0] == 202, 'Initialization notification failed'

        status, _, payload = rpc(url, token, 'tools/list', {})
        names = [tool['name'] for tool in payload.get('result', {}).get('tools', [])]
        assert status == 200 and 'echo' in names and ('add' in names) == can_add, f'Tool visibility mismatch: HTTP {status}, names={names}, can_add={can_add}'

        status, _, payload = rpc(url, token, 'tools/call', {'name': 'echo', 'arguments': {'message': 'oidc-ok'}})
        assert status == 200 and payload.get('result', {}).get('content', [{}])[0].get('text') == 'oidc-ok', 'Echo failed'

        status, _, payload = rpc(url, token, 'tools/call', {'name': 'add', 'arguments': {'a': 2, 'b': 3}})
        if can_add:
            assert status == 200 and payload.get('result', {}).get('content', [{}])[0].get('text') == '5', 'Add failed'
        else:
            assert status == 400 and payload.get('error', {}).get('message') == 'Unknown tool: add', f'Viewer add was not denied: HTTP {status}, error={payload.get("error")}, isError={payload.get("result",{}).get("isError")}'

    parsed = urllib.parse.urlsplit(url)
    metadata_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, '/.well-known/oauth-protected-resource' + parsed.path, '', ''))
    status, _, body = request(metadata_url)
    assert status == 200, 'Protected resource metadata unavailable'

    metadata = json.loads(body)
    assert metadata['resource'] == resource, 'Resource identifier mismatch'
    assert issuer in metadata['authorization_servers'], 'Authorization server discovery mismatch'
    print(f'PASS: {url}: challenge, audience/signature rejection, OAuth/OIDC roles, tool filtering, spoof resistance, metadata', flush=True)

if args.mtls_cert_dir:
    for url in urls:
        for role in (None, 'rogue-client', 'gateway-client'):
            for token in (None, tokens['calculator'], tokens['wrong-audience']):
                headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
                if token:
                    headers['Authorization'] = 'Bearer ' + token

                message = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': init}).encode()

                try:
                    status, _, body = request(url, message, headers, context=tls_context(role))
                    # Nginx returns HTTP 400 after TLS rather than a TLS alert.
                    assert status == 400 and b'nginx' in body.lower(), 'Invalid certificate reached MCP'
                except urllib.error.URLError as exc:
                    assert isinstance(exc.reason, (ssl.SSLError, ConnectionResetError)), 'Unexpected network failure'
                except (ssl.SSLError, ConnectionResetError, http.client.RemoteDisconnected):
                    pass

            print(f'PASS: {url}: client certificate {role} rejected with missing/valid/invalid tokens', flush=True)

        base = url.removesuffix('/mcp/mtls')
        assert request(base + '/mtls-check/good')[0] == 200, 'Valid backend mTLS failed'

        for path in ('no-client', 'bad-client'):
            assert request(base + '/mtls-check/' + path)[0] == 503, 'Backend accepted invalid client certificate'

        print(f'PASS: {url}: backend mTLS good=200, missing/untrusted certificate=503', flush=True)

if args.refresh:
    status, _, _ = form(issuer + '/protocol/openid-connect/logout',
                        {'client_id': 'browser', 'refresh_token': login_tokens['refresh_token']})
    assert status == 204, 'Session logout failed'

    status, _, body = form(endpoint, {'grant_type': 'refresh_token', 'client_id': 'browser',
                                     'refresh_token': login_tokens['refresh_token']})
    assert status == 400 and json.loads(body).get('error') == 'invalid_grant', 'Logged-out refresh accepted'

    # Logout invalidates refresh at Keycloak; locally verified JWTs are not immediately revoked.
    for url in urls:
        assert rpc(url, login_tokens['access_token'], 'initialize', init)[0] == 200, 'Unexpected immediate access-token revocation'

    print('PASS: logout rejects refresh; already-issued access token remains valid at Gateway (offline JWT validation)', flush=True)

if args.expiry:
    # Test after the clock-tolerance margin, not at the exact expiration boundary.
    deadline = decode_part(tokens['viewer'])['exp'] + 61
    while time.time() <= deadline:
        remaining = int(deadline - time.time()) + 1
        print(f'Waiting for token expiration and clock tolerance: {remaining}s', flush=True)

        time.sleep(min(30, remaining))

    for url in urls:
        assert rpc(url, tokens['viewer'], 'initialize', init)[0] == 401, 'Expired token accepted'

    print('PASS: expired access token rejected on every tested endpoint', flush=True)
