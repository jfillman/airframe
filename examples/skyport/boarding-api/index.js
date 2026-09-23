'use strict';
const { createApp } = require('./app');
const { createStore } = require('./store');

(async () => {
  const store = await createStore();
  const port = process.env.PORT || 8080;
  const server = createApp({ store }).listen(port, () => {
    console.log(`boarding-api listening on port ${port} (cache: ${store.mode()})`);
  });
  const stop = () => server.close(() => store.close().then(() => process.exit(0)));
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
})();
