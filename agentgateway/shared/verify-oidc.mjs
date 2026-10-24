// Verify the ID token independently; input arrives on stdin and is never logged.
import { createPublicKey, verify } from 'node:crypto';
import assert from 'node:assert/strict';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { token, jwks, issuer, nonce } = JSON.parse(input);
const [header, payload, signature] = token.split('.');
const h = JSON.parse(Buffer.from(header, 'base64url'));
const p = JSON.parse(Buffer.from(payload, 'base64url'));
assert.equal(h.alg, 'RS256');
const jwk = jwks.keys.find(k => k.kid === h.kid && k.kty === 'RSA' && k.use === 'sig');
assert.ok(jwk);
assert.ok(verify('RSA-SHA256', Buffer.from(`${header}.${payload}`),
  createPublicKey({ key: jwk, format: 'jwk' }), Buffer.from(signature, 'base64url')));
assert.equal(p.iss, issuer);
assert.ok([p.aud].flat().includes('browser'));
assert.equal(p.nonce, nonce);
assert.ok(p.exp > Date.now() / 1000);
assert.ok(p.sub);
process.stdout.write('PASS: OIDC ID token signature, issuer, audience, nonce and expiration\n');
