'use strict';
const { createApp } = require('./app');
const { createStore } = require('./store');
const { flightApiLookup } = require('./reservations');
const { startConsumer } = require('./events');

(async () => {
  const store = await createStore();
  const port = process.env.PORT || 8080;
  // FLIGHT_API_URL points at flight-api (e.g. http://flight-api.app-flight-api-dev.svc:8080).
  // Unset, the built-in stand-in answers, so the app still runs anywhere.
  const flightApi = process.env.FLIGHT_API_URL;
  const opts = flightApi ? { lookup: flightApiLookup(flightApi), flights: 'flight-api' } : {};
  // RABBITMQ_HOST set: consume flight events and drop the changed flight from the cache.
  const events = startConsumer({ store });
  const server = createApp({ store, events, ...opts }).listen(port, () => {
    console.log(`boarding-api listening on port ${port} (cache: ${store.mode()}, flights: ${opts.flights || 'built-in'}, events: ${events.mode()})`);
  });
  const stop = () => server.close(() => events.close().then(() => store.close()).then(() => process.exit(0)));
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
})();
