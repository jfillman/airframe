import json
import unittest

import mongomock

from baggage import BaggageStore, bag_count, carousel_for
from events import Consumer, amqp_url, handle_body


def msg(flight="AC123", gate="B7", type="GATE_CHANGED", **kw):
    return dict(flight=flight, gate=gate, type=type, detail="x", delayMinutes=0, occurredAt="2026-09-26T00:00:00Z", **kw)


def new_store():
    """A fresh BaggageStore per test, backed by mongomock - not a shared client, so tests never
    see each other's data (the old in-memory version's own per-instance dict gave this for
    free; a real MongoClient would need an explicit per-test database/collection instead)."""
    return BaggageStore(mongomock.MongoClient().db)


class Carousel(unittest.TestCase):
    def test_concourse_letter_picks_carousel(self):
        self.assertEqual([carousel_for("A1"), carousel_for("B7"), carousel_for("c12")], [1, 2, 3])

    def test_unusable_gates(self):
        for g in (None, "", "7", "B", "BB7", 5):
            self.assertIsNone(carousel_for(g), g)

    def test_bag_count_is_stable_and_in_range(self):
        self.assertEqual(bag_count("AC123"), bag_count("AC123"))
        self.assertTrue(all(40 <= bag_count("F%d" % i) < 160 for i in range(200)))


class Store(unittest.TestCase):
    def test_first_event_assigns_without_rerouting(self):
        s = new_store()
        self.assertIsNone(s.apply_event(msg(type="DELAY_CHANGED")))
        self.assertEqual(s.flight("AC123")["carousel"], 2)
        self.assertEqual(s.reroutes(), [])

    def test_gate_change_reroutes_and_records(self):
        s = new_store()
        s.apply_event(msg(gate="B7"))
        move = s.apply_event(msg(gate="C3"))
        self.assertEqual((move["from_carousel"], move["to_carousel"], move["carousel_changed"]), (2, 3, True))
        self.assertEqual(move["bags"], bag_count("AC123"))
        self.assertEqual(s.flight("AC123")["gate"], "C3")
        self.assertEqual(s.flight("AC123")["reroutes"], 1)

    def test_same_concourse_gate_change_keeps_carousel(self):
        s = new_store()
        s.apply_event(msg(gate="B7"))
        self.assertFalse(s.apply_event(msg(gate="B9"))["carousel_changed"])

    def test_duplicate_and_non_gate_events_do_nothing(self):
        s = new_store()
        s.apply_event(msg(gate="B7"))
        self.assertIsNone(s.apply_event(msg(gate="B7")))
        self.assertIsNone(s.apply_event(msg(gate="C1", type="DELAY_CHANGED")))
        self.assertEqual(s.flight("AC123")["gate"], "B7")

    def test_garbage_is_ignored(self):
        s = new_store()
        for bad in (None, 5, {}, {"flight": 1}, {"flight": "X", "gate": "??"}):
            self.assertIsNone(s.apply_event(bad))
        self.assertEqual(s.flights(), [])

    def test_reroutes_newest_first(self):
        s = new_store()
        s.apply_event(msg(gate="A1"))
        for g in ("B1", "C1"):
            s.apply_event(msg(gate=g))
        self.assertEqual([r["to_gate"] for r in s.reroutes()], ["C1", "B1"])


class Events(unittest.TestCase):
    def test_handle_body(self):
        s = new_store()
        handle_body(json.dumps(msg(gate="B7")), s)
        move = handle_body(json.dumps(msg(gate="C3")).encode(), s)
        self.assertEqual(move["to_carousel"], 3)
        self.assertIsNone(handle_body(b"not json", s))
        self.assertIsNone(handle_body(None, s))

    def test_amqp_url_escapes(self):
        u = amqp_url({"RABBITMQ_HOST": "h", "RABBITMQ_USER": "u@x", "RABBITMQ_PASSWORD": "p/w:1"})
        self.assertEqual(u, "amqp://u%40x:p%2Fw%3A1@h:5672/flights")

    def test_off_without_host(self):
        c = Consumer(new_store(), {})
        c.start()
        self.assertEqual(c.state, "off")


if __name__ == "__main__":
    unittest.main()
