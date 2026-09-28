// gate-api: the smallest useful Skyport service. It answers "what's at this gate?" and says which version
// and pod answered, so a canary is visible from the outside.
const os = require('node:os');
const { version } = require('./package.json');

const gates = {
  A12: { flight: 'AC123', to: 'YYZ', status: 'Boarding' },
  A14: { flight: 'WS456', to: 'YYC', status: 'On time' },
  B3: { flight: 'PD789', to: 'YTZ', status: 'Delayed' },
  C7: { flight: 'TS321', to: 'YVR', status: 'Boarding' },
};

function handler(req, res) {
  const url = new URL(req.url, 'http://x');
  const json = (code, body) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(body)); };
  if (url.pathname === '/healthz') return json(200, { ok: true });
  if (url.pathname === '/api/whoami') return json(200, { version, pod: os.hostname() });
  const m = url.pathname.match(/^\/api\/gates\/([A-Z0-9]+)$/);
  if (m) return gates[m[1]] ? json(200, { gate: m[1], ...gates[m[1]], version }) : json(404, { error: `no gate ${m[1]}` });
  if (url.pathname === '/') {
    res.writeHead(200, { 'content-type': 'text/html' });
    return res.end(`<!doctype html><title>gate-api</title><h1>Skyport gates</h1><ul>${Object.entries(gates)
      .map(([g, f]) => `<li>${g}: ${f.flight} to ${f.to}, ${f.status}</li>`).join('')}</ul><p>gate-api ${version} on ${os.hostname()}</p>`);
  }
  json(404, { error: 'not found' });
}

module.exports = { handler, gates };
