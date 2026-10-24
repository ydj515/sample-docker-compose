"""Generate local-only credentials and a gateway config containing hashes."""

import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

root = Path(sys.argv[1]).resolve()
if root.name not in ('single', 'ha'):
    raise SystemExit('Specify the single or ha directory')

folder = root / 'data'
folder.mkdir(exist_ok=True)
path = folder / 'auth-keys.json'
# Reuse local keys so rerunning preparation does not invalidate existing test clients.
if path.exists():
    keys = json.loads(path.read_text())
else:
    keys = {name: secrets.token_urlsafe(32) for name in ('baseline', 'denied', 'invalid', 'calculator')}
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        json.dump(keys, f)

variant = sys.argv[2] if len(sys.argv) > 2 else 'auth'
if variant not in ('auth', 'extauthz', 'a2a'):
    raise SystemExit('Variant must be auth, extauthz or a2a')

config = (root / f'config-{variant}.template.yaml').read_text()
# Mount only hashes in the Gateway config; raw keys stay in the owner-only file.
for name, value in keys.items():
    config = config.replace('@' + name.upper() + '_HASH@', 'sha256:' + hashlib.sha256(value.encode()).hexdigest())

out = folder / f'config-{variant}.yaml'
with os.fdopen(os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
    f.write(config)

print('Prepared local credentials and hashed configuration; no key values printed')
