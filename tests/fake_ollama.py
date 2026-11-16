"""A stand-in for the `ollama` command, used by the tests.

`fake_ollama.py serve` runs a tiny HTTP server that answers /api/tags with no
models on the host:port given by OLLAMA_HOST (Ollama's own convention), after
an optional delay from FAKE_OLLAMA_DELAY, so the tests can check that Alter Ego
starts the server, waits for it, and stops it again. `FAKE_OLLAMA_EXIT=1` makes
it exit at once, like an install that is broken.
"""

from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"models": []}).encode()
        self.send_response(200 if self.path == "/api/tags" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "serve":
        return 2
    if os.environ.get("FAKE_OLLAMA_EXIT"):
        return 1
    time.sleep(float(os.environ.get("FAKE_OLLAMA_DELAY", "0")))
    host, _, port = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").partition(":")
    server = HTTPServer((host or "127.0.0.1", int(port or 11434)), Handler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
