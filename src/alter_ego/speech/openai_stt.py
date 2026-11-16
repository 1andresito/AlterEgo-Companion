"""Speech recognition through an OpenAI-compatible API (POST {base_url}/audio/transcriptions).

Uses the same base URL and API key as the OpenAI-compatible chat provider,
so people who already pay for one key need nothing else. OpenAI offers
"whisper-1"; Groq offers "whisper-large-v3"; a local server such as
speaches or LocalAI works too. The recording leaves the computer, which the
README says plainly.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
import uuid

from .audio import AudioClip
from .transcriber import Transcriber, TranscriptionError

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "whisper-1"
API_KEY_ENV = "OPENAI_API_KEY"
TIMEOUT_S = 60


class OpenAITranscriber(Transcriber):
    id = "openai"
    label = "OpenAI-compatible API (whisper-1, uses your key)"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        language: str = "",
    ):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or os.environ.get(API_KEY_ENV, "")
        self.model = model or DEFAULT_MODEL
        self.language = language.strip()

    def describe(self) -> str:
        return f"'{self.model}' at {self.base_url}"

    def prepare(self) -> str:
        request = urllib.request.Request(self.base_url + "/models", headers=self._headers())
        self._send(request)
        return f"I can reach {self.base_url}. Speech will be recognised there by '{self.model}'."

    def transcribe(self, clip: AudioClip) -> str:
        fields = {"model": self.model, "response_format": "json"}
        if self.language:
            fields["language"] = self.language
        body, content_type = _multipart(fields, "file", "speech.wav", "audio/wav", clip.to_wav_bytes())
        headers = self._headers()
        headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base_url + "/audio/transcriptions", data=body, headers=headers, method="POST")
        raw = self._send(request)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise TranscriptionError(f"{self.base_url} sent a reply I couldn't understand.") from None
        return str(data.get("text", "")).strip() if isinstance(data, dict) else ""

    # ----- HTTP -----

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "AlterEgo-Companion"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _send(self, request: urllib.request.Request) -> bytes:
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise TranscriptionError(self._explain_http_error(error)) from None
        except urllib.error.URLError as error:
            reason = error.reason if not isinstance(error.reason, socket.timeout) else "timed out"
            raise TranscriptionError(f"I couldn't connect to {self.base_url}: {reason}") from None
        except socket.timeout:
            raise TranscriptionError(f"{self.base_url} took too long to recognise the speech.") from None

    def _explain_http_error(self, error: urllib.error.HTTPError) -> str:
        detail = ""
        try:
            payload = json.loads(error.read().decode("utf-8"))
            err = payload.get("error") if isinstance(payload, dict) else None
            detail = str(err.get("message") if isinstance(err, dict) else err or "").strip()
        except Exception:  # noqa: BLE001 - the body is only decoration for the message
            pass
        if error.code == 401:
            return f"{self.base_url} rejected the API key. Check the 'openai' section of the settings file."
        if error.code == 404:
            return f"{self.base_url} has no /audio/transcriptions endpoint, so it cannot recognise speech."
        if error.code == 429:
            return f"{self.base_url} says I'm sending too much right now (rate limit). {detail}".strip()
        return f"{self.base_url} answered with HTTP {error.code}. {detail}".strip()


def _multipart(fields: dict[str, str], file_field: str, filename: str, mime: str, content: bytes) -> tuple[bytes, str]:
    """Build a multipart/form-data body by hand (the standard library has no helper for it)."""
    boundary = f"----AlterEgo{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8")
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {mime}\r\n\r\n".encode("utf-8") + content + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
