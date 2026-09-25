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

test('whoami reports the event consumer (off by default)', () => withApp(async (base) => {
  const body = await (await fetch(`${base}/api/whoami`)).json();
  assert.strictEqual(body.events, 'off');
  assert.strictEqual(body.eventsReceived, 0);
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

const { flightApiLookup } = require('../reservations');

// A stand-in flight-api: serves AC123, 404s everything else, and can be told to misbehave.
async function withFlightApi(fn) {
  const http = require('node:http');
  let mode = 'ok';
  const server = http.createServer((req, res) => {
    if (mode === 'error') { res.writeHead(500); return res.end(); }
    if (req.url === '/api/flights/AC123') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ flight: 'AC123', gate: 'B7', destination: 'JFK', departs: '09:00',
        estimatedDeparture: '09:30', status: 'DELAYED', delayMinutes: 30, capacity: 150, group: 3 }));
    }
    res.writeHead(404); res.end();
  }).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  try { await fn(base, (m) => { mode = m; }); } finally { server.close(); }
}

test('flight-api lookup maps the response, using the estimated departure', () => withFlightApi(async (base) => {
  const f = await flightApiLookup(base)('AC123');
  assert.deepStrictEqual(f, { flight: 'AC123', gate: 'B7', destination: 'JFK', departs: '09:30', status: 'DELAYED',
    delayMinutes: 30, capacity: 150, group: 3, source: 'flight-api' });
}));

test('an unknown flight is a 404 from boarding-api, not a 500', () => withFlightApi(async (base) => {
  await withApp(async (app) => {
    assert.strictEqual((await fetch(`${app}/api/boarding/AC999`)).status, 404);
  }, { lookup: flightApiLookup(base) });
}));

test('flight-api being down is a 502 and is not cached', () => withFlightApi(async (base, setMode) => {
  await withApp(async (app) => {
    setMode('error');
    assert.strictEqual((await fetch(`${app}/api/boarding/AC123`)).status, 502);
    setMode('ok');
    const r = await (await fetch(`${app}/api/boarding/AC123`)).json();
    assert.strictEqual(r.cached, false);       // the failure left nothing in the cache
    assert.strictEqual(r.gate, 'B7');
    assert.strictEqual(r.source, 'flight-api');
  }, { lookup: flightApiLookup(base) });
}));

test('an unreachable flight-api is a 502', () => withApp(async (app) => {
  assert.strictEqual((await fetch(`${app}/api/boarding/AC123`)).status, 502);
}, { lookup: flightApiLookup('http://127.0.0.1:1', { timeoutMs: 500 }) }));

test('whoami says which flight source is in use', () => withApp(async (base) => {
  assert.strictEqual((await (await fetch(`${base}/api/whoami`)).json()).flights, 'built-in');
}, {}));
