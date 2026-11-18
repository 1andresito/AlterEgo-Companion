"""The voice, run in a helper process so its memory can be given back.

RemoteVoice looks like any Synthesizer to the Speaker and the setup. The cheap
parts (its description, whether files are missing, downloading them) use an
unloaded local engine; loading the models and speaking happen in the helper
process (voice/server.py, Alter Ego started with --voice-server).

    Speaker -> RemoteVoice.synthesize(text) --stdin--> helper: Kokoro + RVC (+ GPU pack)
                                            <--stdout-- samples

When the helper goes:
- On a computer with less than 16 GB of memory (core/machine.keep_voice_loaded),
  it is closed after IDLE_CLOSE_S without speech; the next sentence starts it again.
- On any computer, when it holds more than MEMORY_CAP_MB a little while after
  speaking, it is restarted, so the slow growth of a long session cannot add up.
- If it crashes, the sentence fails with a SynthesisError and the next one
  starts a fresh helper.
- When Alter Ego quits (close()), or if the app dies (the helper's stdin closes).
"""

from __future__ import annotations

import array
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Sequence

from ..core.machine import keep_voice_loaded
from .synthesizer import Speech, SynthesisError, Synthesizer

IDLE_CLOSE_S = 600         # Smaller computers: close the helper after 10 quiet minutes.
IDLE_CHECK_S = 30          # Everywhere: this long after speaking, check the helper's memory.
MEMORY_CAP_MB = 3500       # Above this, the helper is restarted (it grows slowly with every sentence).
STOPPED = "my voice stopped unexpectedly. I'll start it again for the next sentence."


