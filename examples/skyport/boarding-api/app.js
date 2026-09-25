'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { lookupFlight } = require('./reservations');
const pkg = require('./package.json');

const FLIGHT = /^[A-Z]{2}\d{1,4}$/;
const CACHE_TTL_SECONDS = 180;
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' };

function createApp({ store, version = pkg.version, lookup = lookupFlight, flights = 'built-in', publicDir = path.join(__dirname, 'public') }) {
  const json = (res, code, body, extra = {}) => {
    res.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...extra });
    res.end(JSON.stringify(body));
  };

  async function boardingInfo(code) {
    const key = `boarding:${code}`;
    const started = Date.now();
    const hit = await store.get(key).catch(() => null);
    if (hit) return { ...JSON.parse(hit), cached: true, latencyMs: Date.now() - started };
    const info = await lookup(code);
    await store.set(key, JSON.stringify(info), CACHE_TTL_SECONDS).catch(() => {});
    return { ...info, cached: false, latencyMs: Date.now() - started };
  }

  return http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://x');
    try {
      if (url.pathname === '/healthz') return json(res, 200, { status: 'ok' });

      // Which version/pod answered? The gate board polls this to draw the canary split.
      // Connection: close so a kubectl port-forward (which pins a keep-alive connection to
      // ONE pod) re-picks a pod on every poll instead of showing 100% one version.
      if (url.pathname === '/api/whoami') {
        return json(res, 200, {
          service: 'boarding-api', version, pod: process.env.HOSTNAME || os.hostname(),
          cache: store.mode(), flights,
        }, { Connection: 'close' });
      }

      let m = url.pathname.match(/^\/api\/boarding\/([A-Za-z0-9]+)$/);
      if (m && req.method === 'GET') {
        const code = m[1].toUpperCase();
        if (!FLIGHT.test(code)) return json(res, 400, { error: 'flight code looks like AC123' });
        return json(res, 200, { ...(await boardingInfo(code)), version });
      }

      // Scan a boarding pass: a shared counter. In-memory mode counts per pod (wrong with
      // >1 replica); Redis mode counts once for the whole flight.
      m = url.pathname.match(/^\/api\/boarding\/([A-Za-z0-9]+)\/scan$/);
      if (m && req.method === 'POST') {
        const code = m[1].toUpperCase();
        if (!FLIGHT.test(code)) return json(res, 400, { error: 'flight code looks like AC123' });
        const info = await boardingInfo(code);
        const boarded = await store.incr(`boarded:${code}`);
        return json(res, 200, { flight: code, boarded, capacity: info.capacity, cache: store.mode() });
      }

      if (req.method === 'GET') {
        const file = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        const full = path.join(publicDir, file);
        if (full.startsWith(publicDir) && fs.existsSync(full) && fs.statSync(full).isFile()) {
          res.writeHead(200, { 'Content-Type': TYPES[path.extname(full)] || 'application/octet-stream' });
          return fs.createReadStream(full).pipe(res);
        }
      }
      json(res, 404, { error: 'not found' });
    } catch (err) {
      json(res, err.status || 500, { error: String(err.message || err) });
    }
  });
}

module.exports = { createApp };
