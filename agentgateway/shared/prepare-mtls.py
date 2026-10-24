"""Issue a local mTLS generation; renew leaves with stable CAs into a new directory."""

import argparse
import os
from pathlib import Path
import secrets
import shutil
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
parser.add_argument('--renew-from', type=Path)
args = parser.parse_args()
out = args.output.resolve()
if out.exists():
    raise SystemExit('Output already exists; use a new generation directory')

os.umask(0o077)
out.mkdir(parents=True)


def openssl(*cmd):
    result = subprocess.run(['openssl', *map(str, cmd)], capture_output=True)
    if result.returncode:
        raise SystemExit('OpenSSL failed; files retained, no existing generation changed')


for name in ['ca', 'frontend-ca', 'backend-ca', 'wrong-ca']:
    if args.renew_from:
        # Renew 30-day leaves only when the retained CA has at least 31 days left.
        openssl('x509', '-in', args.renew_from / f'{name}.crt', '-checkend', 31 * 86400, '-noout')
        for suffix in ['crt', 'key']:
            shutil.copyfile(args.renew_from / f'{name}.{suffix}', out / f'{name}.{suffix}')
    else:
        openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-days', 365,
                '-subj', f'/CN=sample-mtls-{name}', '-keyout', out / f'{name}.key', '-out', out / f'{name}.crt',
                '-addext', 'subjectKeyIdentifier=hash', '-addext', 'basicConstraints=critical,CA:TRUE',
                '-addext', 'keyUsage=critical,keyCertSign,cRLSign')

# Distinct client CAs let the tests detect backend credentials used at the frontend.
roles = [
    ('gateway', 'ca', 'serverAuth', 'DNS:localhost,DNS:gateway-tls,DNS:gateway-1,DNS:gateway-2,IP:127.0.0.1'),
    ('backend', 'ca', 'serverAuth', 'DNS:mcp-mtls'),
    ('client', 'frontend-ca', 'clientAuth', 'DNS:client.sample.local'),
    ('proxy-client', 'frontend-ca', 'clientAuth', 'DNS:nginx.sample.local'),
    ('gateway-client', 'backend-ca', 'clientAuth', 'DNS:gateway.sample.local'),
    ('health-client', 'backend-ca', 'clientAuth', 'DNS:health.sample.local'),
    ('rogue-client', 'wrong-ca', 'clientAuth', 'DNS:untrusted.sample.local'),
]
for name, ca, usage, san in roles:
    d = out / name
    d.mkdir()
    ext = d / 'extensions.cnf'
    ext.write_text('basicConstraints=critical,CA:FALSE\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n'
                   f'keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage={usage}\nsubjectAltName={san}\n')
    openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', f'/CN={name}',
            '-keyout', d / 'tls.key', '-out', d / 'tls.csr')
    openssl('x509', '-req', '-in', d / 'tls.csr', '-CA', out / f'{ca}.crt', '-CAkey', out / f'{ca}.key',
            '-set_serial', '0x' + secrets.token_hex(16), '-days', 30 if args.renew_from else 7,
            '-sha256', '-extfile', ext, '-out', d / 'tls.crt')
    openssl('verify', '-CAfile', out / f'{ca}.crt', d / 'tls.crt')

print(f'Created mTLS generation: {out}; leaves valid for {30 if args.renew_from else 7} days')
