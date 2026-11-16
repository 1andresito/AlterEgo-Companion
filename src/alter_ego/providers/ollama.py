"""Ollama provider: local models served by https://ollama.com.

Talks to Ollama's HTTP API with the standard library only, so it adds no
dependency. Three endpoints are used:

  GET  /api/tags   -> installed models
  POST /api/chat   -> chat completion, streamed as one JSON object per line
  POST /api/pull   -> download a model, progress streamed the same way

Alter Ego also looks after the server (see ollama_server.py): when Ollama is
chosen it starts `ollama serve` if nothing answers locally, and before the
first reply it downloads a default model if none is installed, so a fresh
Ollama install works without a terminal.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Callable, Iterator

from .base import ChatMessage, Provider, ProviderError
from .ollama_server import DEFAULT_COMMAND, is_local, ollama_server

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"  # Small, general, about 2 GB: what the README suggests for chatting.
CONNECT_TIMEOUT_S = 10
STREAM_TIMEOUT_S = 120
PULL_TIMEOUT_S = 600  # Between progress lines, not for the whole download.


class OllamaProvider(Provider):
    id = "ollama"
    label = "Ollama (local)"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        command: str | list[str] = DEFAULT_COMMAND,
        auto_start: bool = True,
        auto_pull: bool = True,
        default_model: str = DEFAULT_MODEL,
    ):
        self.base_url = base_url.rstrip("/")
        self.command = command
        self.auto_start = auto_start
        self.auto_pull = auto_pull
        self.default_model = default_model or DEFAULT_MODEL

    def describe(self) -> str:
        return f"Ollama at {self.base_url}"

    # ----- Getting ready -----

    def warm_up(self, progress: Callable[[str], None]) -> None:
        """Start the local server if nothing answers (only when allowed and only locally)."""
        if self.auto_start and is_local(self.base_url):
            ollama_server.ensure_running(self.base_url, self.command, progress)

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
    ) -> Iterator[str]:
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
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
                text = chunk.get("message", {}).get("content", "")
                if text:
                    yield text
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
            return urllib.request.urlopen(request, timeout=timeout)
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

    def _request_json(self, method: str, path: str, timeout: float, payload: dict | None = None):
        response = self._open(method, path, payload, timeout)
        try:
            return json.loads(response.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ProviderError(f"Ollama at {self.base_url} sent a reply I couldn't understand.") from None
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
