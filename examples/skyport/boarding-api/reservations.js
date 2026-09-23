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

module.exports = { lookupFlight };
