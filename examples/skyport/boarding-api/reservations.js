'use strict';
// Stand-in for the slow upstream system of record. Deterministic per flight code so
// results are stable across pods and restarts; the delay is what makes a cache hit
// visibly different from a miss.

const GATES = ['A1', 'A4', 'B2', 'B7', 'C3', 'C9', 'D5'];
const DESTS = ['YYZ', 'YVR', 'LHR', 'CDG', 'NRT', 'JFK', 'SFO', 'DXB'];

function hash(s) {
  let h = 2166136261;
  for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; }
  return h;
}

async function lookupFlight(code, delayMs = 400) {
  if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
  const h = hash(code);
  return {
    flight: code,
    gate: GATES[h % GATES.length],
    destination: DESTS[(h >> 3) % DESTS.length],
    departs: `${String(6 + (h % 16)).padStart(2, '0')}:${['00', '15', '30', '45'][(h >> 5) % 4]}`,
    capacity: 120 + (h % 60),
    group: 1 + ((h >> 7) % 5),
  };
}

class FlightLookupError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

// The real system of record: flight-api (Spring Boot + Postgres). Same result shape as
// lookupFlight above, plus the live status, so the gate board can use either one.
// A missing flight is a 404 for the caller; anything else (down, slow, malformed) is a 502 -
// never a made-up answer, and never cached (app.js caches only what this returns).
function flightApiLookup(baseUrl, { timeoutMs = 3000, fetchImpl = fetch } = {}) {
  const base = baseUrl.replace(/\/+$/, '');
  return async (code) => {
    let res;
    try {
      res = await fetchImpl(`${base}/api/flights/${encodeURIComponent(code)}`, { signal: AbortSignal.timeout(timeoutMs) });
    } catch (err) {
      throw new FlightLookupError(`flight-api unreachable: ${err.message}`, 502);
    }
    if (res.status === 404) throw new FlightLookupError('no such flight', 404);
    if (!res.ok) throw new FlightLookupError(`flight-api answered ${res.status}`, 502);
    const f = await res.json();
    return {
      flight: f.flight,
      gate: f.gate,
      destination: f.destination,
      departs: f.estimatedDeparture,
      status: f.status,
      delayMinutes: f.delayMinutes,
      capacity: f.capacity,
      group: f.group,
      source: 'flight-api',
    };
  };
}

module.exports = { lookupFlight, flightApiLookup, FlightLookupError };
