'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { createApp } = require('../app');
const { memoryStore } = require('../store');

async function withApp(fn, opts = {}) {
  let calls = 0;
  const lookup = async (code) => { calls++; return { flight: code, gate: 'A1', destination: 'YYZ', departs: '09:00', capacity: 150, group: 1 }; };
  const server = createApp({ store: memoryStore(), lookup, version: '9.9.9', ...opts }).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  try { await fn(base, () => calls); } finally { server.close(); }
}

test('healthz', () => withApp(async (base) => {
  assert.deepStrictEqual(await (await fetch(`${base}/healthz`)).json(), { status: 'ok' });
}));

test('whoami reports version and cache mode', () => withApp(async (base) => {
  const body = await (await fetch(`${base}/api/whoami`)).json();
  assert.strictEqual(body.version, '9.9.9');
  assert.strictEqual(body.cache, 'memory');
}));

test('second lookup is served from cache without calling reservations', () => withApp(async (base, calls) => {
  const a = await (await fetch(`${base}/api/boarding/ac123`)).json();
  const b = await (await fetch(`${base}/api/boarding/AC123`)).json();
  assert.strictEqual(a.cached, false);
  assert.strictEqual(b.cached, true);
  assert.strictEqual(calls(), 1);
}));

test('scan increments the boarded counter', () => withApp(async (base) => {
  await fetch(`${base}/api/boarding/AC123/scan`, { method: 'POST' });
  const r = await (await fetch(`${base}/api/boarding/AC123/scan`, { method: 'POST' })).json();
  assert.strictEqual(r.boarded, 2);
  assert.strictEqual(r.capacity, 150);
}));

test('rejects a malformed flight code', () => withApp(async (base) => {
  assert.strictEqual((await fetch(`${base}/api/boarding/nope`)).status, 400);
}));

test('serves the gate board', () => withApp(async (base) => {
  const r = await fetch(`${base}/`);
  assert.strictEqual(r.status, 200);
  assert.match(await r.text(), /Gate board/);
}));
