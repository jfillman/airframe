'use strict';
const test = require('node:test');
const assert = require('node:assert');
const http = require('node:http');
const { clientCredentials, tokenFromEnv, TokenError } = require('../auth');
const { flightApiLookup } = require('../reservations');

// A stand-in Dex token endpoint: checks Basic auth and the grant, counts calls.
async function withDex(fn, { expiresIn = 3600 } = {}) {
  const state = { calls: 0, fail: false };
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      state.calls++;
      const auth = req.headers.authorization || '';
      const ok = auth === `Basic ${Buffer.from('board-oauth:s3cret').toString('base64')}`;
      if (state.fail || !ok || req.method !== 'POST' || body !== 'grant_type=client_credentials') {
        res.writeHead(state.fail ? 500 : 401); return res.end('{}');
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ access_token: `tok-${state.calls}`, token_type: 'bearer', expires_in: expiresIn }));
    });
  }).listen(0);
  const url = `http://127.0.0.1:${server.address().port}/dex/token`;
  try { await fn(url, state); } finally { server.close(); }
}

test('fetches a client_credentials token with Basic auth', () => withDex(async (tokenUrl, state) => {
  const token = clientCredentials({ tokenUrl, clientId: 'board-oauth', clientSecret: 's3cret' });
  assert.strictEqual(await token(), 'tok-1');
  assert.strictEqual(state.calls, 1);
}));

test('caches the token until shortly before expiry, then refreshes', () => withDex(async (tokenUrl, state) => {
  let t = 1_000_000;
  const token = clientCredentials({ tokenUrl, clientId: 'board-oauth', clientSecret: 's3cret', now: () => t, marginMs: 30_000 });
  assert.strictEqual(await token(), 'tok-1');
  t += 60_000;                                    // 1 minute later: still cached
  assert.strictEqual(await token(), 'tok-1');
  assert.strictEqual(state.calls, 1);
  t += 3600_000 - 60_000 - 30_000;               // inside the 30 s margin before expiry
  assert.strictEqual(await token(), 'tok-2');
  assert.strictEqual(state.calls, 2);
}));

test('concurrent callers share one fetch', () => withDex(async (tokenUrl, state) => {
  const token = clientCredentials({ tokenUrl, clientId: 'board-oauth', clientSecret: 's3cret' });
  const all = await Promise.all([token(), token(), token()]);
  assert.deepStrictEqual(all, ['tok-1', 'tok-1', 'tok-1']);
  assert.strictEqual(state.calls, 1);
}));

test('a refused or failed fetch throws and is not cached', () => withDex(async (tokenUrl, state) => {
  const bad = clientCredentials({ tokenUrl, clientId: 'board-oauth', clientSecret: 'wrong' });
  await assert.rejects(bad(), TokenError);
  state.fail = true;
  const good = clientCredentials({ tokenUrl, clientId: 'board-oauth', clientSecret: 's3cret' });
  await assert.rejects(good(), TokenError);
  state.fail = false;
  assert.match(await good(), /^tok-/);
}));

test('tokenFromEnv is null with no client configured, and refuses a partial one', () => {
  assert.strictEqual(tokenFromEnv({}), null);
  assert.throws(() => tokenFromEnv({ OAUTH_CLIENT_ID: 'x' }), TokenError);
});

// A stand-in flight-api that requires the bearer token.
async function withEnforcingFlightApi(fn) {
  const seen = [];
  const server = http.createServer((req, res) => {
    seen.push(req.headers.authorization);
    if (req.headers.authorization !== 'Bearer good') { res.writeHead(401); return res.end(); }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ flight: 'AC123', gate: 'B7', destination: 'JFK', estimatedDeparture: '09:30',
      status: 'ON_TIME', delayMinutes: 0, capacity: 150, group: 3 }));
  }).listen(0);
  try { await fn(`http://127.0.0.1:${server.address().port}`, seen); } finally { server.close(); }
}

test('the flight-api lookup sends the bearer token', () => withEnforcingFlightApi(async (base, seen) => {
  const f = await flightApiLookup(base, { token: async () => 'good' })('AC123');
  assert.strictEqual(f.gate, 'B7');
  assert.deepStrictEqual(seen, ['Bearer good']);
}));

test('a 401 from flight-api is a 502 and drops the cached token', () => withEnforcingFlightApi(async (base) => {
  let cleared = 0;
  const token = async () => 'stale';
  token.clear = () => { cleared++; };
  await assert.rejects(flightApiLookup(base, { token })('AC123'), (e) => e.status === 502);
  assert.strictEqual(cleared, 1);
}));

test('without a token source the lookup sends no Authorization header', () => withEnforcingFlightApi(async (base, seen) => {
  await assert.rejects(flightApiLookup(base)('AC123'), (e) => e.status === 502);
  assert.deepStrictEqual(seen, [undefined]);
}));

test('a token that cannot be obtained is a 502, without calling flight-api', () => withEnforcingFlightApi(async (base, seen) => {
  const token = async () => { throw new TokenError('down'); };
  await assert.rejects(flightApiLookup(base, { token })('AC123'), (e) => e.status === 502 && /no token/.test(e.message));
  assert.deepStrictEqual(seen, []);
}));
