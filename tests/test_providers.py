"""Tests for the Ollama provider against a fake Ollama server.

A tiny HTTP server on a random local port imitates the two Ollama endpoints
the provider uses, so these tests run without Ollama installed.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alter_ego.providers import PROVIDER_LABELS, create_provider  # noqa: E402
from alter_ego.providers.base import ChatMessage, ProviderError  # noqa: E402
from alter_ego.providers import https  # noqa: E402
from alter_ego.providers.claude_code import ClaudeCodeProvider  # noqa: E402
from alter_ego.providers.ollama import OllamaProvider  # noqa: E402
from alter_ego.providers.ollama_server import NOT_INSTALLED_MESSAGE, OllamaServer, find_command, is_local  # noqa: E402
from alter_ego.providers.openai_compat import OpenAICompatibleProvider  # noqa: E402
from alter_ego.settings.config import Config  # noqa: E402

FAKE_CLAUDE = [sys.executable, str(Path(__file__).resolve().parent / "fake_claude.py")]
FAKE_OLLAMA = [sys.executable, str(Path(__file__).resolve().parent / "fake_ollama.py")]

MODELS = ["llama3.2:latest", "qwen2.5:3b"]
REPLY_PIECES = ["[shy]", " Hel", "lo ", "there."]


class FakeOllamaHandler(BaseHTTPRequestHandler):
    received: list[dict] = []
    models: list[str] = MODELS   # /api/tags answers with these; a pull adds to them
    pulled: list[str] = []

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
            self._send_json(200, {"models": [{"name": name} for name in FakeOllamaHandler.models]})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        FakeOllamaHandler.received.append(request)

        if self.path == "/api/pull":
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            if request.get("name") == "broken":
                self.wfile.write((json.dumps({"error": "pull model manifest: file does not exist"}) + "\n").encode())
                return
            for status in ({"status": "pulling manifest"}, {"status": "pulling abc", "total": 200, "completed": 50},
                           {"status": "pulling abc", "total": 200, "completed": 200}, {"status": "success"}):
                self.wfile.write((json.dumps(status) + "\n").encode())
                self.wfile.flush()
            FakeOllamaHandler.pulled.append(request["name"])
            FakeOllamaHandler.models = FakeOllamaHandler.models + [request["name"] + ":latest"]
            return
        if self.path != "/api/chat":
            self._send_json(404, {"error": "not found"})
            return
        if request.get("model") not in FakeOllamaHandler.models:
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
        FakeOllamaHandler.pulled.clear()
        FakeOllamaHandler.models = MODELS
        self.provider = OllamaProvider(self.base_url + "/")  # trailing slash is tolerated

    def test_prepare_pulls_the_default_model_only_when_nothing_is_installed(self):
        progress = []
        self.provider.prepare(progress.append)  # Two models installed: nothing to do, server already answers.
        self.assertEqual(FakeOllamaHandler.pulled, [])
        self.assertEqual(progress, [])

        FakeOllamaHandler.models = []
        provider = OllamaProvider(self.base_url, auto_pull=True, default_model="llama3.2")
        provider.prepare(progress.append)
        self.assertEqual(FakeOllamaHandler.pulled, ["llama3.2"])
        self.assertTrue(any("llama3.2" in p and "25%" in p for p in progress), progress)
        self.assertTrue(any("100%" in p for p in progress), progress)
        self.assertEqual(progress[-1], "")
        self.assertEqual(provider.list_models(), ["llama3.2:latest"])

        FakeOllamaHandler.models = []
        FakeOllamaHandler.pulled.clear()
        OllamaProvider(self.base_url, auto_pull=False).prepare(progress.append)
        self.assertEqual(FakeOllamaHandler.pulled, [])

    def test_pull_failure_is_explained(self):
        with self.assertRaises(ProviderError) as caught:
            self.provider.pull("broken", lambda _: None)
        self.assertIn("couldn't download 'broken'", str(caught.exception))

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

    def test_dropped_connection_is_explained(self):
        # A server that resets the connection (Ollama stopping or crashing mid-request)
        # raises a bare ConnectionResetError on Windows; it must still reach the user in words.
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)

        def reset_once():
            connection, _ = listener.accept()
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            connection.recv(1024)
            connection.close()  # linger 0: an RST instead of a clean close

        threading.Thread(target=reset_once, daemon=True).start()
        provider = OllamaProvider(f"http://127.0.0.1:{listener.getsockname()[1]}")
        with self.assertRaises(ProviderError) as caught:
            provider.list_models()
        self.assertIn("Ollama", str(caught.exception))


class OllamaServerTests(unittest.TestCase):
    """The supervisor starts a fake `ollama serve`, waits for it, and stops it again."""

    @staticmethod
    def free_port() -> int:
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_helpers(self):
        self.assertTrue(is_local("http://localhost:11434"))
        self.assertTrue(is_local("http://127.0.0.1:5000/"))
        self.assertFalse(is_local("http://192.168.1.20:11434"))
        self.assertEqual(find_command(FAKE_OLLAMA), FAKE_OLLAMA)
        self.assertIsNone(find_command("definitely-not-an-installed-program-xyz"))
        self.assertEqual(find_command(sys.executable), [sys.executable])

    def test_starts_waits_and_stops(self):
        port = self.free_port()
        base_url = f"http://127.0.0.1:{port}"
        server = OllamaServer()
        progress = []
        os.environ["FAKE_OLLAMA_DELAY"] = "0.7"
        try:
            self.assertTrue(server.ensure_running(base_url, FAKE_OLLAMA, progress.append))
        finally:
            os.environ.pop("FAKE_OLLAMA_DELAY", None)
        self.assertTrue(server.started_by_us)
        self.assertEqual(progress, ["Starting Ollama..."])
        self.assertEqual(OllamaProvider(base_url).list_models(), [])
        self.assertFalse(server.ensure_running(base_url, FAKE_OLLAMA))  # already answering: nothing started
        server.stop()
        self.assertFalse(server.started_by_us)
        with self.assertRaises(ProviderError):
            OllamaProvider(base_url).list_models()
        server.stop()  # a second stop is harmless

    def test_not_installed_remote_and_broken(self):
        port = self.free_port()
        server = OllamaServer()
        with self.assertRaises(ProviderError) as caught:
            server.ensure_running(f"http://127.0.0.1:{port}", "definitely-not-an-installed-program-xyz")
        self.assertEqual(str(caught.exception), NOT_INSTALLED_MESSAGE)
        with self.assertRaises(ProviderError) as caught:
            server.ensure_running("http://192.0.2.1:9", FAKE_OLLAMA)  # TEST-NET address: never reachable
        self.assertIn("isn't on this computer", str(caught.exception))
        os.environ["FAKE_OLLAMA_EXIT"] = "1"
        try:
            with self.assertRaises(ProviderError) as caught:
                server.ensure_running(f"http://127.0.0.1:{port}", FAKE_OLLAMA)
        finally:
            os.environ.pop("FAKE_OLLAMA_EXIT", None)
        self.assertIn("stopped again at once", str(caught.exception))
        self.assertFalse(server.started_by_us)

    def test_provider_warm_up_uses_the_supervisor(self):
        port = self.free_port()
        base_url = f"http://127.0.0.1:{port}"
        from alter_ego.providers import ollama_server as shared

        provider = OllamaProvider(base_url, command=FAKE_OLLAMA)
        try:
            provider.warm_up(lambda _: None)
            self.assertTrue(shared.started_by_us)
            self.assertEqual(provider.list_models(), [])
            OllamaProvider(base_url, command=FAKE_OLLAMA, auto_start=False).warm_up(lambda _: None)  # no-op
        finally:
            shared.stop()
        self.assertFalse(shared.started_by_us)


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

    def test_a_tool_used_mid_reply_clears_its_status_when_the_words_go_on(self):
        statuses: list[str] = []
        msgs = [ChatMessage("system", "You are Alter Ego."), ChatMessage("user", "tool-mid")]
        text = "".join(self.provider.stream_reply(msgs, "default", lambda: False, statuses.append))
        self.assertEqual(text, "[happy] Let me look. Found it!")
        self.assertEqual(statuses, ["", "Searching the web...", ""])  # never left on "Searching the web..."

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


class HttpsTests(unittest.TestCase):
    """Downloads check certificates with the system store or certifi, not Python's own list."""

    def test_every_download_uses_the_shared_certificate_check(self):
        from unittest import mock

        with mock.patch("urllib.request.urlopen") as opened:
            https.urlopen("https://example.invalid/voices-v1.0.bin", timeout=5)
        self.assertIs(opened.call_args.kwargs["context"], https.ssl_context())
        self.assertEqual(opened.call_args.kwargs["timeout"], 5)

    def test_falls_back_when_the_optional_packages_are_missing(self):
        import ssl
        from unittest import mock

        with mock.patch.dict(sys.modules, {"truststore": None, "certifi": None}):
            context = https._make_context()
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)


if __name__ == "__main__":
    unittest.main()
