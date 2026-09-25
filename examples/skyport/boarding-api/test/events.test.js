'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { startConsumer, handleMessage, amqpUrl } = require('../events');
const { memoryStore } = require('../store');

const msg = (obj) => ({ content: Buffer.from(typeof obj === 'string' ? obj : JSON.stringify(obj)) });
const quiet = { log() {}, warn() {} };
const until = async (fn) => { for (let i = 0; i < 100 && !fn(); i++) await new Promise((r) => setTimeout(r, 10)); };

test('a flight event evicts that flight from the cache', async () => {
  const store = memoryStore();
  await store.set('boarding:AC123', '{"gate":"A1"}', 180);
  await store.set('boarding:WS410', '{"gate":"B7"}', 180);
  assert.strictEqual(await handleMessage(msg({ flight: 'AC123', type: 'GATE_CHANGED' }), store), 'AC123');
  assert.strictEqual(await store.get('boarding:AC123'), null);
  assert.notStrictEqual(await store.get('boarding:WS410'), null);
});

test('malformed messages are ignored, not fatal', async () => {
  const store = memoryStore();
  assert.strictEqual(await handleMessage(msg('not json'), store), null);
  assert.strictEqual(await handleMessage(msg({ nope: 1 }), store), null);
});

test('the URL carries the vhost and encodes credentials', () => {
  assert.strictEqual(
    amqpUrl({ RABBITMQ_HOST: 'b.ns.svc', RABBITMQ_USER: 'u_ser', RABBITMQ_PASSWORD: 'p@ss/w', RABBITMQ_VHOST: 'flights' }),
    'amqp://u_ser:p%40ss%2Fw@b.ns.svc:5672/flights');
});

test('off without RABBITMQ_HOST', () => {
  const c = startConsumer({ store: memoryStore(), env: {} });
  assert.strictEqual(c.mode(), 'off');
});

function fakeBroker() {
  const b = { handlers: {}, bound: null, acked: 0, consumer: null, failBind: 0 };
  const ch = {
    on() {}, ack() { b.acked++; }, nack() {},
    async assertQueue(q) { b.queue = q; },
    async bindQueue(q, ex, key) { if (b.failBind-- > 0) throw new Error('NOT_FOUND - no exchange'); b.bound = { q, ex, key }; },
    async prefetch() {},
    async consume(q, fn) { b.consumer = fn; },
  };
  b.conn = { on(ev, fn) { b.handlers[ev] = fn; }, removeAllListeners() {}, async createChannel() { return ch; }, async close() { b.closedConn = true; } };
  return b;
}

test('declares its own queue, binds to flights.events, then evicts on delivery', async () => {
  const broker = fakeBroker();
  const store = memoryStore();
  await store.set('boarding:AC123', 'x', 180);
  const c = startConsumer({ store, env: { RABBITMQ_HOST: 'h' }, connect: async () => broker.conn, log: quiet });
  await until(() => c.mode() === 'connected');
  assert.deepStrictEqual(broker.bound, { q: 'boarding.flight-events', ex: 'flights.events', key: 'flight.#' });
  await broker.consumer(msg({ flight: 'AC123' }));
  assert.strictEqual(await store.get('boarding:AC123'), null);
  assert.strictEqual(c.received(), 1);
  assert.strictEqual(broker.acked, 1);
  await c.close();
});

test('retries until the exchange exists (flight-api may not have started yet)', async () => {
  const broker = fakeBroker();
  broker.failBind = 2;
  const c = startConsumer({ store: memoryStore(), env: { RABBITMQ_HOST: 'h' }, connect: async () => broker.conn, log: quiet, retryMs: 10 });
  await until(() => c.mode() === 'connected');
  assert.strictEqual(c.mode(), 'connected');
  await c.close();
});
