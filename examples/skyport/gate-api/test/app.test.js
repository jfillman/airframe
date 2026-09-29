const test = require('node:test');
const assert = require('node:assert');
const http = require('node:http');
const { handler } = require('../app');

const get = (server, path) => new Promise((resolve) => {
  http.get({ port: server.address().port, path }, (res) => {
    let body = ''; res.on('data', (c) => (body += c)); res.on('end', () => resolve({ status: res.statusCode, body }));
  });
});

test('gate-api', async (t) => {
  const server = http.createServer(handler).listen(0);
  t.after(() => server.close());
  await t.test('healthz is ok', async () => assert.strictEqual((await get(server, '/healthz')).status, 200));
  await t.test('a known gate', async () => assert.strictEqual(JSON.parse((await get(server, '/api/gates/A12')).body).flight, 'AC123'));
  await t.test('an unknown gate is a 404', async () => assert.strictEqual((await get(server, '/api/gates/Z9')).status, 404));
  await t.test('whoami reports the version', async () => assert.ok(JSON.parse((await get(server, '/api/whoami')).body).version));
});
