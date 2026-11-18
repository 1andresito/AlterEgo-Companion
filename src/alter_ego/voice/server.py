"""The voice in its own process: Alter Ego started with --voice-server.

The character voice (Kokoro + PyTorch + the RVC converter) takes 2-3 GB of
memory, and a process rarely gives freed memory back to the system. So it runs
here, in a helper process the app starts and stops (voice/remote.py): closing
the helper is what really returns the memory.

    app (RemoteVoice) --stdin, one JSON line per request--> this process
                      <--stdout: a JSON line, then raw samples--

Requests and answers:

    {"op": "prepare"}                          -> {"ok": true, "summary": ..., "device": ...}
    {"op": "synthesize", "text", "speed"}      -> {"ok": true, "rate": 24000, "bytes": N} + N bytes (float32)
    {"op": "stats"}                            -> {"ok": true, "memory_mb": ...}
    {"op": "quit"}                             -> the process ends (it also ends when stdin closes)
    any failure                                -> {"ok": false, "error": "a sentence for the user"}

`--probe` only reports whether PyTorch sees a CUDA card, for the GPU pack check.
Like the tool server, this is the same executable as the app, so it also works
from the packaged build, and it uses file descriptors 0 and 1 because a windowed
build has no sys.stdin/sys.stdout. Everything printed (library logs included)
goes to stderr, which the app copies into its log, never into the answers.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

FLAG = "--voice-server"
PROBE_FLAG = "--probe"
VOICE_FOLDER_FLAG = "--voice-folder"
GPU_SITE_ENV = "ALTER_EGO_GPU_SITE"     # The GPU pack's site-packages, set by the app when it is installed.
FAKE_ENV = "ALTER_EGO_FAKE_VOICE"       # Tests: a beep instead of the real voice, no models needed.
FAKE_CRASH_ENV = "ALTER_EGO_FAKE_VOICE_CRASH"  # Tests: exit at once when asked to say this text.


def server_command(voice_folder: Path | None = None, probe: bool = False) -> list[str]:
    """The command line that starts this helper: Alter Ego's own executable, or main.py from source."""
    if getattr(sys, "frozen", False):
        command = [sys.executable, FLAG]
    else:
        command = [sys.executable, str(Path(__file__).resolve().parents[3] / "main.py"), FLAG]
    if voice_folder is not None:
        command += [VOICE_FOLDER_FLAG, str(voice_folder)]
    if probe:
        command.append(PROBE_FLAG)
    return command


def main(argv: list[str]) -> int:
    answers, requests = _protocol_pipes()
    site = os.environ.get(GPU_SITE_ENV, "")
    if site:
        from ..core.gpu_pack import prefer_pack  # Standard library only: safe before PyTorch is imported.

        prefer_pack(Path(site))
    if PROBE_FLAG in argv:
        return _probe(answers)
    synthesizer = _build(argv)

    def reply(data: dict, payload: bytes = b"") -> None:
        answers.write((json.dumps(data) + "\n").encode("utf-8") + payload)
        answers.flush()

    for raw in requests:
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        op = request.get("op") if isinstance(request, dict) else None
        if op == "quit":
            break
        try:
            if op == "prepare":
                reply({"ok": True, "summary": synthesizer.prepare(), "device": _device()})
            elif op == "synthesize":
                text = str(request.get("text", ""))
                crash = os.environ.get(FAKE_CRASH_ENV)
                if crash and crash in text:
                    os._exit(3)
                speech = synthesizer.synthesize(text, float(request.get("speed", 1.0)))
                payload = speech.samples.tobytes()
                reply({"ok": True, "rate": speech.sample_rate, "bytes": len(payload)}, payload)
            elif op == "stats":
                from ..core.machine import process_memory_mb

                reply({"ok": True, "memory_mb": process_memory_mb()})
            else:
                reply({"ok": False, "error": f"unknown request {op!r}"})
        except Exception as error:  # noqa: BLE001 - one bad sentence must not end the helper
            from .synthesizer import SynthesisError

            if not isinstance(error, SynthesisError):
                traceback.print_exc()
                error = f"something went wrong in my voice ({type(error).__name__}: {error})"
            reply({"ok": False, "error": str(error)})
    return 0


def _protocol_pipes():
    """Binary stdin/stdout for the protocol; afterwards anything printed goes to stderr instead."""
    answers = os.fdopen(os.dup(1), "wb")
    requests = open(0, "rb", closefd=False)
    try:
        os.dup2(2, 1)  # Native libraries that write to stdout now write to stderr.
    except OSError:
        pass
    if sys.stderr is None:  # A windowed build: use the stderr pipe the app gave us.
        try:
            sys.stderr = open(2, "w", encoding="utf-8", errors="replace", buffering=1, closefd=False)
        except OSError:
            sys.stderr = open(os.devnull, "w")
    sys.stdout = sys.stderr
    return answers, requests


def _build(argv: list[str]):
    if os.environ.get(FAKE_ENV) == "1":
        return _FakeVoice()
    from ..settings.config import Config
    from . import build_synthesizer

    folder = None
    if VOICE_FOLDER_FLAG in argv:
        index = argv.index(VOICE_FOLDER_FLAG)
        if index + 1 < len(argv):
            folder = Path(argv[index + 1])
    synthesizer = build_synthesizer(Config.load(), folder)
    if synthesizer is None:
        raise SystemExit("the voice is switched off")
    return synthesizer


def _device() -> str:
    if os.environ.get(FAKE_ENV) == "1":
        return "test"
    try:
        from .device import describe_device

        return describe_device()
    except Exception:  # noqa: BLE001
        return ""


def _probe(answers) -> int:
    """For the GPU pack: does this process's PyTorch see a CUDA card?"""
    result: dict = {"cuda": False, "name": "", "torch": "", "file": ""}
    try:
        import torch

        result["torch"] = str(torch.__version__)
        result["file"] = str(getattr(torch, "__file__", ""))
        if torch.cuda.is_available():
            result["cuda"] = True
            result["name"] = torch.cuda.get_device_name(0)
    except Exception as error:  # noqa: BLE001
        result["error"] = f"{type(error).__name__}: {error}"
    answers.write((json.dumps(result) + "\n").encode("utf-8"))
    answers.flush()
    return 0


class _FakeVoice:
    """A quiet tone, so tests can run the real helper process without any models."""

    shape_voice = False

    def prepare(self) -> str:
        return "fake voice ready"

    def synthesize(self, text: str, speed: float = 1.0):
        import array

        from .synthesizer import Speech

        samples = array.array("f", [0.25] * int(len(text) * 240 / max(speed, 0.1)))
        return Speech(samples, 24000)
