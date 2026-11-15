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
from alter_ego.providers.claude_code import ClaudeCodeProvider  # noqa: E402
from alter_ego.providers.ollama import OllamaProvider  # noqa: E402
from alter_ego.providers.openai_compat import OpenAICompatibleProvider  # noqa: E402
from alter_ego.settings.config import Config  # noqa: E402

FAKE_CLAUDE = [sys.executable, str(Path(__file__).resolve().parent / "fake_claude.py")]

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


class FakeOpenAIHandler(BaseHTTPRequestHandler):
    """Imitates /models and a streamed /chat/completions (Server-Sent Events)."""

    received: list[dict] = []
    auth_headers: list[str | None] = []

    def log_message(self, *args):
        pass

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeOpenAIHandler.auth_headers.append(self.headers.get("Authorization"))
        if self.headers.get("Authorization") != "Bearer good-key":
            self._send_json(401, {"error": {"message": "Incorrect API key provided"}})
        elif self.path == "/v1/models":
            self._send_json(200, {"data": [{"id": "gpt-b"}, {"id": "gpt-a"}]})
        else:
            self._send_json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        FakeOpenAIHandler.received.append(request)
        if request.get("model") == "missing":
            self._send_json(404, {"error": {"message": "The model `missing` does not exist"}})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            self.wfile.write(b": keep-alive comment\n\n")
            for piece in ["[talk] ", "Hi ", "there."]:
                chunk = {"choices": [{"delta": {"content": piece}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass


class OpenAICompatibleProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAIHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeOpenAIHandler.received.clear()
        self.provider = OpenAICompatibleProvider(self.base_url, api_key="good-key")

    def test_list_models_sorted_and_authenticated(self):
        self.assertEqual(self.provider.list_models(), ["gpt-a", "gpt-b"])
        self.assertEqual(FakeOpenAIHandler.auth_headers[-1], "Bearer good-key")

    def test_bad_key_is_explained(self):
        with self.assertRaises(ProviderError) as caught:
            OpenAICompatibleProvider(self.base_url, api_key="wrong").list_models()
        self.assertIn("401", str(caught.exception))
        self.assertIn("api_key", str(caught.exception))

    def test_stream_reply_parses_sse(self):
        pieces = list(self.provider.stream_reply([ChatMessage("user", "hi")], "gpt-a", lambda: False))
        self.assertEqual(pieces, ["[talk] ", "Hi ", "there."])
        self.assertTrue(FakeOpenAIHandler.received[0]["stream"])
        self.assertEqual(FakeOpenAIHandler.received[0]["messages"], [{"role": "user", "content": "hi"}])

    def test_missing_model_is_explained(self):
        with self.assertRaises(ProviderError) as caught:
            list(self.provider.stream_reply([ChatMessage("user", "hi")], "missing", lambda: False))
        self.assertIn("Pick another model", str(caught.exception))


class ClaudeCodeProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = ClaudeCodeProvider(command=FAKE_CLAUDE)
        self.messages = [ChatMessage("system", "You are Alter Ego."), ChatMessage("user", "hello")]

    def reply(self, text="hello", model="default"):
        msgs = [ChatMessage("system", "You are Alter Ego."), ChatMessage("user", text)]
        return "".join(self.provider.stream_reply(msgs, model, lambda: False))

    def test_models_and_version(self):
        self.assertEqual(self.provider.list_models()[0], "default")
        self.assertIn("9.9.9", self.provider.test_connection())

    def test_streams_reply_with_system_prompt_and_no_tools(self):
        text = self.reply("hello")
        self.assertTrue(text.startswith("[happy] You said: hello"))
        self.assertIn("system=18", text)       # len("You are Alter Ego.") -> the system prompt reached the CLI
        self.assertIn("tools=''", text)
        self.assertIn("resumed=False", text)

    def test_second_message_resumes_session_and_reset_starts_new(self):
        self.reply("one")
        self.assertIn("resumed=True", self.reply("two"))
        self.provider.reset()
        self.assertIn("resumed=False", self.reply("three"))

    def test_model_alias_is_passed(self):
        self.assertIn("model=sonnet", self.reply("hi", model="sonnet"))
        self.assertIn("model=default", self.reply("hi", model="default"))

    def test_not_logged_in_is_explained(self):
        with self.assertRaises(ProviderError) as caught:
            self.reply("fail-auth please")
        self.assertIn("/login", str(caught.exception))

    def test_lost_session_falls_back_to_fresh_one(self):
        self.reply("fail-resume")                       # first call: new session, succeeds
        text = self.reply("fail-resume")                # resume fails -> retried as a new session
        self.assertIn("resumed=False", text)

    def test_missing_command_is_explained(self):
        with self.assertRaises(ProviderError) as caught:
            ClaudeCodeProvider(command="definitely-not-a-real-command-xyz").test_connection()
        self.assertIn("Install Claude Code", str(caught.exception))

    def test_cancel_kills_process(self):
        calls = {"n": 0}

        def cancelled():
            calls["n"] += 1
            return calls["n"] > 1

        pieces = list(self.provider.stream_reply(self.messages, "default", cancelled))
        self.assertLessEqual(len(pieces), 2)


class RegistryTests(unittest.TestCase):
    def test_create_provider(self):
        config = Config(Path("unused.json"), {
            "ollama": {"base_url": "http://example:1234"},
            "openai": {"base_url": "http://example:5678/v1", "api_key": "k"},
            "claude_code": {"command": "claude-custom", "effort": "low"},
        })
        provider = create_provider("ollama", config)
        self.assertIsInstance(provider, OllamaProvider)
        self.assertEqual(provider.base_url, "http://example:1234")

        openai = create_provider("openai", config)
        self.assertIsInstance(openai, OpenAICompatibleProvider)
        self.assertEqual((openai.base_url, openai.api_key), ("http://example:5678/v1", "k"))

        claude = create_provider("claude_code", config)
        self.assertIsInstance(claude, ClaudeCodeProvider)
        self.assertEqual(claude._command, "claude-custom")

        self.assertIsNone(create_provider("offline", config))
        self.assertIsNone(create_provider("bogus", config))
        for provider_id in ("ollama", "claude_code", "openai"):
            self.assertIn(provider_id, PROVIDER_LABELS)


if __name__ == "__main__":
    unittest.main()
