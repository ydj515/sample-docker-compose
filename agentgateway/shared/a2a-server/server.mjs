import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';

export function rpc(input) {
  const error = (code, message) => ({ jsonrpc: '2.0', id: input?.id ?? null, error: { code, message } });
  if (!input || Array.isArray(input) || input.jsonrpc !== '2.0' ||
      !['string', 'number'].includes(typeof input.id) || typeof input.method !== 'string')
    return error(-32600, 'Invalid Request');
  if (input.method !== 'message/send') return error(-32601, 'Method not found');
  const m = input.params?.message;
  if (!m || m.kind !== 'message' || m.role !== 'user' || typeof m.messageId !== 'string' || !m.messageId ||
      !Array.isArray(m.parts) || !m.parts.length || m.parts.some(p => !p || p.kind !== 'text' || typeof p.text !== 'string') ||
      m.taskId !== undefined || (m.contextId !== undefined && typeof m.contextId !== 'string') ||
      input.params.configuration !== undefined)
    return error(-32602, 'Expected a text-only user Message; tasks and configuration are unsupported');
  return { jsonrpc: '2.0', id: input.id, result: {
    kind: 'message', role: 'agent', messageId: randomUUID(), contextId: m.contextId || randomUUID(),
    parts: [{ kind: 'text', text: `Mock LLM: ${m.parts.map(p => p.text).join('\n')}` }],
    metadata: { mock: true, model: 'deterministic-echo', networkCalls: 0 },
  } };
}

export function createServer() {
  return http.createServer(async (req, res) => {
    const send = (status, body) => { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(body)); };
    const path = new URL(req.url, 'http://localhost').pathname;
    if (req.headers.origin) return send(403, { error: 'Browser origins unsupported' });
    if (req.method === 'GET' && path === '/healthz') return send(200, { status: 'ok' });
    if (req.method === 'GET' && ['/a2a', '/raw'].some(p => path === `${p}/.well-known/agent-card.json`))
      return send(200, {
        protocolVersion: '0.3.0', name: 'Mock LLM Agent', description: 'Stateless deterministic text echo; no external LLM calls.',
        url: 'http://a2a-demo:3010/a2a', preferredTransport: 'JSONRPC', version: '1.0.0',
        capabilities: { streaming: false, pushNotifications: false },
        defaultInputModes: ['text/plain'], defaultOutputModes: ['text/plain'],
        securitySchemes: { gatewayKey: { type: 'http', scheme: 'bearer' } }, security: [{ gatewayKey: [] }],
        skills: [{ id: 'mock-echo', name: 'Mock echo', description: 'Returns input with a Mock LLM prefix.', tags: ['mock', 'echo'], examples: ['hello'] }],
      });
    if (req.method !== 'POST' || !['/a2a', '/a2a/', '/raw', '/raw/'].includes(path)) return send(404, { error: 'Not found' });
    if (!/^application\/json(?:;|$)/i.test(req.headers['content-type'] || '')) return send(415, { error: 'Expected application/json' });
    let size = 0; const chunks = [];
    try {
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 65536) { send(413, { error: 'Body too large' }); return; }
        chunks.push(chunk);
      }
      let input;
      try { input = JSON.parse(Buffer.concat(chunks).toString()); }
      catch { return send(200, { jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } }); }
      send(200, rpc(input));
    } catch { if (!res.headersSent) send(400, { error: 'Incomplete request' }); }
  });
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href)
  createServer().listen(Number(process.env.PORT || 3010), '0.0.0.0', () => console.log('Mock A2A server listening'));
