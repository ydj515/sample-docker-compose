"""Generate new leaves, recreate this local Compose stack, then verify mTLS.

The old generation is preserved. This is a restart-based example, not zero-downtime rotation.
"""

import argparse
import hashlib
import os
from pathlib import Path
import ssl
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('mode', choices=['single', 'ha'])
p.add_argument('previous', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
shared = Path(__file__).resolve().parent
project = shared.parent / a.mode
old, new = a.previous.resolve(), a.output.resolve()
subprocess.run([sys.executable, str(shared / 'prepare-mtls.py'), str(new), '--renew-from', str(old)], check=True)
env = {**os.environ, 'MTLS_CERT_DIR': str(new), 'AGENTGATEWAY_CONFIG': './config-mtls.yaml',
       'LOCAL_UID': str(os.getuid()), 'LOCAL_GID': str(os.getgid())}
compose = ['docker', 'compose', '-f', 'docker-compose.yml', '-f', 'compose-mtls.yml']


def run(*command, **kwargs):
    return subprocess.run(compose + list(command), cwd=project, env=env, check=True, **kwargs)


# Reject a bad generation before recreating any running service.
subprocess.run([sys.executable, str(shared / 'validate-mtls.py'), str(new)], check=True)
run('config', '--quiet')
run('up', '-d', '--force-recreate', '--wait')
ports = [3443] if a.mode == 'single' else [13443, 14401, 14402]
for port in ports:
    subprocess.run([sys.executable, str(shared / 'test-mtls.py'), f'https://localhost:{port}', str(new), '--previous', str(old)], check=True)

# Check the certificate actually served by the backend, not just the files on disk.
probe = """const fs=require('node:fs'),tls=require('node:tls'),crypto=require('node:crypto');
const s=tls.connect({host:'mcp-mtls',port:3445,servername:'mcp-mtls',
ca:fs.readFileSync('/certs/ca.crt'),cert:fs.readFileSync('/certs/health-client/tls.crt'),
key:fs.readFileSync('/certs/health-client/tls.key')},()=>{
console.log(crypto.createHash('sha256').update(s.getPeerCertificate().raw).digest('hex'));s.end();});
s.setTimeout(5000,()=>{s.destroy();process.exit(1)});s.on('error',()=>process.exit(1));"""
actual = run('exec', '-T', 'mcp-mtls', 'node', '-e', probe, capture_output=True, text=True).stdout.strip()
expected = hashlib.sha256(ssl.PEM_cert_to_DER_cert((new / 'backend/tls.crt').read_text())).hexdigest()
assert actual == expected, 'Backend did not present renewed certificate'
print('PASS: backend presents new generation certificate')

print(f'Rotation complete. Keep MTLS_CERT_DIR={new} for subsequent Compose operations.')

print(f'Rollback: select previous MTLS_CERT_DIR={old} and recreate with compose-mtls.yml.')
