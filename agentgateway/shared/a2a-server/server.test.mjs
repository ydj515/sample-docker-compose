import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer, rpc } from './server.mjs';
const message = { kind: 'message', role: 'user', messageId: 'm1', parts: [{ kind: 'text', text: 'hello' }] };
const request = { jsonrpc: '2.0', id: 1, method: 'message/send', params: { message } };
test('stateless deterministic response and validation', () => {
  assert.equal(rpc(request).result.parts[0].text, 'Mock LLM: hello');
  assert.equal(rpc({ ...request, method: 'message/stream' }).error.code, -32601);
  assert.equal(rpc({ ...request, params: {} }).error.code, -32602);
  assert.equal(rpc({ ...request, params: { message: { ...message, taskId: 'unknown' } } }).error.code, -32602);
  assert.equal(rpc([]).error.code, -32600);
});
test('HTTP discovery, parse errors, content type, body bound and origin', async () => {
  const server = createServer(); await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const card = await (await fetch(base + '/a2a/.well-known/agent-card.json')).json();
    assert.equal(card.capabilities.streaming, false);
    const post = body => fetch(base + '/a2a', { method: 'POST', headers: { 'content-type': 'application/json' }, body });
    assert.equal((await (await post('{')).json()).error.code, -32700);
    assert.equal((await post('x'.repeat(65537))).status, 413);
    assert.equal((await fetch(base + '/a2a', { method: 'POST', body: '{}' })).status, 415);
    assert.equal((await fetch(base + '/healthz', { headers: { origin: 'http://example.com' } })).status, 403);
  } finally { await new Promise(r => server.close(r)); }
});
