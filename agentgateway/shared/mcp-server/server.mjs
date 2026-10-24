import http from 'node:http';
import https from 'node:https';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const protocolVersion = '2025-03-26';
const tools = [
  {
    name: 'echo', description: 'Return the supplied message.',
    inputSchema: { type: 'object', properties: { message: { type: 'string' } }, required: ['message'], additionalProperties: false },
  },
  {
    name: 'add', description: 'Add two finite numbers.',
    inputSchema: { type: 'object', properties: { a: { type: 'number' }, b: { type: 'number' } }, required: ['a', 'b'], additionalProperties: false },
  },
];
const error = (id, code, message) => ({ jsonrpc: '2.0', id, error: { code, message } });
const textResult = (text, isError = false) => ({ content: [{ type: 'text', text }], isError });

export function dispatch(request) {
  if (!request || Array.isArray(request) || request.jsonrpc !== '2.0' || typeof request.method !== 'string'
      || ('id' in request && typeof request.id !== 'string' && !Number.isInteger(request.id))) {
    return error(null, -32600, 'Invalid Request');
  }
  if (!('id' in request)) return null;
  const { id, method, params = {} } = request;
  if (!params || typeof params !== 'object' || Array.isArray(params)) return error(id, -32602, 'Invalid params');
  let result;
  switch (method) {
    case 'initialize':
      if (typeof params.protocolVersion !== 'string' || !params.clientInfo || !params.capabilities) {
        return error(id, -32602, 'Invalid initialization params');
      }
      result = { protocolVersion, capabilities: { tools: { listChanged: false } }, serverInfo: { name: 'sample-mcp-server', version: '1.0.0' } };
      break;
    case 'ping': result = {}; break;
    case 'tools/list': result = { tools }; break;
    case 'tools/call': {
      const args = params.arguments;
      if (!tools.some(tool => tool.name === params.name)) return error(id, -32602, 'Unknown tool');
      if (!args || typeof args !== 'object' || Array.isArray(args)) return error(id, -32602, 'Invalid tool arguments');
      if (params.name === 'echo') {
        if (typeof args.message !== 'string' || Object.keys(args).some(key => key !== 'message')) return error(id, -32602, 'Expected a string message');
        result = textResult(args.message);
      } else {
        if (!Number.isFinite(args.a) || !Number.isFinite(args.b) || Object.keys(args).some(key => !['a', 'b'].includes(key))) return error(id, -32602, 'Expected finite numbers a and b');
        const sum = args.a + args.b;
        result = Number.isFinite(sum) ? textResult(String(sum)) : textResult('Result is outside the finite number range', true);
      }
      break;
    }
    default: return error(id, -32601, 'Method not found');
  }
  return { jsonrpc: '2.0', id, result };
}

const probeHeaders = ['x-policy-gateway', 'x-policy-route', 'x-policy-backend', 'x-policy-winner', 'x-policy-common'];
export function inspectHeaders(headers) {
  return Object.fromEntries(probeHeaders.filter(name => headers[name] !== undefined).map(name => [name, headers[name]]));
}

function dispatchProbe(request, headers) {
  if (request?.jsonrpc === '2.0' && request.id !== undefined && request.method === 'tools/list') {
    return { jsonrpc: '2.0', id: request.id, result: { tools: [{ name: 'inspect_headers', description: 'Return only policy test headers.', inputSchema: { type: 'object', properties: {}, additionalProperties: false } }] } };
  }
  if (request?.jsonrpc === '2.0' && request.id !== undefined && request.method === 'tools/call' && request.params?.name === 'inspect_headers') {
    return { jsonrpc: '2.0', id: request.id, result: textResult(JSON.stringify(inspectHeaders(headers))) };
  }
  return dispatch(request);
}

