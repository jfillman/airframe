"""checkin-api: Skyport check-in counters. Which counters are open for a flight, and which version answered."""
import json
import os
import socket
from http.server import BaseHTTPRequestHandler

VERSION = open(os.path.join(os.path.dirname(__file__), "VERSION")).read().strip()

COUNTERS = {
    "AC123": {"counters": "12-18", "opens": "05:30", "bagDrop": True},
    "WS456": {"counters": "3-6", "opens": "06:10", "bagDrop": True},
    "PD789": {"counters": "22", "opens": "07:00", "bagDrop": False},
}


def lookup(flight):
    info = COUNTERS.get(flight.upper())
    return None if info is None else {"flight": flight.upper(), **info, "version": VERSION}


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client (often a probe that timed out) hung up first; nothing to answer

    def do_GET(self):
        if self.path in ("/", "/healthz"):
            return self._json(200, {"ok": True})
        if self.path == "/api/whoami":
            return self._json(200, {"version": VERSION, "pod": socket.gethostname()})
        if self.path.startswith("/api/checkin/"):
            found = lookup(self.path.rsplit("/", 1)[-1])
            return self._json(200, found) if found else self._json(404, {"error": "unknown flight"})
        return self._json(404, {"error": "not found"})

    def log_message(self, *args):
        pass
