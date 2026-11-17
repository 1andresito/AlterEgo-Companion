"""Tests for what the AI can do besides talking: web and file tools, and how providers use them.

Everything runs offline: web pages come from a fake fetch function, Ollama is a
fake HTTP server, Claude Code is the fake script, and files go to a temporary
folder.

Run from the project root with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from alter_ego.app import EngineCache  # noqa: E402
from alter_ego.core.tools import DENIED_MESSAGE, MAX_RESULT_CHARS, ToolBox, page_text, parse_wikipedia  # noqa: E402
from alter_ego.providers import build_toolbox, create_provider  # noqa: E402
import alter_ego.providers.ollama_server  # noqa: E402

# The package exports the shared server object under the same name, so take the module from sys.modules.
ollama_server_module = sys.modules["alter_ego.providers.ollama_server"]
from alter_ego.providers.base import ChatMessage  # noqa: E402
from alter_ego.providers.claude_code import ClaudeCodeProvider  # noqa: E402
from alter_ego.providers.ollama import OllamaProvider  # noqa: E402
from alter_ego.providers.ollama_server import OllamaServer  # noqa: E402
from alter_ego.providers.tools_mcp import ApprovalServer, ask_app, handle  # noqa: E402
from alter_ego.settings.config import Config  # noqa: E402
from alter_ego.tool_approval import ToolApproval  # noqa: E402

FAKE_CLAUDE = [sys.executable, str(Path(__file__).resolve().parent / "fake_claude.py")]

# Signals and threads need an application object; one per test process is enough.
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


def process_events_until(condition, timeout_s: float = 5.0) -> bool:
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class FileToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / "Alter Ego"
        self.asked: list[Path] = []
        self.answer = True

        def approve(folder: Path) -> bool:
            self.asked.append(folder)
            return self.answer

        self.tools = ToolBox(folder=self.folder, internet=False, files=True, approve=approve)

    def tearDown(self):
        self.temp.cleanup()

    def test_write_asks_once_then_writes_inside_the_folder(self):
        result = self.tools.run("write_file", {"path": "notes/hi.txt", "content": "hello"})
        self.assertIn("Saved notes/hi.txt", result)
        self.assertEqual((self.folder / "notes" / "hi.txt").read_text(encoding="utf-8"), "hello")
        self.tools.run("make_folder", {"path": "more"})
        self.assertEqual(self.asked, [self.folder])  # asked once for the whole run
        self.assertIn("hi.txt", self.tools.run("list_files", {"path": "notes"}))
        self.assertEqual(self.tools.run("read_file", {"path": "notes/hi.txt"}), "hello")

    def test_no_means_nothing_is_written_and_not_asked_again_at_once(self):
        self.answer = False
        self.assertEqual(self.tools.run("write_file", {"path": "a.txt", "content": "x"}), DENIED_MESSAGE)
        self.assertEqual(self.tools.run("write_file", {"path": "a.txt", "content": "x"}), DENIED_MESSAGE)
        self.assertEqual(len(self.asked), 1)
        self.assertFalse((self.folder / "a.txt").exists())

    def test_paths_outside_the_folder_are_refused(self):
        outside = Path(self.temp.name) / "secret.txt"
        outside.write_text("private", encoding="utf-8")
        for path in ("../secret.txt", str(outside), "notes/../../secret.txt"):
            self.assertTrue(self.tools.run("read_file", {"path": path}).startswith("Error:"), path)
            self.assertTrue(self.tools.run("write_file", {"path": path, "content": "x"}).startswith("Error:"), path)
        self.assertEqual(outside.read_text(encoding="utf-8"), "private")

    def test_reading_is_capped_and_needs_no_approval(self):
        self.folder.mkdir(parents=True)
        (self.folder / "big.txt").write_text("a" * (MAX_RESULT_CHARS * 3), encoding="utf-8")
        result = self.tools.run("read_file", {"path": "big.txt"})
        self.assertLess(len(result), MAX_RESULT_CHARS + 50)
        self.assertTrue(result.endswith("[...cut short]"))
        self.assertEqual(self.asked, [])

    def test_switched_off_tools_are_not_offered_or_run(self):
        names = {spec["function"]["name"] for spec in self.tools.specs()}
        self.assertEqual(names, {"list_files", "read_file", "write_file", "make_folder"})
        self.assertIn("switched off", self.tools.run("web_search", {"query": "x"}))
        self.assertIn("no tool", self.tools.run("format_disk", {}))
        self.assertIn("not valid JSON", self.tools.run("read_file", "{broken"))


class WebToolTests(unittest.TestCase):
    def test_search_combines_instant_answer_and_wikipedia(self):
        requested: list[str] = []

        def fetch(url: str, data: bytes | None) -> str:
            requested.append(url)
            if "duckduckgo" in url:
                return json.dumps({"Heading": "Tokyo", "AbstractText": "Capital of Japan.",
                                   "AbstractURL": "https://example.org/tokyo"})
            return json.dumps({"query": {"search": [
                {"title": "Tokyo Tower", "snippet": "A <span class=\"searchmatch\">tower</span> &amp; landmark"}]}})

        result = ToolBox(internet=True, files=False, fetch=fetch).run("web_search", {"query": "tokyo"})
        self.assertIn("Capital of Japan.", result)
        self.assertIn("https://en.wikipedia.org/wiki/Tokyo_Tower", result)
        self.assertIn("A tower & landmark", result)
        self.assertEqual(len(requested), 2)

    def test_searxng_server_is_used_when_set(self):
        def fetch(url: str, data: bytes | None) -> str:
            self.assertTrue(url.startswith("http://searx.local/search?"))
            return json.dumps({"results": [{"title": "Hit", "url": "https://hit.example", "content": "text"}]})

        tools = ToolBox(internet=True, files=False, search_url="http://searx.local/", fetch=fetch)
        self.assertIn("https://hit.example", tools.run("web_search", {"query": "q"}))

    def test_page_text_and_url_checks(self):
        page = "<html><head><title>t</title><script>evil()</script></head><body><p>Hello &amp; welcome</p></body></html>"
        self.assertEqual(page_text(page), "Hello & welcome")
        tools = ToolBox(internet=True, files=False, fetch=lambda url, data: page)
        self.assertEqual(tools.run("read_web_page", {"url": "https://x.example"}), "Hello & welcome")
        for bad in ("file:///etc/passwd", "/ yesterday breakfast", "https://"):
            self.assertIn("full web address", tools.run("read_web_page", {"url": bad}))

    def test_network_errors_come_back_as_text(self):
        def fetch(url, data):
            raise OSError("no network")

        self.assertIn("no network", ToolBox(internet=True, files=False, fetch=fetch).run("web_search", {"query": "x"}))

    def test_wikipedia_parsing_skips_empty_titles(self):
        self.assertEqual(parse_wikipedia({"query": {"search": [{"title": ""}]}}), [])


class ToolOllamaHandler(BaseHTTPRequestHandler):
    """Asks for one tool call, then answers in words once it sees the tool's result."""

    requests: list[dict] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        ToolOllamaHandler.requests.append(request)
        if request.get("model") == "old" and request.get("tools"):
            body = json.dumps({"error": "registry.ollama.ai/library/old does not support tools"}).encode()
            self.send_response(400)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.end_headers()
        tool_messages = [m for m in request["messages"] if m["role"] == "tool"]
        if request.get("model") == "texty" and request.get("tools") and not tool_messages:
            written = json.dumps({"name": "write_file", "parameters": {"path": "t.txt", "content": "typed"}})
            lines = [{"message": {"role": "assistant", "content": "[shy] " + written[:9]}, "done": False},
                     {"message": {"role": "assistant", "content": written[9:]}, "done": True}]
        elif request.get("tools") and not tool_messages:
            call = {"function": {"name": "write_file", "arguments": {"path": "hi.txt", "content": "hi"}}}
            lines = [{"message": {"role": "assistant", "content": "[happy] Okay!", "tool_calls": [call]}, "done": True}]
        else:
            said = tool_messages[-1]["content"] if tool_messages else "no tools"
            lines = [{"message": {"role": "assistant", "content": f"Done: {said}"}, "done": True}]
        for line in lines:
            self.wfile.write((json.dumps(line) + "\n").encode())


class OllamaToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ToolOllamaHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        ToolOllamaHandler.requests.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.tools = ToolBox(folder=self.temp.name, internet=False, files=True, approve=lambda _: True)

    def tearDown(self):
        self.temp.cleanup()

    def test_tool_call_runs_and_the_model_continues(self):
        provider = OllamaProvider(self.base_url, auto_start=False, tools=self.tools)
        progress: list[str] = []
        text = "".join(provider.stream_reply([ChatMessage("user", "make a file")], "m", lambda: False, progress.append))
        self.assertTrue(text.startswith("[happy] Okay! Done: Saved hi.txt"), text)
        self.assertEqual((Path(self.temp.name) / "hi.txt").read_text(encoding="utf-8"), "hi")
        self.assertEqual(progress, ["Writing hi.txt...", ""])
        first, second = ToolOllamaHandler.requests
        self.assertEqual(first["options"]["temperature"], 0.6)
        self.assertEqual(second["messages"][-1]["role"], "tool")
        self.assertEqual(second["messages"][-1]["tool_name"], "write_file")

    def test_tool_call_written_as_json_text_is_run_not_shown(self):
        provider = OllamaProvider(self.base_url, auto_start=False, tools=self.tools)
        text = "".join(provider.stream_reply([ChatMessage("user", "make a file")], "texty", lambda: False))
        self.assertEqual(text, "Done: Saved t.txt in the Alter Ego folder.")
        self.assertEqual((Path(self.temp.name) / "t.txt").read_text(encoding="utf-8"), "typed")

    def test_ordinary_text_is_not_held_back(self):
        provider = OllamaProvider(self.base_url, auto_start=False, tools=ToolBox(internet=True, files=False))
        text = "".join(provider.stream_reply([ChatMessage("user", "hi")], "plain", lambda: False))
        self.assertTrue(text.startswith("[happy] Okay! Done: Error: working with files is switched off"), text)

    def test_model_without_tool_support_just_chats(self):
        provider = OllamaProvider(self.base_url, auto_start=False, tools=self.tools)
        text = "".join(provider.stream_reply([ChatMessage("user", "hi")], "old", lambda: False))
        self.assertEqual(text, "Done: no tools")
        "".join(provider.stream_reply([ChatMessage("user", "hi")], "old", lambda: False))
        self.assertNotIn("tools", ToolOllamaHandler.requests[-1])  # remembered: not offered again

    def test_no_tools_when_everything_is_switched_off(self):
        provider = OllamaProvider(self.base_url, auto_start=False, tools=ToolBox(internet=False, files=False))
        "".join(provider.stream_reply([ChatMessage("user", "hi")], "m", lambda: False))
        self.assertNotIn("tools", ToolOllamaHandler.requests[-1])


