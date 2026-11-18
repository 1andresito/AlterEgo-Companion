"""Ollama provider: local models served by https://ollama.com.

Talks to Ollama's HTTP API with the standard library only, so it adds no
dependency. Three endpoints are used:

  GET  /api/tags   -> installed models
  POST /api/chat   -> chat completion, streamed as one JSON object per line
  POST /api/pull   -> download a model, progress streamed the same way

When the user allowed it (AI -> Allow internet / Let me work with files) the
model is offered the tools in core/tools.py through Ollama's tool calling.

Alter Ego also looks after the server (see ollama_server.py): when Ollama is
chosen it starts `ollama serve` if nothing answers locally, and before the
first reply it can download a default model if none is installed (`auto_pull`,
off by default: the first-run setup asks the user which model to download).
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from typing import Callable, Iterator

from ..core.tools import ToolBox, WrittenCallFilter, progress_text, tool_result_message
from .base import ChatMessage, Provider, ProviderError
from .https import urlopen
from .ollama_server import DEFAULT_COMMAND, direct_url, is_local, ollama_server

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"  # Small, general, about 2 GB: what the README suggests for chatting.
CONNECT_TIMEOUT_S = 10
STREAM_TIMEOUT_S = 120
PULL_TIMEOUT_S = 600  # Between progress lines, not for the whole download.
MAX_TOOL_ROUNDS = 4   # Tool calls in a row before the model must answer in words.
TEMPERATURE = 0.6     # A little below Ollama's 0.8: fewer invented facts, still warm.
KEEP_ALIVE = "30m"    # How long the model stays loaded after a reply; reloading it is what made replies slow.
LOAD_TIMEOUT_S = 120  # Loading a model from disk into memory can take a while on a slow drive.
# Room for the personality, the Danganronpa knowledge and the recent chat (Ollama's default is 4096,
# which cut off the start of the prompt). Loading and chatting must ask for the same size, or the
# first reply reloads the model.
NUM_CTX = 8192
MODEL_OPTIONS = {"temperature": TEMPERATURE, "num_ctx": NUM_CTX}


class OllamaProvider(Provider):
    id = "ollama"
    label = "Ollama (local)"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        command: str | list[str] = DEFAULT_COMMAND,
        auto_start: bool = True,
        auto_pull: bool = False,
        default_model: str = DEFAULT_MODEL,
        tools: ToolBox | None = None,
    ):
        self.base_url = direct_url(base_url.rstrip("/"))  # 127.0.0.1, not localhost: two seconds faster per request
        self.command = command
        self.auto_start = auto_start
        self.auto_pull = auto_pull
        self.default_model = default_model or DEFAULT_MODEL
        self.tools = tools if tools is not None and tools.enabled else None
        self._no_tools: set[str] = set()  # Models that said they cannot use tools.

    def describe(self) -> str:
        return f"Ollama at {self.base_url}"

    @property
    def file_tools(self) -> bool:
        return self.tools is not None and self.tools.files

    @property
    def web_tools(self) -> bool:
        return self.tools is not None and self.tools.internet

    # ----- Getting ready -----

    def warm_up(self, progress: Callable[[str], None]) -> None:
        """Start the local server if nothing answers (only when allowed and only locally)."""
        if self.auto_start and is_local(self.base_url):
            ollama_server.ensure_running(self.base_url, self.command, progress)

    def load_model(self, model: str) -> None:
        """Load the model now: a /api/generate request without a prompt is Ollama's way to do that."""
        response = self._open("POST", "/api/generate", {"model": model, "keep_alive": KEEP_ALIVE, "options": MODEL_OPTIONS},
                              timeout=LOAD_TIMEOUT_S)
        try:
            response.read()
        except OSError as error:
            raise ProviderError(self._lost_connection(error)) from None
        finally:
            response.close()

    def prepare(self, progress: Callable[[str], None]) -> None:
        """Start the server if needed, then download the default model if no model is installed."""
        self.warm_up(progress)
        if self.auto_pull and not self.list_models():
            self.pull(self.default_model, progress)

    def pull(self, model: str, progress: Callable[[str], None]) -> None:
        """Download a model through the server, reporting progress like 'Downloading llama3.2... 43%'."""
        progress(f"Downloading the AI model '{model}' (a few GB, only once)...")
        response = self._open("POST", "/api/pull", {"name": model, "stream": True}, timeout=PULL_TIMEOUT_S)
        try:
            for raw_line in response:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "error" in chunk:
                    raise ProviderError(f"Ollama couldn't download '{model}': {chunk['error']}")
                total, completed = chunk.get("total"), chunk.get("completed")
                if total and completed is not None:
                    progress(f"Downloading the AI model '{model}'... {100 * completed // total}%")
                elif chunk.get("status"):
                    progress(f"Downloading the AI model '{model}'... {chunk['status']}")
        except socket.timeout:
            raise ProviderError(f"The download of '{model}' stalled. Check the internet connection and try again.") from None
        finally:
            response.close()
        progress("")

    def list_models(self) -> list[str]:
        data = self._request_json("GET", "/api/tags", timeout=CONNECT_TIMEOUT_S)
        models = data.get("models", []) if isinstance(data, dict) else []
        return [str(entry.get("name")) for entry in models if entry.get("name")]

    def stream_reply(
        self,
        messages: list[ChatMessage],
        model: str,
        cancelled: Callable[[], bool],
        progress: Callable[[str], None] | None = None,
    ) -> Iterator[str]:
        """Stream the reply; when the model asks for a tool, run it and let the model continue.

        Each round is one /api/chat request. A round that ends with tool calls
        gets the results appended as "tool" messages and is followed by another
        round, at most MAX_TOOL_ROUNDS times, so a confused model cannot loop.
        """
        chat = [{"role": m.role, "content": m.content} for m in messages]
        request = next((m.content for m in reversed(messages) if m.role == "user"), "")
        tools = self.tools.specs(request) if self.tools is not None and model not in self._no_tools else []
        round_number = 0
        words_only = False  # Set when the model wrote only a call it cannot make: one more try, in words.
        while True:
            # The last round, and the try in words, offer no tools: the model must answer.
            offer = tools if round_number < MAX_TOOL_ROUNDS and not words_only else []
            calls: list[dict] = []
            text = ""
            written = WrittenCallFilter()  # Tool calls typed into the reply as JSON never reach the chat.
            try:
                for piece, call in self._stream_round(chat, model, offer, cancelled):
                    if call is not None:
                        calls.append(call)
                        continue
                    shown = written.feed(piece)
                    if shown:
                        text += shown
                        yield shown
                rest = written.flush()
                if rest:
                    text += rest
                    yield rest
            except ProviderError as error:
                if offer and "does not support tools" in str(error):
                    # Older or tiny models cannot use tools; remember that and just chat.
                    print(f"Alter Ego: the Ollama model '{model}' can't use tools; chatting without them.")
                    self._no_tools.add(model)
                    tools = []
                    continue
                raise
            if cancelled():
                return
            if not calls:
                # A call typed as text counts when it names a tool on offer; anything else (a mood
                # tag such as {"name": "talk"}, or a tool in a round without tools) is only dropped.
                offered = {spec["function"]["name"] for spec in offer}
                calls = [{"function": call} for call in written.calls if call["name"] in offered]
            if not calls:
                if written.calls and not _has_words(text) and not words_only:
                    words_only = True
                    chat.append({"role": "system", "content": WORDS_ONLY})
                    continue
                return
            chat.append({"role": "assistant", "content": text, "tool_calls": calls})
            for call in calls:
                function = call.get("function") or {}
                name = str(function.get("name", ""))
                args = function.get("arguments") or {}
                if progress:
                    progress(progress_text(name, args if isinstance(args, dict) else {}))
                result = self.tools.run(name, args) if self.tools is not None else "Error: no tools."
                chat.append({"role": "tool", "tool_name": name, "content": tool_result_message(name, result)})
            if progress:
                progress("")
            if text and not text[-1].isspace():
                yield " "  # The next round's words follow on from what was already said.
            round_number += 1

    def _stream_round(self, chat: list[dict], model: str, tools: list[dict], cancelled: Callable[[], bool]):
        """One /api/chat request. Yields (text, None) for words and ("", call) for each tool call."""
        payload: dict = {
            "model": model,
            "messages": chat,
            "stream": True,
            "keep_alive": KEEP_ALIVE,
            "options": dict(MODEL_OPTIONS),
        }
        if tools:
            payload["tools"] = tools
        response = self._open("POST", "/api/chat", payload, timeout=STREAM_TIMEOUT_S)
        try:
            # Each line is a complete JSON object; the last one has "done": true.
            for raw_line in response:
                if cancelled():
                    return
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue  # Ignore anything that is not JSON rather than crash.
                if "error" in chunk:
                    raise ProviderError(f"Ollama reported an error: {chunk['error']}")
                message = chunk.get("message") or {}
                for call in message.get("tool_calls") or []:
                    yield "", call
                text = message.get("content", "")
                if text:
                    yield text, None
                if chunk.get("done"):
                    return
        except socket.timeout:
            raise ProviderError("Ollama stopped responding mid-reply (timed out).") from None
        finally:
            response.close()

    # ----- HTTP helpers -----

    def _open(self, method: str, path: str, payload: dict | None, timeout: float):
        url = self.base_url + path
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url, data=body, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            return urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            raise ProviderError(self._explain_http_error(error)) from None
        except urllib.error.URLError as error:
            reason = getattr(error, "reason", error)
            if isinstance(reason, (ConnectionRefusedError, socket.timeout)) or "refused" in str(reason).lower():
                raise ProviderError(
                    f"I can't reach Ollama at {self.base_url}. Is it running? "
                    "Start the Ollama app, or run 'ollama serve'."
                ) from None
            raise ProviderError(f"I couldn't connect to Ollama at {self.base_url}: {reason}") from None
        except socket.timeout:
            raise ProviderError(f"Ollama at {self.base_url} took too long to answer.") from None
        except OSError as error:
            # A server that closes the connection mid-request (stopping, crashing) raises a plain
            # ConnectionResetError on Windows, not a URLError.
            raise ProviderError(self._lost_connection(error)) from None

    def _lost_connection(self, error: OSError) -> str:
        return f"I lost the connection to Ollama at {self.base_url} ({error.strerror or error}). Please try again."

    def _request_json(self, method: str, path: str, timeout: float, payload: dict | None = None):
        response = self._open(method, path, payload, timeout)
        try:
            return json.loads(response.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ProviderError(f"Ollama at {self.base_url} sent a reply I couldn't understand.") from None
        except OSError as error:
            raise ProviderError(self._lost_connection(error)) from None
        finally:
            response.close()

    @staticmethod
    def _explain_http_error(error: urllib.error.HTTPError) -> str:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("error", "")
        except Exception:
            detail = ""
        if "not found" in detail.lower() and "model" in detail.lower():
            return f"Ollama says: {detail}. Install it with 'ollama pull <model>' or pick another model."
        return f"Ollama returned HTTP {error.code}" + (f": {detail}" if detail else ".")


# ----- Tool calls written as text -----
# core/tools.py WrittenCallFilter takes {"name": ..., "parameters": ...} objects out of
# the streamed text; stream_reply runs the ones that name a tool on offer.

_LEADING_TAG = re.compile(r"^\s*\[[a-z]{1,15}\]\s*")
WORDS_ONLY = "Answer the user in plain spoken words now. Do not write JSON or tool calls."


def _has_words(text: str) -> bool:
    return bool(_LEADING_TAG.sub("", text, count=1).strip())
