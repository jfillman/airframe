'use strict';
const { createApp } = require('./app');
const { createStore } = require('./store');
const { flightApiLookup } = require('./reservations');

(async () => {
  const store = await createStore();
  const port = process.env.PORT || 8080;
  // FLIGHT_API_URL points at flight-api (e.g. http://flight-api.app-flight-api-dev.svc:8080).
  // Unset, the built-in stand-in answers, so the app still runs anywhere.
  const flightApi = process.env.FLIGHT_API_URL;
  const opts = flightApi ? { lookup: flightApiLookup(flightApi), flights: 'flight-api' } : {};
  const server = createApp({ store, ...opts }).listen(port, () => {
    console.log(`boarding-api listening on port ${port} (cache: ${store.mode()}, flights: ${opts.flights || 'built-in'})`);
  });
  const stop = () => server.close(() => store.close().then(() => process.exit(0)));
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
})();
