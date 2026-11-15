"""Ollama provider: local models served by https://ollama.com.

Talks to Ollama's HTTP API with the standard library only, so it adds no
dependency. Two endpoints are used:

  GET  /api/tags   -> installed models
  POST /api/chat   -> chat completion, streamed as one JSON object per line
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Callable, Iterator

from .base import ChatMessage, Provider, ProviderError

DEFAULT_BASE_URL = "http://localhost:11434"
CONNECT_TIMEOUT_S = 10
STREAM_TIMEOUT_S = 120


class OllamaProvider(Provider):
    id = "ollama"
    label = "Ollama (local)"

    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def describe(self) -> str:
        return f"Ollama at {self.base_url}"

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
