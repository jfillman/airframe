import json
import logging
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from baggage import BaggageStore, connect
from events import Consumer

PORT = int(os.environ.get("PORT", 8080))
VERSION = os.environ.get("APP_VERSION", "dev")
MONGODB_URI = os.environ.get("MONGODB_URI")
if not MONGODB_URI:
    # No silent in-memory fallback in a real deployment (Skyport Phase 3): every live env
    # declares a mongodb component and wires MONGODB_URI via fromComponent (see cicd.yaml's own
    # docs and this app's platform/envs/*.yaml) - a missing value here means the component or
    # the env wiring is actually broken, not that persistence is optional.
    print("MONGODB_URI is not set - this app requires a MongoDB component (see cicd.yaml)", file=sys.stderr)
    sys.exit(1)
STORE = BaggageStore(connect(MONGODB_URI))
CONSUMER = Consumer(STORE, os.environ)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/healthz":
            return self._json(200, {"status": "ok"})
        if path == "/api/whoami":
            return self._json(200, {"app": "baggage-api", "version": VERSION, "pod": socket.gethostname()})
        if path == "/api/events/status":
            return self._json(200, {"mode": CONSUMER.state, "received": CONSUMER.received})
        if path == "/api/reroutes":
            return self._json(200, STORE.reroutes())
        if path == "/api/bags":
            return self._json(200, STORE.flights())
        if path.startswith("/api/bags/"):
            f = STORE.flight(path[len("/api/bags/"):].upper())
            return self._json(200, f) if f else self._json(404, {"error": "no bags seen for that flight yet"})
        self._json(200, {"app": "baggage-api", "endpoints": ["/api/bags", "/api/bags/{flight}", "/api/reroutes",
                                                            "/api/events/status", "/api/whoami", "/healthz"]})

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    CONSUMER.start()
    print("baggage-api listening on port {}".format(PORT), flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()