"""OpenAI-compatible provider: ChatGPT (OpenAI API) and everything that speaks its dialect.

The same two endpoints are offered by OpenAI, Groq, OpenRouter, Mistral,
LM Studio, llama.cpp's server and Ollama itself, so one class covers many
services. Only the base URL, the API key and the model differ.

  GET  {base_url}/models            -> available models
  POST {base_url}/chat/completions  -> streamed as Server-Sent Events ("data: {...}")
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Callable, Iterator

from .base import ChatMessage, Provider, ProviderError

DEFAULT_BASE_URL = "https://api.openai.com/v1"
CONNECT_TIMEOUT_S = 15
STREAM_TIMEOUT_S = 120
API_KEY_ENV = "OPENAI_API_KEY"


class OpenAICompatibleProvider(Provider):
    id = "openai"
    label = "OpenAI-compatible API (ChatGPT, Groq, LM Studio...)"

    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        # The key can live in the config file or in the OPENAI_API_KEY environment variable.
        self.api_key = api_key or os.environ.get(API_KEY_ENV, "")

    def describe(self) -> str:
        return f"OpenAI-compatible API at {self.base_url}"

    def list_models(self) -> list[str]:
        data = self._request_json("GET", "/models", timeout=CONNECT_TIMEOUT_S)
        entries = data.get("data", []) if isinstance(data, dict) else []
        return sorted(str(entry.get("id")) for entry in entries if entry.get("id"))

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
        response = self._open("POST", "/chat/completions", payload, timeout=STREAM_TIMEOUT_S)
        try:
            for raw_line in response:
                if cancelled():
                    return
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue  # SSE comments, blank keep-alive lines, "event:" lines
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if "error" in chunk:
                    raise ProviderError(f"The API reported an error: {_error_text(chunk['error'])}")
                for choice in chunk.get("choices", []):
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        yield text
        except socket.timeout:
            raise ProviderError("The API stopped responding mid-reply (timed out).") from None
        finally:
            response.close()

    # ----- HTTP helpers -----

    def _open(self, method: str, path: str, payload: dict | None, timeout: float):
        url = self.base_url + path
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            raise ProviderError(self._explain_http_error(error)) from None
        except urllib.error.URLError as error:
            reason = getattr(error, "reason", error)
            raise ProviderError(f"I couldn't connect to {self.base_url}: {reason}") from None
        except socket.timeout:
            raise ProviderError(f"{self.base_url} took too long to answer.") from None

    def _request_json(self, method: str, path: str, timeout: float, payload: dict | None = None):
        response = self._open(method, path, payload, timeout)
        try:
            return json.loads(response.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ProviderError(f"{self.base_url} sent a reply I couldn't understand.") from None
        finally:
            response.close()

    def _explain_http_error(self, error: urllib.error.HTTPError) -> str:
        try:
            detail = _error_text(json.loads(error.read().decode("utf-8")).get("error", ""))
        except Exception:
            detail = ""
        if error.code == 401:
            where = f'"api_key" under "{self.id}" in the settings file, or the {API_KEY_ENV} environment variable'
            return f"The API rejected my key (HTTP 401). Put a valid key in {where}."
        if error.code == 404 and "model" in detail.lower():
            return f"The API says: {detail}. Pick another model."
        if error.code == 429:
            return "The API is rate-limiting me (HTTP 429). Please wait a moment and try again."
        return f"The API returned HTTP {error.code}" + (f": {detail}" if detail else ".")


def _error_text(error) -> str:
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)
