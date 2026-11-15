"""Tests for the Ollama provider against a fake Ollama server.

A tiny HTTP server on a random local port imitates the two Ollama endpoints
the provider uses, so these tests run without Ollama installed.
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alter_ego.providers import PROVIDER_LABELS, create_provider  # noqa: E402
from alter_ego.providers.base import ChatMessage, ProviderError  # noqa: E402
from alter_ego.providers.ollama import OllamaProvider  # noqa: E402
from alter_ego.settings.config import Config  # noqa: E402

MODELS = ["llama3.2:latest", "qwen2.5:3b"]
REPLY_PIECES = ["[shy]", " Hel", "lo ", "there."]


class FakeOllamaHandler(BaseHTTPRequestHandler):
    received: list[dict] = []

    def log_message(self, *args):  # Silence request logging during tests.
        pass

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send_json(200, {"models": [{"name": name} for name in MODELS]})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        FakeOllamaHandler.received.append(request)

        if self.path != "/api/chat":
            self._send_json(404, {"error": "not found"})
            return
        if request.get("model") not in MODELS:
            self._send_json(404, {"error": f"model '{request.get('model')}' not found, try pulling it first"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            for piece in REPLY_PIECES:
                line = {"model": request["model"], "message": {"role": "assistant", "content": piece}, "done": False}
                self.wfile.write((json.dumps(line) + "\n").encode("utf-8"))
                self.wfile.flush()
            done = {"model": request["model"], "message": {"role": "assistant", "content": ""}, "done": True}
            self.wfile.write((json.dumps(done) + "\n").encode("utf-8"))
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # The client cancelled and closed the connection; that is allowed.


class OllamaProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeOllamaHandler.received.clear()
        self.provider = OllamaProvider(self.base_url + "/")  # trailing slash is tolerated

    def test_list_models(self):
        self.assertEqual(self.provider.list_models(), MODELS)
        self.assertIn(self.base_url, self.provider.describe())

    def test_test_connection_summary(self):
        self.assertIn("2 model(s)", self.provider.test_connection())

    def test_stream_reply_pieces_and_request_shape(self):
        messages = [ChatMessage("system", "be nice"), ChatMessage("user", "hi")]
        pieces = list(self.provider.stream_reply(messages, "qwen2.5:3b", lambda: False))
        self.assertEqual(pieces, REPLY_PIECES)

        sent = FakeOllamaHandler.received[0]
        self.assertEqual(sent["model"], "qwen2.5:3b")
        self.assertTrue(sent["stream"])
        self.assertEqual(sent["messages"], [{"role": "system", "content": "be nice"},
                                            {"role": "user", "content": "hi"}])

    def test_cancel_stops_early(self):
        calls = {"n": 0}

        def cancelled():
            calls["n"] += 1
            return calls["n"] > 2

        pieces = list(self.provider.stream_reply([ChatMessage("user", "hi")], MODELS[0], cancelled))
        self.assertLess(len(pieces), len(REPLY_PIECES))

    def test_missing_model_is_explained(self):
        with self.assertRaises(ProviderError) as caught:
            list(self.provider.stream_reply([ChatMessage("user", "hi")], "nope:latest", lambda: False))
        self.assertIn("ollama pull", str(caught.exception))

    def test_server_down_is_explained(self):
        # Port 9 (discard) is almost never listening; connection is refused quickly.
        provider = OllamaProvider("http://127.0.0.1:9")
        with self.assertRaises(ProviderError) as caught:
            provider.list_models()
        self.assertIn("Is it running?", str(caught.exception))


class RegistryTests(unittest.TestCase):
    def test_create_provider(self):
        config = Config(Path("unused.json"), {"ollama": {"base_url": "http://example:1234"}})
        provider = create_provider("ollama", config)
        self.assertIsInstance(provider, OllamaProvider)
        self.assertEqual(provider.base_url, "http://example:1234")
        self.assertIsNone(create_provider("offline", config))
        self.assertIsNone(create_provider("bogus", config))
        self.assertIn("ollama", PROVIDER_LABELS)


if __name__ == "__main__":
    unittest.main()
