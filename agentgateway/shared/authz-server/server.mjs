import http from 'node:http';
import { pathToFileURL } from 'node:url';

export function authorize(path, method, role, body) {
  if (!['viewer', 'calculator'].includes(role)) return false;
  if (path === '/auth/mcp') {
    let rpc;
    try { rpc = JSON.parse(body); } catch { return false; }
    if (!rpc || Array.isArray(rpc) || rpc.jsonrpc !== '2.0') return false;
    if (['initialize', 'notifications/initialized', 'tools/list', 'ping'].includes(rpc.method)) return true;
    if (rpc.method !== 'tools/call') return false;
    return rpc.params?.name === 'echo' || (rpc.params?.name === 'add' && role === 'calculator');
  }
  return path === '/auth/processing/authz' && (method === 'GET' || (method === 'POST' && role === 'calculator'));
}

export function createServer() {
  return http.createServer(async (req, res) => {
    const path = new URL(req.url, 'http://authz').pathname;
    const send = (code, message) => { res.writeHead(code, {'Content-Type': 'text/plain'}); res.end(message); };
    if (path === '/healthz') return send(200, 'ok');
    const chunks = []; let size = 0;
    try {
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 1024) return send(413, 'Authorization body too large');
        chunks.push(chunk);
      }
      if (path === '/auth/processing/error') return send(503, 'Authorization service unavailable');
      if (path === '/auth/processing/slow') {
        await new Promise(resolve => setTimeout(resolve, 500));
        return send(200, 'Delayed authorization');
      }
      const allowed = authorize(path, req.method, req.headers['x-authz-role'], Buffer.concat(chunks).toString('utf8'));
      if (!allowed) return send(403, 'Authorization denied');
      res.setHeader('x-policy-winner', 'external-authz');
      return send(200, 'Authorized');
    } catch { if (!res.headersSent) send(400, 'Incomplete authorization request'); }
  });
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const server = createServer();
  server.listen(9000, '0.0.0.0', () => console.log('Authorization service listening on port 9000'));
  process.on('SIGTERM', () => server.close());
}