class RemoteVoice(Synthesizer):
    def __init__(
        self,
        local: Synthesizer,
        command: Sequence[str] | None = None,
        keep_loaded: bool | None = None,
        idle_close_s: float = IDLE_CLOSE_S,
        idle_check_s: float = IDLE_CHECK_S,
        memory_cap_mb: int = MEMORY_CAP_MB,
        gpu_site: Callable[[], Path | None] | None = None,
        env: dict[str, str] | None = None,
    ):
        self.local = local  # Unloaded: answers the cheap questions and downloads files.
        self.id, self.label = local.id, local.label
        self.shape_voice = local.shape_voice
        if command is None:
            from .server import server_command

            command = server_command()
        self._command = list(command)
        self._keep = keep_voice_loaded() if keep_loaded is None else keep_loaded
        self._idle_close_s = idle_close_s
        self._idle_check_s = idle_check_s
        self._cap = memory_cap_mb
        self._gpu_site = gpu_site or (lambda: None)
        self._env = env
        self._process: subprocess.Popen | None = None
        self._loaded = False
        self._lock = threading.RLock()  # One request at a time; the idle timer takes it too.
        self._timer: threading.Timer | None = None
        self.device = ""  # Where the helper runs the voice, e.g. "GPU (NVIDIA GeForce RTX 5070)".
        self.restarts = 0

    # ----- Synthesizer interface -----

    def describe(self) -> str:
        return self.local.describe()

    @property
    def ready(self) -> bool:
        return self._loaded and self._alive()

    @property
    def needs_download(self) -> bool:
        return self.local.needs_download

    @property
    def download_size_mb(self) -> int:
        return int(getattr(self.local, "download_size_mb", 0))

    @property
    def keeps_loaded(self) -> bool:
        return self._keep

    def prepare(self) -> str:
        downloaded = self.local.needs_download
        download = getattr(self.local, "download", None)
        if downloaded and download is not None:
            download()  # Plain file downloads: done here, so the helper only loads.
        with self._lock:
            summary = self._load()
        self._touch()
        if downloaded:
            return "My voice is downloaded and ready. I'll answer out loud from now on."
        return summary

    def synthesize(self, text: str, speed: float = 1.0) -> Speech:
        with self._lock:
            self._load()
            header, payload = self._request({"op": "synthesize", "text": text, "speed": speed})
            samples = array.array("f")
            samples.frombytes(payload)
        self._touch()
        return Speech(samples, int(header.get("rate", 24000)))

    def close(self) -> None:
        """Stop the helper (Alter Ego is quitting, or the voice was switched off or changed)."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        with self._lock:
            self._stop()

    def memory_mb(self) -> int:
        """The helper's memory in MB, or 0 when it isn't running."""
        with self._lock:
            if not self._alive():
                return 0
            try:
                return int(self._request({"op": "stats"})[0].get("memory_mb", 0))
            except SynthesisError:
                return 0

    # ----- The helper process -----

    def _alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _load(self) -> str:
        """Start the helper and load the voice in it, if that hasn't happened. Lock held."""
        if self._loaded and self._alive():
            return "My voice is loaded and ready."
        self._stop()
        self._start()
        header, _ = self._request({"op": "prepare"})
        self._loaded = True
        self.device = str(header.get("device", ""))
        return str(header.get("summary", "My voice is loaded and ready."))

    def _start(self) -> None:
        env = dict(os.environ if self._env is None else self._env)
        site = self._gpu_site()
        if site is not None:
            from .server import GPU_SITE_ENV

            env[GPU_SITE_ENV] = str(site)
        kwargs: dict = {}
        if sys.platform == "win32":
            # No console window, and below normal priority so the desktop stays smooth while it works.
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        try:
            self._process = subprocess.Popen(self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, env=env, **kwargs)
        except OSError as error:
            raise SynthesisError(f"I couldn't start my voice ({error}).") from None
        threading.Thread(target=self._copy_log, args=(self._process,), name="voice-log", daemon=True).start()

    def _request(self, request: dict) -> tuple[dict, bytes]:
        """Send one request and read its answer. Lock held. Raises SynthesisError."""
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise SynthesisError(STOPPED)
        try:
            process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
            process.stdin.flush()
            line = process.stdout.readline()
            header = json.loads(line.decode("utf-8")) if line else None
            payload = b""
            if isinstance(header, dict) and header.get("ok") and header.get("bytes"):
                payload = _read_exactly(process.stdout, int(header["bytes"]))
        except (OSError, ValueError):
            header = None
        if not isinstance(header, dict):
            self._stop()
            raise SynthesisError(STOPPED)
        if not header.get("ok"):
            raise SynthesisError(str(header.get("error") or "my voice couldn't say that."))
        return header, payload

    def _stop(self) -> None:
        """End the helper, politely if it listens. Lock held."""
        process, self._process = self._process, None
        self._loaded = False
        if process is None:
            return
        try:
            if process.poll() is None and process.stdin is not None:
                process.stdin.write(b'{"op": "quit"}\n')
                process.stdin.flush()
                process.stdin.close()
            process.wait(timeout=5)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    @staticmethod
    def _copy_log(process: subprocess.Popen) -> None:
        """The helper's messages (and its libraries' warnings) go to Alter Ego's own log."""
        if process.stderr is None:
            return
        for raw in process.stderr:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                print(f"voice: {line}")

    # ----- After speaking -----

    def _touch(self) -> None:
        """Speech just happened: (re)start the timer that checks on the helper once it is quiet."""
        if self._timer is not None:
            self._timer.cancel()
        delay = self._idle_check_s if self._keep else self._idle_close_s
        self._timer = threading.Timer(delay, self._on_quiet)
        self._timer.daemon = True
        self._timer.start()

    def _on_quiet(self) -> None:
        if not self._lock.acquire(blocking=False):
            self._touch()  # Busy speaking after all: look again later.
            return
        try:
            if not self._alive():
                return
            if not self._keep:
                print("Alter Ego: closing my voice for now to free memory (it loads again when needed).")
                self._stop()
                return
            memory = int(self._request({"op": "stats"})[0].get("memory_mb", 0))
            if memory > self._cap:
                print(f"Alter Ego: my voice grew to {memory} MB; restarting it to free memory.")
                self.restarts += 1
                self._stop()
                self._load()  # Keep it ready: this computer keeps the voice loaded.
        except SynthesisError as error:
            print(f"Alter Ego: voice check failed: {error}")
        finally:
            self._lock.release()


def _read_exactly(stream, size: int) -> bytes:
    parts = []
    while size > 0:
        chunk = stream.read(size)
        if not chunk:
            raise OSError("the voice helper closed its output")
        parts.append(chunk)
        size -= len(chunk)
    return b"".join(parts)