export function createServer(tlsOptions) {
  const attempts = new Map();
  const processing = new Map();
  const listen = tlsOptions ? handler => https.createServer(tlsOptions, handler) : handler => http.createServer(handler);
  return listen(async (req, res) => {
    const send = (status, body) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(body === undefined ? undefined : JSON.stringify(body));
    };
    // The backend is internal to Compose; browser calls must use the gateway.
    if (req.headers.origin) return send(403, { error: 'Direct browser access is not allowed' });
    const probeUrl = new URL(req.url, 'http://localhost');
    if (probeUrl.pathname.startsWith('/processing/')) {
      const id = probeUrl.searchParams.get('id');
      if (!id || !/^[a-zA-Z0-9-]{1,80}$/.test(id)) return send(400, { error: 'Invalid probe id' });
      if (probeUrl.pathname.endsWith('/stats')) return send(200, processing.get(id) ?? { count: 0 });
      const chunks = [];
      let size = 0;
      try {
        for await (const chunk of req) {
          size += chunk.length;
          if (size > 65536) return send(413, { error: 'Request exceeds 64 KiB' });
          chunks.push(chunk);
        }
        if (processing.size >= 1000 && !processing.has(id)) processing.delete(processing.keys().next().value);
        const record = { count: (processing.get(id)?.count ?? 0) + 1, method: req.method,
          path: probeUrl.pathname, query: probeUrl.searchParams.get('keep'),
          headers: inspectHeaders(req.headers), body: Buffer.concat(chunks).toString('utf8') };
        processing.set(id, record);
        res.setHeader('x-policy-winner', 'backend');
        res.setHeader('x-policy-common', 'remove-me');
        return send(process.env.PROBE_ROLE === 'mirror' ? 503 : 200, record);
      } catch {
        if (!res.headersSent) return send(400, { error: 'Incomplete probe request' });
        return res.end();
      }
    }
    if (probeUrl.pathname.startsWith('/resilience/')) {
      const id = probeUrl.searchParams.get('id');
      if (!id || !/^[a-zA-Z0-9-]{1,80}$/.test(id)) return send(400, { error: 'Invalid probe id' });
      if (probeUrl.pathname === '/resilience/stats') return send(200, { attempts: attempts.get(id) ?? 0 });
      if (!['/resilience/retry', '/resilience/no-retry', '/resilience/timeout', '/resilience/budget'].includes(probeUrl.pathname)) return send(404, { error: 'Not found' });
      const failures = Number(probeUrl.searchParams.get('failures') ?? 0);
      const delay = Number(probeUrl.searchParams.get('delay') ?? 0);
      const status = Number(probeUrl.searchParams.get('status') ?? 503);
      if (!Number.isInteger(failures) || failures < 0 || failures > 20 || !Number.isInteger(delay) || delay < 0 || delay > 2000 || ![400, 503].includes(status)) return send(400, { error: 'Invalid probe parameters' });
      if (attempts.size >= 1000 && !attempts.has(id)) attempts.delete(attempts.keys().next().value);
      const attempt = (attempts.get(id) ?? 0) + 1;
      attempts.set(id, attempt);
      // Count receipt even if the gateway later times out: cancellation cannot undo work.
      req.resume();
      await new Promise(resolve => setTimeout(resolve, delay));
      return send(attempt <= failures ? status : 200, { attempt, method: req.method });
    }
    if (req.url === '/healthz' && req.method === 'GET') return send(200, { status: 'ok' });
    if (req.url === '/inspect-headers' && req.method === 'GET') return send(200, inspectHeaders(req.headers));
    if (req.url !== '/mcp' && req.url !== '/mcp-inspect') return send(404, { error: 'Not found' });
    if (req.method !== 'POST') {
      res.setHeader('Allow', 'POST');
      return send(405, { error: 'Only POST is supported; no SSE stream or sessions' });
    }
    if (req.headers['content-type']?.split(';')[0].trim() !== 'application/json') return send(415, { error: 'Expected application/json' });
    const accept = req.headers.accept ?? '';
    if (!accept.includes('application/json') || !accept.includes('text/event-stream')) return send(406, { error: 'Accept must include application/json and text/event-stream' });
    const chunks = [];
    let size = 0;
    try {
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 65536) { send(413, { error: 'Request exceeds 64 KiB' }); return; }
        chunks.push(chunk);
      }
      let body;
      try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
      catch { return send(400, error(null, -32700, 'Parse error')); }
      const handler = req.url === '/mcp-inspect' ? item => dispatchProbe(item, req.headers) : dispatch;
      const response = Array.isArray(body)
        ? (body.length ? body.map(handler).filter(Boolean) : error(null, -32600, 'Empty batch'))
        : handler(body);
      if (response === null || (Array.isArray(response) && response.length === 0)) return send(202);
      send(200, response);
    } catch {
      if (!res.headersSent) send(500, { error: 'Request processing failed' });
      else res.end();
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (Boolean(process.env.TLS_CERT) !== Boolean(process.env.TLS_KEY)) throw new Error('TLS_CERT and TLS_KEY must be configured together');
  if (process.env.TLS_CLIENT_CA && !process.env.TLS_CERT) throw new Error('TLS_CLIENT_CA requires TLS_CERT and TLS_KEY');
  const server = createServer(process.env.TLS_CERT ? {
    cert: readFileSync(process.env.TLS_CERT), key: readFileSync(process.env.TLS_KEY), minVersion: 'TLSv1.2',
    ...(process.env.TLS_CLIENT_CA ? {ca: readFileSync(process.env.TLS_CLIENT_CA), requestCert: true, rejectUnauthorized: true} : {}),
  } : undefined);
  const port = Number(process.env.PORT ?? 3005);
  server.listen(port, '0.0.0.0', () => console.log(`Sample MCP server listening on port ${port}`));
  process.on('SIGTERM', () => server.close());
  process.on('SIGINT', () => server.close());
}
