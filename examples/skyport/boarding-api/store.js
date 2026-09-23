'use strict';
// A tiny key/value + counter store with two backends. Redis when REDIS_URL is set;
// otherwise an in-process Map, so the app runs locally and BEFORE a Redis component
// exists. The in-memory fallback is deliberately visible (see mode()): with two
// replicas each pod keeps its own counts, which is exactly the symptom Redis fixes.

function memoryStore() {
  const data = new Map();
  const expiry = new Map();
  const live = (k) => {
    const t = expiry.get(k);
    if (t !== undefined && t <= Date.now()) { data.delete(k); expiry.delete(k); }
    return data.has(k);
  };
  return {
    mode: () => 'memory',
    async get(k) { return live(k) ? data.get(k) : null; },
    async set(k, v, ttlSeconds) {
      data.set(k, v);
      if (ttlSeconds) expiry.set(k, Date.now() + ttlSeconds * 1000);
    },
    async incr(k) {
      const n = (live(k) ? Number(data.get(k)) : 0) + 1;
      data.set(k, String(n));
      return n;
    },
    async close() {},
  };
}

async function redisStore(url) {
  const { createClient } = require('redis');
  const client = createClient({ url, password: process.env.REDIS_PASSWORD || undefined, socket: { reconnectStrategy: (n) => Math.min(n * 200, 2000) } });
  let healthy = false;
  client.on('error', () => { healthy = false; });
  client.on('ready', () => { healthy = true; });
  await client.connect().catch(() => {}); // stay up and keep retrying; mode() reports state
  return {
    mode: () => (healthy ? 'redis' : 'redis-unreachable'),
    get: (k) => client.get(k),
    set: (k, v, ttl) => (ttl ? client.set(k, v, { EX: ttl }) : client.set(k, v)),
    incr: (k) => client.incr(k),
    close: () => client.quit().catch(() => {}),
  };
}

async function createStore(env = process.env) {
  return env.REDIS_URL ? redisStore(env.REDIS_URL) : memoryStore();
}

module.exports = { createStore, memoryStore };
