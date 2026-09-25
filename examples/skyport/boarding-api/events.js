'use strict';
// Consumes flight events from the shared RabbitMQ broker and evicts the changed flight from the
// cache, so a gate change shows on the board at once instead of after the 3-minute cache TTL.
//
// On when RABBITMQ_HOST is set (see part 3 of the quickstart), off otherwise, so the app still
// runs anywhere. Credentials are this app's own broker user: it may create and consume queues
// named boarding.* and bind them to the flights.events exchange, and nothing else. It cannot
// declare that exchange (flight-api owns it), so if flight-api has not started yet the bind is
// refused and this retries until the exchange exists.

const EXCHANGE = 'flights.events';
const QUEUE = 'boarding.flight-events';
const BINDING = 'flight.#';
const RETRY_MS = 5000;

function amqpUrl(env) {
  const enc = encodeURIComponent;
  const auth = env.RABBITMQ_USER ? `${enc(env.RABBITMQ_USER)}:${enc(env.RABBITMQ_PASSWORD || '')}@` : '';
  return `amqp://${auth}${env.RABBITMQ_HOST}:${env.RABBITMQ_PORT || 5672}/${enc(env.RABBITMQ_VHOST || 'flights')}`;
}

// Handle one delivered message. Returns the flight that was evicted, or null.
async function handleMessage(msg, store) {
  let event;
  try { event = JSON.parse(msg.content.toString()); } catch { return null; }
  if (!event || typeof event.flight !== 'string') return null;
  await store.del(`boarding:${event.flight}`);
  return event.flight;
}

function startConsumer({ store, env = process.env, connect = (url) => require('amqplib').connect(url), log = console, retryMs = RETRY_MS }) {
  if (!env.RABBITMQ_HOST) return { mode: () => 'off', received: () => 0, close: async () => {} };

  let state = 'connecting';
  let received = 0;
  let conn = null;
  let closed = false;
  let timer = null;

  const retry = (why) => {
    state = 'connecting';
    conn = null;
    if (closed) return;
    log.warn(`events: ${why}; retrying in ${retryMs / 1000}s`);
    timer = setTimeout(run, retryMs);
    if (timer.unref) timer.unref();
  };

  async function run() {
    try {
      conn = await connect(amqpUrl(env));
      // A refused bind closes the channel and, on some brokers, the connection; either way retry.
      conn.on('error', () => {});
      conn.on('close', () => { if (!closed) retry('connection closed'); });
      const ch = await conn.createChannel();
      ch.on('error', () => {});
      await ch.assertQueue(QUEUE, { durable: true });
      await ch.bindQueue(QUEUE, EXCHANGE, BINDING);
      await ch.prefetch(10);
      await ch.consume(QUEUE, async (msg) => {
        if (!msg) return;
        try {
          if (await handleMessage(msg, store)) received++;
          ch.ack(msg);
        } catch (e) {
          ch.nack(msg, false, true);
        }
      });
      state = 'connected';
      log.log(`events: consuming ${QUEUE} (${EXCHANGE} ${BINDING})`);
    } catch (e) {
      const c = conn;
      conn = null;
      if (c) { c.removeAllListeners('close'); c.close().catch(() => {}); }
      retry(e.message || String(e));
    }
  }

  run();
  return {
    mode: () => state,
    received: () => received,
    async close() {
      closed = true;
      clearTimeout(timer);
      if (conn) await conn.close().catch(() => {});
    },
  };
}

module.exports = { startConsumer, handleMessage, amqpUrl, EXCHANGE, QUEUE, BINDING };