class ClaudeToolTests(unittest.TestCase):
    def test_internet_and_files_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = ClaudeCodeProvider(command=FAKE_CLAUDE, working_dir=Path(temp) / "cc", internet=True,
                                          files_folder=Path(temp) / "files", approval_address="1234:token")
            args = provider._reply_args("hi", "sys", "default", "id", False)
            self.assertEqual(args[args.index("--tools") + 1], "WebSearch,WebFetch")
            self.assertEqual(args[args.index("--max-turns") + 1], "8")
            allowed = args[args.index("--allowedTools") + 1]
            self.assertIn("mcp__alter_ego__write_file", allowed)
            self.assertNotIn("Bash", allowed)
            config = json.loads(Path(args[args.index("--mcp-config") + 1]).read_text(encoding="utf-8"))
            server = config["mcpServers"]["alter_ego"]
            self.assertIn("--tool-server", server["args"])
            self.assertEqual(server["env"]["ALTER_EGO_APPROVAL"], "1234:token")
            self.assertIn("--strict-mcp-config", args)

    def test_no_tools_is_a_pure_chat(self):
        provider = ClaudeCodeProvider(command=FAKE_CLAUDE)
        args = provider._reply_args("hi", "sys", "default", "id", False)
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertEqual(args[args.index("--max-turns") + 1], "1")
        self.assertNotIn("--allowedTools", args)
        self.assertNotIn("--mcp-config", args)

    def test_registry_passes_the_tool_settings(self):
        config = Config(Path("unused.json"), {"tools": {"internet": False, "files": True}})
        self.assertFalse(create_provider("claude_code", config, approval_address="1:t")._internet)
        self.assertIsNone(create_provider("claude_code", config)._files_folder)  # nobody to approve: no files
        self.assertIsNotNone(create_provider("claude_code", config, approval_address="1:t")._files_folder)
        ollama = create_provider("ollama", config, approve=lambda _: True)
        self.assertEqual([s["function"]["name"] for s in ollama.tools.specs()][0], "list_files")
        self.assertFalse(build_toolbox(config).run("write_file", {"path": "x", "content": ""}).startswith("Saved"))


