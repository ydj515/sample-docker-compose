// Local failure fixture, not an authorization server. Never use these tokens outside the sample.
import http from 'node:http';
import { generateKeyPairSync, sign } from 'node:crypto';
import { pathToFileURL } from 'node:url';

export function createFixture(issuer, audience) {
  const pairs = Object.fromEntries(['A', 'B'].map(kid => {
    const pair = generateKeyPairSync('rsa', { modulusLength: 2048 });
    return [kid, { ...pair, jwk: { ...pair.publicKey.export({ format: 'jwk' }), kid, alg: 'RS256', use: 'sig' } }];
  }));
  let published = ['A'], unavailable = false, fetches = 0, failures = 0;
  const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
  return http.createServer(async (req, res) => {
    const send = (status, body) => {
      res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
      res.end(JSON.stringify(body));
    };
    const url = new URL(req.url, 'http://fixture');
    if (req.method === 'GET' && url.pathname === '/healthz') return send(200, { status: 'ok' });
    if (req.method === 'GET' && url.pathname === '/stats') return send(200, { published, unavailable, fetches, failures });
    if (req.method === 'GET' && url.pathname === '/jwks') {
      fetches++;
      if (unavailable) { failures++; return send(503, { error: 'injected outage' }); }
      res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'public, max-age=60' });
      return res.end(JSON.stringify({ keys: published.map(kid => pairs[kid].jwk) }));
    }
    if (req.method === 'POST' && url.pathname === '/token') {
      const kid = url.searchParams.get('kid');
      if (!Object.hasOwn(pairs, kid)) return send(400, { error: 'unknown key' });
      const now = Math.floor(Date.now() / 1000);
      const input = `${encode({ alg: 'RS256', typ: 'JWT', kid })}.${encode({
        iss: issuer, aud: audience, sub: 'rotation-fixture', demo_role: 'viewer', iat: now, exp: now + 900,
      })}`;
      return send(200, { access_token: `${input}.${sign('RSA-SHA256', Buffer.from(input), pairs[kid].privateKey).toString('base64url')}` });
    }
    if (req.method === 'POST' && url.pathname === '/control') {
      let body = '';
      for await (const chunk of req) {
        body += chunk;
        if (body.length > 4096) return send(413, { error: 'body too large' });
      }
      try {
        const next = JSON.parse(body);
        if (!Array.isArray(next.published) || !next.published.length ||
            next.published.some(kid => !Object.hasOwn(pairs, kid)) || typeof next.unavailable !== 'boolean') {
          return send(400, { error: 'invalid control' });
        }
        published = [...new Set(next.published)]; unavailable = next.unavailable;
        return send(200, { published, unavailable });
      } catch { return send(400, { error: 'invalid JSON' }); }
    }
    send(404, { error: 'not found' });
  });
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (!process.env.ISSUER || !process.env.AUDIENCE) throw new Error('ISSUER and AUDIENCE required');
  createFixture(process.env.ISSUER, process.env.AUDIENCE).listen(9080, '0.0.0.0');
}
