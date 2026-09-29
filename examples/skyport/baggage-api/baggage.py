"""Baggage state: which carousel a flight's bags are on, and every re-route.

Persisted in MongoDB (Skyport Phase 3 - state used to be an in-process dict, see this repo's
history before this file). Storage goes through a `db`-like object (pymongo's Database, or
mongomock's in tests) passed into the constructor rather than opened here - the same
injectable-dependency pattern events.py's Consumer already uses for its pika connection, so
this stays testable without a real cluster.
"""
import zlib
from datetime import datetime, timezone

# Reroutes are kept newest-N, oldest trimmed - same cap the old in-memory list enforced
# (`del self._reroutes[:-200]`), now applied per-write against the `reroutes` collection instead
# of a capped collection: portable across both a real MongoDB and mongomock (which doesn't
# support capped-collection max-doc-count truncation), and just as correct at this app's traffic
# scale.
MAX_REROUTES = 200


def carousel_for(gate):
    """Concourse letter picks the carousel: A -> 1, B -> 2, C -> 3 ... None if the gate is unusable."""
    if not isinstance(gate, str) or len(gate) < 2 or not gate[0].isalpha() or not gate[1:].isdigit():
        return None
    return ord(gate[0].upper()) - ord("A") + 1


def bag_count(flight):
    """Deterministic 40..159 bags per flight, so the demo is stable across restarts."""
    return 40 + zlib.crc32(flight.encode()) % 120


def connect(uri):
    """Open a real MongoDB connection. pymongo is imported lazily, here only - so `test.sh`
    running against an injected fake `db` (mongomock, see test_baggage.py) never needs the real
    driver's C extensions to be importable, and main.py only pays for the import when a real
    MONGODB_URI is actually configured."""
    import pymongo
    return pymongo.MongoClient(uri).get_default_database()


def _strip(doc):
    """A Mongo document's own `_id` (and, for a reroute, the internal `seq` ordering key) is
    storage bookkeeping, not part of this app's API shape - every caller of flight()/flights()/
    reroutes() expects exactly the same dict shape the old in-memory version returned."""
    doc = dict(doc)
    doc.pop("_id", None)
    doc.pop("seq", None)
    return doc


class BaggageStore:
    def __init__(self, db):
        self._flights = db["flights"]
        self._reroutes = db["reroutes"]
        self._flights.create_index("flight", unique=True)
        self._reroutes.create_index("seq")

    def apply_event(self, event):
        """Apply one flight message. Returns the re-route dict if bags moved, else None."""
        if not isinstance(event, dict) or not isinstance(event.get("flight"), str):
            return None
        flight, gate = event["flight"], event.get("gate")
        carousel = carousel_for(gate)
        if carousel is None:
            return None
        # find_one_and_update's default return_document (BEFORE) is exactly what "first
        # sighting?" needs: None on a fresh upsert-insert, or the flight's pre-update state on a
        # real match - and $setOnInsert never touches an existing document, so a match's
        # returned doc is genuinely still current, not stale. Atomic against a concurrent writer
        # (a second app replica applying the same event) the way the old in-process
        # threading.Lock could only ever be atomic within one process.
        before = self._flights.find_one_and_update(
            {"flight": flight},
            {"$setOnInsert": {"flight": flight, "gate": gate, "carousel": carousel,
                               "bags": bag_count(flight), "reroutes": 0}},
            upsert=True,
        )
        if before is None:
            return None  # first sighting: assigned, nothing to re-route yet
        if str(event.get("type", "")).lower() != "gate_changed" or before["gate"] == gate:
            return None
        move = {"flight": flight, "bags": before["bags"], "from_gate": before["gate"], "to_gate": gate,
                "from_carousel": before["carousel"], "to_carousel": carousel,
                "carousel_changed": before["carousel"] != carousel,
                "at": event.get("occurredAt") or datetime.now(timezone.utc).isoformat()}
        self._flights.update_one({"flight": flight},
                                  {"$set": {"gate": gate, "carousel": carousel}, "$inc": {"reroutes": 1}})
        seq = self._next_seq()
        self._reroutes.insert_one({**move, "seq": seq})
        self._reroutes.delete_many({"seq": {"$lte": seq - MAX_REROUTES}})
        return move

    def _next_seq(self):
        latest = list(self._reroutes.find(sort=[("seq", -1)], limit=1))
        return (latest[0]["seq"] + 1) if latest else 1

    def flight(self, flight):
        doc = self._flights.find_one({"flight": flight})
        return _strip(doc) if doc else None

    def flights(self):
        return [_strip(d) for d in self._flights.find()]

    def reroutes(self, limit=50):
        return [_strip(d) for d in self._reroutes.find(sort=[("seq", -1)], limit=limit)]
