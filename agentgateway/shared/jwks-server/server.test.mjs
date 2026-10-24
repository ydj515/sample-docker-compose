import test from 'node:test';
import assert from 'node:assert/strict';
import { createPublicKey, verify } from 'node:crypto';
import { createFixture } from './server.mjs';

test('signatures, overlap, retirement and outage use public keys only', async () => {
  const server = createFixture('http://issuer', 'resource');
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const a = await (await fetch(base + '/jwks')).json();
    assert.deepEqual(a.keys.map(k => k.kid), ['A']);
    assert.ok(a.keys.every(k => !k.d && !k.p && !k.q));
    const token = (await (await fetch(base + '/token?kid=A', { method: 'POST' })).json()).access_token;
    const [h, p, signature] = token.split('.');
    assert.ok(verify('RSA-SHA256', Buffer.from(`${h}.${p}`), createPublicKey({ key: a.keys[0], format: 'jwk' }), Buffer.from(signature, 'base64url')));
    for (const [published, unavailable] of [[['A', 'B'], false], [['B'], false], [['B'], true]]) {
      const r = await fetch(base + '/control', { method: 'POST', body: JSON.stringify({ published, unavailable }) });
      assert.equal(r.status, 200);
      const keys = await fetch(base + '/jwks');
      assert.equal(keys.status, unavailable ? 503 : 200);
      if (!unavailable) assert.deepEqual((await keys.json()).keys.map(k => k.kid), published);
    }
    assert.equal((await fetch(base + '/token?kid=unknown', { method: 'POST' })).status, 400);
    assert.equal((await fetch(base + '/control', { method: 'POST', body: '{}' })).status, 400);
  } finally { await new Promise(resolve => server.close(resolve)); }
});
