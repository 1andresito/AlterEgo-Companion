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
from alter_ego.core.assistant import ProviderResponder  # noqa: E402
from alter_ego.core.conversation import Message, Role  # noqa: E402
from alter_ego.core.personality import Personality  # noqa: E402
from alter_ego.core.tools import (  # noqa: E402
    CREATE, DENIED_MESSAGE, FILES_INSTRUCTION, MAKE_FOLDER, MAX_RESULT_CHARS, READ, READ_DENIED_MESSAGE, REPLACE, Access, ToolBox,
    page_text, parse_wikipedia, system_folders, tool_result_message, wants_web,
)
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
from alter_ego.tool_approval import ToolApproval, question_text  # noqa: E402

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
        self.root = Path(self.temp.name).resolve()
        self.folder = self.root / "Alter Ego"
        self.asked: list[Access] = []
        self.answer = True

        def approve(access: Access) -> bool:
            self.asked.append(access)
            return self.answer

        self.approve = approve
        self.tools = ToolBox(folder=self.folder, internet=False, files=True, approve=approve)

    def tearDown(self):
        self.temp.cleanup()

    def test_questions_about_the_world_offer_the_web_but_small_talk_does_not(self):
        for text in ["Can you tell me todays news?", "who won the election?", "what is a black hole?",
                     "whats the capital of Peru", "how tall is the Eiffel Tower?", "tell me about Peru"]:
            self.assertTrue(wants_web(text), text)
        for text in ["hello", "how are you?", "what do you like?", "what's your name?", "whats up",
                     "who are you?", "tell me about yourself", "where is my phone?"]:
            self.assertFalse(wants_web(text), text)

    def test_every_change_is_asked_about(self):
        result = self.tools.run("write_file", {"path": "notes/hi.txt", "content": "hello"})
        target = self.folder / "notes" / "hi.txt"
        self.assertIn(f"Saved {target}", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "hello")
        self.tools.run("write_file", {"path": "notes/hi.txt", "content": "again"})
        self.tools.run("make_folder", {"path": "more"})
        self.assertEqual([(a.kind, a.path) for a in self.asked], [
            (CREATE, target), (REPLACE, target), (MAKE_FOLDER, self.folder / "more")])
        self.assertEqual(self.asked[1].detail, "again")  # the question shows the new content
        self.assertIn("hi.txt", self.tools.run("list_files", {"path": "notes"}))
        self.assertEqual(self.tools.run("read_file", {"path": "notes/hi.txt"}), "again")
        self.assertEqual(len(self.asked), 3)  # reading in the Alter Ego folder is not asked about

    def test_no_means_nothing_is_written_and_not_asked_again_at_once(self):
        self.answer = False
        self.assertEqual(self.tools.run("write_file", {"path": "a.txt", "content": "x"}), DENIED_MESSAGE)
        self.assertEqual(self.tools.run("write_file", {"path": "a.txt", "content": "x"}), DENIED_MESSAGE)
        self.assertEqual(len(self.asked), 1)
        self.assertFalse((self.folder / "a.txt").exists())

    def test_a_full_path_anywhere_works_after_a_yes(self):
        outside = self.root / "elsewhere" / "note.txt"
        self.assertIn("Saved", self.tools.run("write_file", {"path": str(outside), "content": "hi"}))
        self.assertEqual(outside.read_text(encoding="utf-8"), "hi")
        self.assertEqual(self.asked[-1].path, outside)
        relative = self.tools.run("write_file", {"path": "../elsewhere/other.txt", "content": "x"})
        self.assertIn("Saved", relative)
        self.assertEqual(self.asked[-1].path, self.root / "elsewhere" / "other.txt")  # the real place is shown
        if sys.platform == "win32":  # "C:notes.txt" is relative to a drive's current folder: refused, not guessed
            self.assertTrue(self.tools.run("read_file", {"path": "C:notes.txt"}).startswith("Error:"))

    def test_home_folders_are_reached_by_tilde_or_by_name(self):
        home = self.root / "home"
        (home / "Downloads").mkdir(parents=True)
        with mock.patch.object(Path, "home", return_value=home), \
                mock.patch.dict(os.environ, {"USERPROFILE": str(home), "HOME": str(home)}):
            self.assertIn("Saved", self.tools.run("write_file", {"path": "~/Downloads/hello.txt", "content": "a"}))
            self.assertIn("Saved", self.tools.run("write_file", {"path": "downloads/hi.txt", "content": "b"}))
            self.tools.run("write_file", {"path": "Desktop/x.txt", "content": "c"})  # no such home folder here
        self.assertEqual([a.path for a in self.asked], [
            home / "Downloads" / "hello.txt", home / "Downloads" / "hi.txt", self.folder / "Desktop" / "x.txt"])

    def test_reading_outside_the_folder_is_asked_once_per_folder(self):
        secret = self.root / "private" / "secret.txt"
        secret.parent.mkdir()
        (secret.parent / "sub").mkdir()
        secret.write_text("private", encoding="utf-8")
        self.answer = False
        self.assertEqual(self.tools.run("read_file", {"path": str(secret)}), READ_DENIED_MESSAGE)
        self.assertEqual([(a.kind, a.path) for a in self.asked], [(READ, secret.parent)])
        self.answer = True
        self.tools._denied.clear()  # as if the short "no" memory had run out
        self.assertEqual(self.tools.run("read_file", {"path": str(secret)}), "private")
        self.assertIn("secret.txt", self.tools.run("list_files", {"path": str(secret.parent)}))
        self.tools.run("list_files", {"path": str(secret.parent / "sub")})  # subfolders are covered
        self.assertEqual(len(self.asked), 2)

    def test_auto_edit_skips_the_question_but_not_for_protected_places_or_reads(self):
        protected = self.root / "program"
        tools = ToolBox(folder=self.folder, internet=False, files=True, approve=self.approve,
                        auto_edit=True, protected=[protected])
        self.assertIn("Saved", tools.run("write_file", {"path": str(self.root / "free.txt"), "content": "x"}))
        self.assertEqual(self.asked, [])
        self.answer = False
        self.assertEqual(tools.run("write_file", {"path": str(protected / "settings.json"), "content": "x"}),
                         DENIED_MESSAGE)
        self.assertFalse((protected / "settings.json").exists())
        self.assertEqual(tools.run("read_file", {"path": str(self.root / "free.txt")}), READ_DENIED_MESSAGE)
        self.assertEqual([a.kind for a in self.asked], [CREATE, READ])
        self.assertTrue(any(tools.is_protected(folder) for folder in system_folders()))

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
        self.assertEqual(len(requested), 3)  # the instant answer, the search, the top pages' openings

    def test_top_results_carry_their_opening_paragraph(self):
        def fetch(url: str, data: bytes | None) -> str:
            if "duckduckgo" in url:
                return "{}"
            if "prop=extracts" in url:
                return json.dumps({"query": {"pages": [
                    {"title": "2026 FIFA World Cup", "extract": "It ended on July 19 with Spain winning."}]}})
            return json.dumps({"query": {"search": [{"title": "2026 FIFA World Cup", "snippet": "The 23rd World Cup"}]}})

        result = ToolBox(internet=True, files=False, fetch=fetch).run("web_search", {"query": "2026 world cup winner"})
        self.assertIn("Spain winning", result)

    def test_news_comes_from_the_current_events_pages(self):
        day_page = (
            "{{Current events|year=2026}}\n<!-- All news items below this line -->\n"
            "\'\'\'Armed conflicts and attacks\'\'\'\n*[[Some war]]\n"
            "**A [[ceasefire]] is agreed in [[Ruritania|the Kingdom]]. [https://apnews.com/x (AP)]\n"
            "\'\'\'Sports\'\'\'\n*[[Spain national team|Spain]] wins the cup. [https://bbc.com/y (BBC)]\n"
        )
        requested: list[str] = []

        def fetch(url: str, data: bytes | None) -> str:
            requested.append(url)
            return json.dumps({"parse": {"wikitext": day_page}})

        tools = ToolBox(internet=True, files=False, fetch=fetch)
        news = tools.run("web_search", {"query": "news today"})
        self.assertIn("Current events", news)
        self.assertIn("- Armed conflicts and attacks: A ceasefire is agreed in the Kingdom. (AP)", news)
        self.assertIn("- Sports: Spain wins the cup. (BBC)", news)
        self.assertNotIn("Some war", news)  # only the items that cite a source, not the story names
        self.assertEqual(len(requested), 1)  # today's page was enough
        self.assertIn("Portal%3ACurrent+events", requested[0])
        about = tools.run("web_search", {"query": "latest news about Spain"})
        self.assertIn("Spain wins the cup", about)
        self.assertNotIn("ceasefire", about)

    def test_weather_comes_from_wttr_in(self):
        weather = {
            "current_condition": [{"temp_C": "29", "temp_F": "84", "FeelsLikeC": "31", "humidity": "58",
                                   "windspeedKmph": "15", "weatherDesc": [{"value": "Partly Cloudy"}]}],
            "nearest_area": [{"areaName": [{"value": "Lima"}], "country": [{"value": "Peru"}]}],
            "weather": [{"date": "2026-11-18", "mintempC": "23", "maxtempC": "29",
                         "hourly": [{"weatherDesc": [{"value": "Sunny"}]}] * 8}],
        }
        requested: list[str] = []

        def fetch(url: str, data: bytes | None) -> str:
            requested.append(url)
            return json.dumps(weather)

        result = ToolBox(internet=True, files=False, fetch=fetch).run(
            "web_search", {"query": "what's the weather like in Lima today?"})
        self.assertEqual(requested, ["https://wttr.in/Lima?format=j1"])
        self.assertIn("Weather for Lima, Peru", result)
        self.assertIn("29°C (84°F)", result)
        self.assertIn("2026-11-18: 23 to 29°C, Sunny", result)

    def test_arguments_wrapped_in_the_call_shape_are_unwrapped(self):
        asked: list[str] = []

        def fetch(url: str, data: bytes | None) -> str:
            asked.append(url)
            return json.dumps({"query": {"search": []}})

        tools = ToolBox(internet=True, files=False, fetch=fetch)
        wrapped = {"type": "function", "function": "web_search", "parameters": {"query": "tokyo tower"}}
        self.assertNotIn("no search words", tools.run("web_search", wrapped))
        self.assertTrue(any("tokyo+tower" in url for url in asked), asked)

    def test_web_results_tell_the_model_to_answer_from_them(self):
        framed = tool_result_message("web_search", "Weather for Lima: 29°C")
        self.assertIn("Weather for Lima: 29°C", framed)
        self.assertIn("Answer the user's question from these results", framed)
        self.assertEqual(tool_result_message("web_search", "Error: down"), "Error: down")
        self.assertEqual(tool_result_message("read_file", "file text"), "file text")

    def test_news_or_weather_that_cannot_be_reached_falls_back_to_the_search(self):
        def fetch(url: str, data: bytes | None) -> str:
            if "wttr.in" in url or "action=parse" in url:
                raise OSError("down")
            return json.dumps({"query": {"search": [{"title": "Lima", "snippet": "Capital of Peru"}]}})

        tools = ToolBox(internet=True, files=False, fetch=fetch)
        self.assertIn("Capital of Peru", tools.run("web_search", {"query": "Lima weather"}))
        self.assertIn("Capital of Peru", tools.run("web_search", {"query": "Lima news"}))

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
        elif request.get("model") == "midtext" and request.get("tools") and not tool_messages:
            written = json.dumps({"name": "read_file", "parameters": {"path": "talent.txt"}})
            lines = [{"message": {"role": "assistant", "content": "Sure! Let me check. " + written[:20]}, "done": False},
                     {"message": {"role": "assistant", "content": written[20:]}, "done": True}]
        elif request.get("model") == "openaiish" and request.get("tools") and not tool_messages:
            written = json.dumps({"type": "function", "function": {"name": "read_file", "parameters": {"path": "x.txt"}}})
            lines = [{"message": {"role": "assistant", "content": written[:30]}, "done": False},
                     {"message": {"role": "assistant", "content": written[30:]}, "done": True}]
        elif request.get("model") == "talky":
            asked_for_words = request["messages"][-1]["role"] == "system"
            content = "[happy] Hello there!" if asked_for_words else '[talk] {"name": "talk", "parameters": {}}'
            lines = [{"message": {"role": "assistant", "content": content}, "done": True}]
        elif request.get("model") == "stubborn":
            written = json.dumps({"name": "read_file", "parameters": {"path": "x.txt"}})
            lines = [{"message": {"role": "assistant", "content": "Hmm. " + written}, "done": True}]
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
        saved = (Path(self.temp.name) / "hi.txt").resolve()
        self.assertTrue(text.startswith(f"[happy] Okay! Done: Saved {saved}"), text)
        self.assertEqual((Path(self.temp.name) / "hi.txt").read_text(encoding="utf-8"), "hi")
        self.assertEqual(progress, ["Writing hi.txt...", ""])
        first, second = ToolOllamaHandler.requests
        self.assertEqual(first["options"]["temperature"], 0.6)
        self.assertEqual(second["messages"][-1]["role"], "tool")
        self.assertEqual(second["messages"][-1]["tool_name"], "write_file")

    def test_tool_call_written_as_json_text_is_run_not_shown(self):
        provider = OllamaProvider(self.base_url, auto_start=False, tools=self.tools)
        text = "".join(provider.stream_reply([ChatMessage("user", "make a file")], "texty", lambda: False))
        self.assertEqual(text, f"[shy] Done: Saved {(Path(self.temp.name) / 't.txt').resolve()}.")
        self.assertEqual((Path(self.temp.name) / "t.txt").read_text(encoding="utf-8"), "typed")

    def test_a_call_written_mid_sentence_is_run_and_not_shown(self):
        provider = OllamaProvider(self.base_url, auto_start=False, tools=self.tools)
        text = "".join(provider.stream_reply([ChatMessage("user", "check the talent.txt file")], "midtext", lambda: False))
        self.assertTrue(text.startswith("Sure! Let me check. Done: There is no file"), text)
        self.assertNotIn("{", text)
        self.assertEqual(ToolOllamaHandler.requests[1]["messages"][-1]["tool_name"], "read_file")

    def test_a_call_written_in_openai_shape_is_run_and_not_shown(self):
        provider = OllamaProvider(self.base_url, auto_start=False, tools=self.tools)
        text = "".join(provider.stream_reply([ChatMessage("user", "read the file x.txt")], "openaiish", lambda: False))
        self.assertTrue(text.startswith("Done: There is no file"), text)
        self.assertEqual(ToolOllamaHandler.requests[1]["messages"][-1]["tool_name"], "read_file")

    def test_a_call_naming_no_tool_is_dropped_and_the_model_answers_in_words(self):
        provider = OllamaProvider(self.base_url, auto_start=False, tools=self.tools)
        text = "".join(provider.stream_reply([ChatMessage("user", "hello")], "talky", lambda: False))
        self.assertNotIn("{", text)
        self.assertIn("Hello there!", text)
        self.assertNotIn("tools", ToolOllamaHandler.requests[-1])  # the try in words offers no tools

    def test_json_in_the_last_round_never_reaches_the_chat(self):
        provider = OllamaProvider(self.base_url, auto_start=False, tools=self.tools)
        text = "".join(provider.stream_reply([ChatMessage("user", "read the file x.txt")], "stubborn", lambda: False))
        self.assertNotIn("{", text)
        self.assertTrue(text.startswith("Hmm."), text)
        self.assertEqual(len(ToolOllamaHandler.requests), 5)  # four tool rounds, then one without tools

    def test_load_and_chat_ask_for_the_same_context_size(self):
        provider = OllamaProvider(self.base_url, auto_start=False)
        provider.load_model("m")
        "".join(provider.stream_reply([ChatMessage("user", "hi")], "m", lambda: False))
        load, chat = ToolOllamaHandler.requests
        self.assertEqual(load["options"]["num_ctx"], chat["options"]["num_ctx"])
        self.assertGreaterEqual(chat["options"]["num_ctx"], 8192)

    def test_ordinary_text_is_not_held_back(self):
        provider = OllamaProvider(self.base_url, auto_start=False, tools=ToolBox(internet=True, files=False))
        text = "".join(provider.stream_reply([ChatMessage("user", "search the news")], "plain", lambda: False))
        self.assertTrue(text.startswith("[happy] Okay! Done: Error: working with files is switched off"), text)

    def test_tools_are_offered_only_when_the_message_is_about_them(self):
        story = Personality.load(PROJECT_ROOT / "assets" / "personality" / "alter_ego.json").knowledge.mentions
        provider = OllamaProvider(self.base_url, auto_start=False, tools=ToolBox(internet=True, files=True, story=story))
        offered = []
        for text in ("hello", "Who is Mondo?", "what's the weather today?", "save this in notes.txt"):
            "".join(provider.stream_reply([ChatMessage("user", text)], "plain", lambda: False))
            offered.append(sorted({spec["function"]["name"].split("_")[0] for spec in ToolOllamaHandler.requests[-1].get("tools", [])}))
            ToolOllamaHandler.requests.clear()
        # A small model offered tools uses them for anything (a web page to answer "hello").
        self.assertEqual(offered[:2], [[], []])
        self.assertEqual(offered[2], ["read", "web"])
        self.assertEqual(offered[3], ["list", "make", "read", "write"])

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
                                          files_folder=Path(temp) / "files", approval_address="1234:token",
                                          protected=[Path(temp) / "a", Path(temp) / "b"])
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
            self.assertEqual(server["env"]["ALTER_EGO_AUTO_EDIT"], "")  # off unless the user switched it on
            self.assertEqual(server["env"]["ALTER_EGO_PROTECTED"].split(os.pathsep),
                             [str(Path(temp) / "a"), str(Path(temp) / "b")])
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
        # The prompt tells the model it may write anywhere, but only while it really has the file tools.
        self.assertTrue(ollama.file_tools)
        about_files = [Message(Role.USER, "put a note in my Downloads folder")]
        prompt = ProviderResponder(ollama, config).build_messages(Personality.default(), about_files)[0].content
        self.assertIn(FILES_INSTRUCTION, prompt)
        chat = [Message(Role.USER, "who is Mondo?")]
        self.assertNotIn(FILES_INSTRUCTION, ProviderResponder(ollama, config).build_messages(Personality.default(), chat)[0].content)
        self.assertTrue(create_provider("claude_code", config, approval_address="1:t").file_tools)
        off = Config(Path("unused.json"), {"tools": {"internet": True, "files": False}})
        off_provider = create_provider("ollama", off, approve=lambda _: True)
        self.assertNotIn(FILES_INSTRUCTION,
                         ProviderResponder(off_provider, off).build_messages(Personality.default(), about_files)[0].content)
        self.assertFalse(build_toolbox(config).auto_edit)  # auto-edit is off unless switched on
        self.assertFalse(create_provider("claude_code", config, approval_address="1:t")._auto_edit)
        on = Config(Path("unused.json"), {"tools": {"files": True, "auto_edit": True}})
        self.assertTrue(build_toolbox(on).auto_edit)
        self.assertTrue(build_toolbox(on).is_protected(build_toolbox(on).protected[-1]))  # Alter Ego's own folders


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
            self.assertIn("a.txt", called["result"]["content"][0]["text"])
            self.assertIn("error", handle({"jsonrpc": "2.0", "id": 4, "method": "nope"}, tools))

    def test_server_process_asks_the_app_over_the_socket(self):
        asked: list[Access] = []
        server = ApprovalServer(lambda access: asked.append(access) or True)
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
                self.assertIn("Saved", replies[1]["result"]["content"][0]["text"])
                self.assertEqual((Path(temp) / "x.txt").read_text(encoding="utf-8"), "ok")
                self.assertEqual([(a.kind, a.path, a.detail) for a in asked],
                                 [(CREATE, (Path(temp) / "x.txt").resolve(), "ok")])
        finally:
            server.close()

    def test_wrong_token_or_no_app_means_no(self):
        server = ApprovalServer(lambda access: True)
        try:
            self.assertTrue(ask_app(server.address, Access(CREATE, Path("f"))))
            self.assertFalse(ask_app(f"{server.port}:wrong", Access(CREATE, Path("f"))))
            self.assertFalse(ask_app(server.address, Access("format_disk", Path("f"))))  # unknown kind: no
        finally:
            server.close()
        self.assertFalse(ask_app("1:nothing-listens", Access(CREATE, Path("f"))))


