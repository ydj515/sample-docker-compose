import assert from 'node:assert/strict';
import { test } from 'node:test';
import { authorize, createServer } from './server.mjs';
test('HTTP methods and roles default to deny', () => {
  assert.equal(authorize('/auth/processing/authz', 'GET', 'viewer', ''), true);
  assert.equal(authorize('/auth/processing/authz', 'POST', 'viewer', ''), false);
  assert.equal(authorize('/auth/processing/authz', 'POST', 'calculator', ''), true);
  for (const role of ['', 'admin', undefined]) assert.equal(authorize('/auth/processing/authz', 'GET', role, ''), false);
  assert.equal(authorize('/other', 'GET', 'calculator', ''), false);
});
test('MCP JSON, batches, unknown tools and methods are checked', () => {
  const call = name => JSON.stringify({jsonrpc:'2.0',method:'tools/call',params:{name}});
  assert.equal(authorize('/auth/mcp', 'POST', 'viewer', call('echo')), true);
  assert.equal(authorize('/auth/mcp', 'POST', 'viewer', call('add')), false);
  assert.equal(authorize('/auth/mcp', 'POST', 'calculator', call('add')), true);
  for (const body of ['{', '[]', 'null', call('unknown'), '{"jsonrpc":"2.0","method":"unknown"}']) {
    assert.equal(authorize('/auth/mcp', 'POST', 'calculator', body), false);
  }
});
test('HTTP service copies only its decision marker and rejects excessive body', async () => {
  const server = createServer(); await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const url=`http://127.0.0.1:${server.address().port}`;
  try {
    const allowed = await fetch(url+'/auth/processing/authz',{headers:{'x-authz-role':'viewer'}});
    assert.equal(allowed.status,200); assert.equal(allowed.headers.get('x-policy-winner'),'external-authz');
    assert.equal((await fetch(url+'/auth/processing/authz')).status,403);
    assert.equal((await fetch(url+'/auth/processing/authz',{method:'POST',body:'x'.repeat(1025)})).status,413);
  } finally { await new Promise(r=>server.close(r)); }
});
