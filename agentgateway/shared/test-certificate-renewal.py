"""Stage renewal failures; optionally deploy a bad server chain and restore the good generation.

All fixtures are retained under mtls-certs. Runtime mode recreates the local stack and causes downtime.
"""

import argparse
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('mode', choices=('single', 'ha'))
p.add_argument('cert_dir', type=Path)
p.add_argument('--runtime', action='store_true')
p.add_argument('--variant', choices=('mtls', 'oidc-mtls'), default='mtls')
a = p.parse_args()
os.umask(0o077)
shared = Path(__file__).resolve().parent
project = shared.parent / a.mode
old = a.cert_dir.resolve()
subprocess.run([sys.executable, str(shared / 'validate-mtls.py'), str(old)], check=True)
before = {p: hashlib.sha256(p.read_bytes()).digest() for p in old.rglob('*') if p.is_file()}
work = project / 'mtls-certs' / ('failure-' + secrets.token_hex(6))
work.mkdir(parents=True)


def openssl(*args):
    result = subprocess.run(['openssl', *map(str, args)], capture_output=True)
    assert result.returncode == 0, 'Fixture certificate generation failed'


def copy(name):
    target = work / name
    shutil.copytree(old, target)
    return target


def reject(path):
    result = subprocess.run([sys.executable, str(shared / 'validate-mtls.py'), str(path)], capture_output=True)
    assert result.returncode != 0, 'Invalid staged generation passed preflight'


mismatch = copy('mismatched-key')
shutil.copyfile(old / 'client/tls.key', mismatch / 'gateway/tls.key')
reject(mismatch)
print('PASS: staged certificate/private-key mismatch rejected', flush=True)

wrong = copy('wrong-server-ca')
openssl('x509', '-req', '-in', wrong / 'gateway/tls.csr', '-CA', wrong / 'wrong-ca.crt',
        '-CAkey', wrong / 'wrong-ca.key', '-set_serial', '0x' + secrets.token_hex(16),
        '-days', 7, '-sha256', '-extfile', wrong / 'gateway/extensions.cnf', '-out', wrong / 'gateway/tls.crt')
reject(wrong)
print('PASS: staged untrusted replacement server certificate rejected', flush=True)

expired = copy('expired-server')
(expired / 'issued').mkdir()
(expired / 'index.txt').write_text('')
(expired / 'serial').write_text(secrets.token_hex(16) + '\n')
config = expired / 'expire.cnf'
config.write_text(f"""[ca]
default_ca = local
[local]
database = {expired / 'index.txt'}
serial = {expired / 'serial'}
new_certs_dir = {expired / 'issued'}
certificate = {expired / 'ca.crt'}
private_key = {expired / 'ca.key'}
default_md = sha256
policy = names
[names]
commonName = supplied
""")
openssl('ca', '-batch', '-config', config, '-in', expired / 'gateway/tls.csr',
        '-startdate', '200101000000Z', '-enddate', '200102000000Z',
        '-extfile', expired / 'gateway/extensions.cnf', '-out', expired / 'gateway/tls.crt')
reject(expired)
print('PASS: staged expired replacement certificate rejected', flush=True)

short_ca = copy('insufficient-ca-lifetime')
openssl('req', '-x509', '-new', '-key', short_ca / 'ca.key', '-days', 1, '-sha256',
        '-subj', '/CN=short-lived-test-ca', '-out', short_ca / 'ca.crt')
result = subprocess.run([sys.executable, str(shared / 'prepare-mtls.py'), str(work / 'failed-renewal'),
                         '--renew-from', str(short_ca)], capture_output=True)
assert result.returncode != 0, 'Renewal with insufficient CA lifetime unexpectedly succeeded'
print('PASS: issuance aborts when CA has less than 31 days remaining', flush=True)

assert all(hashlib.sha256(path.read_bytes()).digest() == digest for path, digest in before.items())
print('PASS: original generation unchanged after all failed preparations', flush=True)

if a.runtime:
    compose = ['docker', 'compose', '-f', 'docker-compose.yml', '-f', 'compose-mtls.yml']
    if a.variant == 'oidc-mtls':
        compose += ['-f', 'compose-oidc-mtls.yml']

    env = {**os.environ, 'LOCAL_UID': str(os.getuid()), 'LOCAL_GID': str(os.getgid()),
           'AGENTGATEWAY_CONFIG': f'./config-{a.variant}.yaml'}

    def deploy(directory):
        result = subprocess.run(compose + ['up', '-d', '--force-recreate', '--wait'], cwd=project,
                                env={**env, 'MTLS_CERT_DIR': str(directory)}, capture_output=True, text=True)
        assert result.returncode == 0, 'Local stack recreation failed; inspect Compose state (outputs withheld)'

    ctx = ssl.create_default_context(cafile=str(old / 'ca.crt'))
    ctx.load_cert_chain(old / 'client/tls.crt', old / 'client/tls.key')
    ports = [3443] if a.mode == 'single' else [14401, 14402, 13443]

    def fingerprint(port):
        with socket.create_connection(('localhost', port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname='localhost') as tls:
                return hashlib.sha256(tls.getpeercert(binary_form=True)).digest()

    expected = hashlib.sha256(ssl.PEM_cert_to_DER_cert((old / 'gateway/tls.crt').read_text())).digest()
    deploy(old)
    assert all(fingerprint(port) == expected for port in ports)

    try:
        # Deliberately bypass the preflight in this failure-injection test only.
        deploy(wrong)
        for port in ports:
            try:
                fingerprint(port)
            except ssl.SSLCertVerificationError:
                continue

            raise AssertionError('Client accepted an untrusted replacement certificate')

        print('PASS: bypassing preflight causes client TLS verification failures on all endpoints', flush=True)
    finally:
        # Restore after assertion failures too; abrupt process/host termination still needs manual recovery.
        deploy(old)
        assert all(fingerprint(port) == expected for port in ports), 'Rollback fingerprint mismatch'
        print('PASS: rollback restores original server fingerprint on all endpoints', flush=True)

print(f'Failure fixtures retained: {work}')
