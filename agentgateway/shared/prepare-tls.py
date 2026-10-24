"""Generate local-only CA/leaf certificates without overwriting existing files."""

import os
from pathlib import Path
import subprocess
import sys

out = Path(sys.argv[1]).resolve()
if out.exists():
    raise SystemExit('Certificate directory already exists; reuse it or choose a new directory')

os.umask(0o077)
out.mkdir(parents=True)


def openssl(*args):
    result = subprocess.run(['openssl', *map(str, args)], capture_output=True)
    if result.returncode:
        raise SystemExit('OpenSSL failed; generated files retained for inspection')


for name in ['ca', 'wrong-ca']:
    openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-days', '30',
            '-subj', f'/CN=sample-{name}', '-keyout', out / f'{name}.key', '-out', out / f'{name}.crt',
            '-addext', 'subjectKeyIdentifier=hash', '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')

for name, san in [('gateway', 'DNS:localhost,DNS:gateway-tls,DNS:gateway-1,DNS:gateway-2,IP:127.0.0.1'),
                  ('backend', 'DNS:mcp-tls')]:
    directory = out / name
    directory.mkdir()
    ext = directory / 'extensions.cnf'
    ext.write_text(f'basicConstraints=critical,CA:FALSE\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName={san}\n')
    openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', f'/CN={name}',
            '-keyout', directory / 'tls.key', '-out', directory / 'tls.csr')
    openssl('x509', '-req', '-in', directory / 'tls.csr', '-CA', out / 'ca.crt', '-CAkey', out / 'ca.key',
            '-set_serial', '1' if name == 'gateway' else '2', '-days', '30', '-sha256',
            '-extfile', ext, '-out', directory / 'tls.crt')
    openssl('verify', '-CAfile', out / 'ca.crt', directory / 'tls.crt')

print(f'Created local certificates in {out}; private keys stay local, valid for 30 days')
