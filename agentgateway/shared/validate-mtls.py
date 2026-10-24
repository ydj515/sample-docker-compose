"""Reject incomplete, expired, untrusted or mismatched local mTLS generations before deployment."""

import argparse
from pathlib import Path
import ssl
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('directory', type=Path)
a = p.parse_args()
roles = {'gateway': ('ca', 'sslserver', 'localhost'), 'backend': ('ca', 'sslserver', 'mcp-mtls'),
         'client': ('frontend-ca', 'sslclient', None), 'proxy-client': ('frontend-ca', 'sslclient', None),
         'gateway-client': ('backend-ca', 'sslclient', None), 'health-client': ('backend-ca', 'sslclient', None),
         'rogue-client': ('wrong-ca', 'sslclient', None)}
for name, (ca, purpose, hostname) in roles.items():
    cert, key = a.directory / name / 'tls.crt', a.directory / name / 'tls.key'

    try:
        # Loading checks the key pair; OpenSSL separately checks trust, dates and purpose.
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_cert_chain(cert, key)
        result = subprocess.run(['openssl', 'verify', '-purpose', purpose, '-CAfile',
                                 str(a.directory / f'{ca}.crt'), str(cert)], capture_output=True)
        if result.returncode:
            raise ValueError('Certificate verification failed')

        if hostname:
            names = ssl._ssl._test_decode_cert(str(cert)).get('subjectAltName', ())
            if ('DNS', hostname) not in names:
                raise ValueError('Required server hostname missing')
    except (OSError, ValueError, ssl.SSLError):
        raise SystemExit(f'REJECT: {name} certificate/key/trust/validity/hostname check failed')

print('PASS: mTLS generation preflight (pairs, trust, validity, purpose, server names)')
