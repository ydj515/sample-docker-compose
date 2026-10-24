"""Prepare local Keycloak realm imports; never print or overwrite credentials."""

import argparse
import json
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('root', type=Path)
parser.add_argument('--mtls', action='store_true')
args = parser.parse_args()
root = args.root.resolve()
if root.name not in ('single', 'ha'):
    raise SystemExit('Specify the single or ha directory')

# Keep standalone and combined credentials separate when switching the same stack.
variant = 'oidc-mtls' if args.mtls else 'oidc'
realm_name = 'agentgateway-mtls' if args.mtls else 'agentgateway'
folder = root / 'data' / variant
folder.mkdir(parents=True, exist_ok=True, mode=0o700)
path = folder / 'credentials.json'
if path.exists():
    credentials = json.loads(path.read_text())
else:
    credentials = {name: secrets.token_urlsafe(32) for name in ('viewer', 'calculator', 'wrong-audience', 'login-password')}
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
        json.dump(credentials, out)


def audience(value):
    return {'name': 'resource-audience', 'protocol': 'openid-connect',
            'protocolMapper': 'oidc-audience-mapper', 'config': {
                'included.custom.audience': value, 'access.token.claim': 'true', 'id.token.claim': 'false'}}


def role(value):
    return {'name': 'demo-role', 'protocol': 'openid-connect',
            'protocolMapper': 'oidc-hardcoded-claim-mapper', 'config': {
                'claim.name': 'demo_role', 'claim.value': value, 'jsonType.label': 'String',
                'access.token.claim': 'true', 'id.token.claim': 'true'}}

resource = 'http://localhost:' + ('3000' if root.name == 'single' else '13000') + '/mcp'
if args.mtls:
    resource = 'https://localhost:' + ('3443' if root.name == 'single' else '13443') + '/mcp/mtls'

clients = []
for name in ('viewer', 'calculator', 'wrong-audience'):
    clients.append({'clientId': name, 'enabled': True, 'protocol': 'openid-connect',
                    'publicClient': False, 'secret': credentials[name], 'serviceAccountsEnabled': True,
                    'standardFlowEnabled': False, 'directAccessGrantsEnabled': False,
                    'protocolMappers': [audience('other-service' if name == 'wrong-audience' else resource),
                                        role('calculator' if name == 'calculator' else 'viewer')]})

# A public browser client has no secret; require S256 PKCE for code exchange.
clients.append({'clientId': 'browser', 'enabled': True, 'protocol': 'openid-connect', 'publicClient': True,
                'standardFlowEnabled': True, 'directAccessGrantsEnabled': False,
                'redirectUris': ['http://127.0.0.1:18765/callback'],
                'attributes': {'pkce.code.challenge.method': 'S256'},
                'protocolMappers': [audience(resource), role('viewer')]})
realm = {'realm': realm_name, 'enabled': True, 'accessTokenLifespan': 60,
         'registrationAllowed': False, 'clients': clients,
         'users': [{'username': 'demo-viewer', 'enabled': True, 'emailVerified': True,
                    'email': 'viewer@example.invalid', 'firstName': 'Demo', 'lastName': 'Viewer',
                    'credentials': [{'type': 'password', 'value': credentials['login-password'], 'temporary': False}]}]}
import_path = folder / 'agentgateway-realm.json'
# Keycloak skips import when its persistent realm already exists. Keep the import immutable too.
if not import_path.exists():
    with os.fdopen(os.open(import_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
        json.dump(realm, out, indent=2)

print('Prepared local OIDC credentials and realm import; existing files preserved')