DIALOG_SCRIPT = """
import sys
from pathlib import Path
from unittest import mock
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from alter_ego.ai_menu import confirm_auto_edit
from alter_ego.core.tools import REPLACE, Access
from alter_ego.tool_approval import ToolApproval

app = QApplication([])
box = ToolApproval()._make_box(Access(REPLACE, Path("notes.txt"), "new"))
print(f"on_top={bool(box.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)}")
print(f"parent={box.parent()}")
print(f"default={'No' if box.defaultButton() is box.button(QMessageBox.StandardButton.No) else 'other'}")
print(f"detail={box.detailedText()}")

def clicking(text):
    def exec_(box):
        next(b for b in box.buttons() if b.text().replace('&', '') == text).click()
        return 0
    return exec_

with mock.patch.object(QMessageBox, "exec", clicking("Yes")):
    print(f"yes={ToolApproval().ask(Access(REPLACE, Path('notes.txt')))}")
with mock.patch.object(QMessageBox, "exec", clicking("Keep asking me")):
    print(f"keep={confirm_auto_edit()}")
with mock.patch.object(QMessageBox, "exec", clicking("Turn it on")):
    print(f"turn_on={confirm_auto_edit()}")
"""


class ToolApprovalTests(unittest.TestCase):
    def test_question_goes_to_the_gui_thread_every_time(self):
        approval = ToolApproval()
        questions: list[Access] = []
        approval._question = lambda access: questions.append(access) or True  # instead of the dialog
        access = Access(REPLACE, Path("notes.txt"), "new text")
        answers: list[bool] = []
        worker = threading.Thread(target=lambda: answers.append(approval.ask(access)))
        worker.start()
        self.assertTrue(process_events_until(lambda: bool(answers)))
        worker.join()
        self.assertEqual(answers, [True])
        self.assertTrue(approval.ask(access))
        self.assertEqual(questions, [access, access])  # asked again: nothing is remembered here

    def test_dialogs_stay_on_top_and_auto_edit_needs_an_explicit_yes(self):
        # Widgets need a QApplication, and this process already has a QCoreApplication: use a child process.
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        done = subprocess.run([sys.executable, "-c", DIALOG_SCRIPT, str(PROJECT_ROOT / "src")],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.split(), ["on_top=True", "parent=None", "default=No", "detail=new",
                                               "yes=True", "keep=False", "turn_on=True"])

    def test_question_names_the_place_and_what_happens(self):
        path = Path("C:/Users/me/notes.txt")
        self.assertIn(str(path), question_text(Access(CREATE, path)))
        self.assertIn("replaced", question_text(Access(REPLACE, path)))
        self.assertIn("folder", question_text(Access(MAKE_FOLDER, path)))
        self.assertIn("goes to the AI", question_text(Access(READ, path)))


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
