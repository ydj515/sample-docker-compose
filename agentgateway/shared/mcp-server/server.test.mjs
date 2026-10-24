import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer, dispatch, inspectHeaders } from './server.mjs';

const call = (name, args) => dispatch({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } });

test('echo preserves Unicode and add handles negative values', () => {
  assert.equal(call('echo', { message: '안녕 MCP' }).result.content[0].text, '안녕 MCP');
  assert.equal(call('add', { a: -3, b: 1.5 }).result.content[0].text, '-1.5');
});
test('invalid arguments and unknown tools fail explicitly', () => {
  assert.equal(call('add', { a: '1', b: 2 }).error.code, -32602);
  assert.equal(call('echo', {}).error.code, -32602);
  assert.equal(call('unknown', {}).error.code, -32602);
  assert.equal(call('add', { a: Number.MAX_VALUE, b: Number.MAX_VALUE }).result.isError, true);
});
test('HTTP transport handles initialization, notifications, malformed JSON, and blocked origins', async () => {
  const server = createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  const headers = { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' };
  try {
    assert.equal((await fetch(`${url}/healthz`)).status, 200);
    const init = await fetch(`${url}/mcp`, { method: 'POST', headers, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-03-26', clientInfo: { name: 'test', version: '1' }, capabilities: {} } }) });
    assert.equal((await init.json()).result.serverInfo.name, 'sample-mcp-server');
    const notify = await fetch(`${url}/mcp`, { method: 'POST', headers, body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) });
    assert.equal(notify.status, 202);
    assert.equal(await notify.text(), '');
    assert.equal((await fetch(`${url}/mcp`, { method: 'POST', headers, body: '{' })).status, 400);
    assert.equal((await fetch(`${url}/mcp`, { headers: { Origin: 'https://example.com' } })).status, 403);
    assert.equal((await fetch(`${url}/mcp`)).status, 405);
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});

test('policy probe exposes only explicit test headers', () => {
  assert.deepEqual(inspectHeaders({ 'x-policy-winner': 'target', authorization: 'redacted-test', cookie: 'redacted-test', 'x-other': 'hidden' }), { 'x-policy-winner': 'target' });
});
