"""Consumes flights.events from the shared broker and feeds the store.

On when RABBITMQ_HOST is set, off otherwise, so the app still runs anywhere. Credentials are this
app's own broker user: it may create and consume queues named baggage.* and bind them to the
flights.events exchange, and nothing else. It cannot declare that exchange (flight-api owns it),
so if flight-api has not started yet the bind is refused and this retries until it exists.
"""
import json
import logging
import threading
import time
from urllib.parse import quote

EXCHANGE = "flights.events"
QUEUE = "baggage.flight-events"
BINDING = "flight.#"
RETRY_S = 5
log = logging.getLogger("events")


def amqp_url(env):
    auth = ""
    if env.get("RABBITMQ_USER"):
        auth = "%s:%s@" % (quote(env["RABBITMQ_USER"], safe=""), quote(env.get("RABBITMQ_PASSWORD", ""), safe=""))
    return "amqp://%s%s:%s/%s" % (auth, env["RABBITMQ_HOST"], env.get("RABBITMQ_PORT", "5672"),
                                  quote(env.get("RABBITMQ_VHOST", "flights"), safe=""))


def handle_body(body, store):
    """One delivered message body. Returns the re-route it caused, or None. Never raises on bad input."""
    try:
        event = json.loads(body)
    except (ValueError, TypeError):
        return None
    return store.apply_event(event)


class Consumer:
    def __init__(self, store, env, connect=None, retry_s=RETRY_S):
        self.store, self.env, self.retry_s = store, env, retry_s
        self.state = "connecting" if env.get("RABBITMQ_HOST") else "off"
        self.received = 0
        self._connect = connect
        self._stop = threading.Event()

    def start(self):
        if self.state == "off":
            return
        threading.Thread(target=self._loop, daemon=True, name="events").start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._run_once()
            except Exception as e:  # refused bind, dropped connection, broker not up yet
                self.state = "connecting"
                log.warning("events: %s; retrying in %ss", e, self.retry_s)
            self._stop.wait(self.retry_s)

    def _run_once(self):
        import pika  # imported lazily so the app and its tests run without a broker client
        conn = (self._connect or pika.BlockingConnection)(pika.URLParameters(amqp_url(self.env)))
        try:
            ch = conn.channel()
            ch.queue_declare(queue=QUEUE, durable=True)
            ch.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key=BINDING)
            ch.basic_qos(prefetch_count=10)
            self.state = "connected"
            log.info("events: consuming %s (%s %s)", QUEUE, EXCHANGE, BINDING)
            for method, _props, body in ch.consume(QUEUE, inactivity_timeout=1):
                if self._stop.is_set():
                    break
                if method is None:
                    continue
                handle_body(body, self.store)
                self.received += 1
                ch.basic_ack(method.delivery_tag)
        finally:
            try:
                conn.close()
            except Exception:
                pass