class ToolServerTests(unittest.TestCase):
    def test_handle_lists_and_calls_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = ToolBox(folder=temp, internet=False, files=True, approve=lambda _: True)
            init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "x"}}, tools)
            self.assertEqual(init["result"]["protocolVersion"], "x")
            self.assertIsNone(handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, tools))
            listed = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, tools)["result"]["tools"]
            self.assertIn("write_file", [tool["name"] for tool in listed])
            called = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "write_file", "arguments": {"path": "a.txt", "content": "z"}}}, tools)
            self.assertIn("Saved a.txt", called["result"]["content"][0]["text"])
            self.assertIn("error", handle({"jsonrpc": "2.0", "id": 4, "method": "nope"}, tools))

    def test_server_process_asks_the_app_over_the_socket(self):
        asked: list[Path] = []
        server = ApprovalServer(lambda folder: asked.append(folder) or True)
        try:
            with tempfile.TemporaryDirectory() as temp:
                env = dict(os.environ, ALTER_EGO_APPROVAL=server.address, ALTER_EGO_FOLDER=temp)
                requests = [
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "write_file", "arguments": {"path": "x.txt", "content": "ok"}}},
                ]
                done = subprocess.run(
                    [sys.executable, str(PROJECT_ROOT / "main.py"), "--tool-server"],
                    input="".join(json.dumps(r) + "\n" for r in requests),
                    capture_output=True, text=True, env=env, timeout=60,
                )
                replies = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
                self.assertEqual([r["id"] for r in replies], [1, 2])
                self.assertIn("Saved x.txt", replies[1]["result"]["content"][0]["text"])
                self.assertEqual((Path(temp) / "x.txt").read_text(encoding="utf-8"), "ok")
                self.assertEqual(asked, [Path(temp)])
        finally:
            server.close()

    def test_wrong_token_or_no_app_means_no(self):
        server = ApprovalServer(lambda folder: True)
        try:
            self.assertTrue(ask_app(server.address, Path("f")))
            self.assertFalse(ask_app(f"{server.port}:wrong", Path("f")))
        finally:
            server.close()
        self.assertFalse(ask_app("1:nothing-listens", Path("f")))


class ToolApprovalTests(unittest.TestCase):
    def test_question_goes_to_the_gui_thread_and_yes_is_remembered(self):
        approval = ToolApproval()
        questions: list[str] = []
        approval._question = lambda folder: questions.append(folder) or True  # instead of the dialog
        answers: list[bool] = []
        worker = threading.Thread(target=lambda: answers.append(approval.ask(Path("folder"))))
        worker.start()
        self.assertTrue(process_events_until(lambda: bool(answers)))
        worker.join()
        self.assertEqual(answers, [True])
        self.assertTrue(approval.ask(Path("folder")))  # remembered: no second question
        self.assertEqual(len(questions), 1)


class OllamaShutdownTests(unittest.TestCase):
    def test_stop_all_stops_every_ollama_on_windows(self):
        commands: list[list[str]] = []
        with mock.patch.object(ollama_server_module, "_run_quietly", commands.append), \
                mock.patch.object(ollama_server_module.sys, "platform", "win32"):
            OllamaServer().stop_all()
        images = [command[-1] for command in commands]
        self.assertEqual(images, ["ollama app.exe", "ollama.exe", "ollama_llama_server.exe"])
        self.assertTrue(all(command[0] == "taskkill" for command in commands))

    def test_stop_all_leaves_a_linux_service_alone(self):
        commands: list[list[str]] = []
        with mock.patch.object(ollama_server_module, "_run_quietly", commands.append), \
                mock.patch.object(ollama_server_module.sys, "platform", "linux"):
            OllamaServer().stop_all()
        self.assertEqual(commands, [])


class ReplyCleanupTests(unittest.TestCase):
    def test_mood_tags_after_a_tool_call_and_markdown_links_are_cleaned(self):
        from alter_ego.core.assistant import clean_reply

        text = clean_reply("Let me look. [happy] Found it: [Python](https://python.org).", final=True)
        self.assertEqual(text, "Let me look. Found it: Python (https://python.org).")
        self.assertEqual(clean_reply("[not a mood] stays", final=True), "[not a mood] stays")


class EngineCacheTests(unittest.TestCase):
    def test_engine_is_kept_until_its_settings_change(self):
        cache = EngineCache()
        builds: list[int] = []

        def build():
            builds.append(1)
            return object()

        first = cache.get("voice", (True, "a"), build)
        self.assertIs(cache.get("voice", (True, "a"), build), first)
        self.assertIsNot(cache.get("voice", (True, "b"), build), first)
        self.assertEqual(len(builds), 2)


if __name__ == "__main__":
    unittest.main()
