"""Text-to-speech through an OpenAI-compatible API (POST {base_url}/audio/speech).

Uses the same base URL and API key as the OpenAI-compatible chat provider and
the API speech-recognition engine. OpenAI offers the "tts-1" and
"gpt-4o-mini-tts" models with voices such as "nova" and "shimmer"; local
servers such as speaches, LocalAI or Kokoro-FastAPI expose the same route.
The text of each reply leaves the computer, which the README says plainly.
"""

from __future__ import annotations

import io
import json
import os
import socket
import urllib.error
import urllib.request
import wave

from .effects import from_pcm16
from .synthesizer import Speech, Synthesizer, SynthesisError

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "tts-1"
DEFAULT_VOICE = "nova"
API_KEY_ENV = "OPENAI_API_KEY"
TIMEOUT_S = 60


class OpenAISynthesizer(Synthesizer):
    id = "openai"
    label = "OpenAI-compatible API (tts-1, uses your key)"

    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_key: str = "", model: str = DEFAULT_MODEL, voice: str = DEFAULT_VOICE):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or os.environ.get(API_KEY_ENV, "")
        self.model = model or DEFAULT_MODEL
        self.voice = voice or DEFAULT_VOICE

    def describe(self) -> str:
        return f"voice '{self.voice}' of '{self.model}' at {self.base_url}"

    def prepare(self) -> str:
        request = urllib.request.Request(self.base_url + "/models", headers=self._headers())
        self._send(request)
        return f"I can reach {self.base_url}. I'll speak with the '{self.voice}' voice of '{self.model}'."

    def synthesize(self, text: str, speed: float = 1.0) -> Speech:
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": "wav",
            "speed": max(0.25, min(4.0, float(speed))),
        }
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + "/audio/speech", data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
        )
        raw = self._send(request)
        try:
            with wave.open(io.BytesIO(raw), "rb") as wav:
                if wav.getsampwidth() != 2:
                    raise SynthesisError(f"{self.base_url} sent {8 * wav.getsampwidth()}-bit audio; I can only play 16-bit WAV.")
                return from_pcm16(wav.readframes(wav.getnframes()), wav.getframerate(), wav.getnchannels())
        except (wave.Error, EOFError):
            raise SynthesisError(f"{self.base_url} sent audio I couldn't understand (not a WAV file).") from None

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
            raise SynthesisError(self._explain_http_error(error)) from None
        except urllib.error.URLError as error:
            reason = error.reason if not isinstance(error.reason, socket.timeout) else "timed out"
            raise SynthesisError(f"I couldn't connect to {self.base_url}: {reason}") from None
        except socket.timeout:
            raise SynthesisError(f"{self.base_url} took too long to produce the speech.") from None

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
            return f"{self.base_url} has no /audio/speech endpoint, so it cannot speak."
        if error.code == 429:
            return f"{self.base_url} says I'm sending too much right now (rate limit). {detail}".strip()
        return f"{self.base_url} answered with HTTP {error.code}. {detail}".strip()
