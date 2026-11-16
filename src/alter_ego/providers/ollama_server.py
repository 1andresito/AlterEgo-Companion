"""Starting and stopping the local Ollama server on Alter Ego's behalf.

When Ollama is the chosen provider, Alter Ego should just work: if nothing is
listening at the local address, it runs `ollama serve` itself, waits until the
server answers, and stops that same process again when Alter Ego quits. A
server the user started (the Ollama desktop app, a terminal) is never touched:
only a process started here is stopped here.

    OllamaServer.ensure_running(base_url, command, progress)  -> starts if needed
    OllamaServer.stop()                                      -> stops what we started

One instance for the whole app (`ollama_server` below): providers come and go
as the settings change, but the process must outlive them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .base import ProviderError

DEFAULT_COMMAND = "ollama"
DOWNLOAD_URL = "https://ollama.com/download"
START_TIMEOUT_S = 30
POLL_INTERVAL_S = 0.5
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

NOT_INSTALLED_MESSAGE = (
    f"Ollama isn't installed on this computer, so I have no AI model to think with. "
    f"Get it from {DOWNLOAD_URL}, then talk to me again."
)


def is_local(base_url: str) -> bool:
    host = urlparse(base_url).hostname or ""
    return host.lower() in LOCAL_HOSTS


def find_command(command: str | list[str] = DEFAULT_COMMAND) -> list[str] | None:
    """The command line that runs Ollama, or None when it is not installed.

    A list is used as-is (tests pass a Python script). A string is looked up on
    PATH and in the usual Windows install folders, which are not always on PATH.
    """
    if isinstance(command, list):
        return list(command) if command else None
    if not command:
        return None
    found = shutil.which(command)
    if found:
        return [found]
    candidate = Path(command)
    if candidate.is_file():
        return [str(candidate)]
    if sys.platform == "win32":
        for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("PROGRAMFILES", "")):
            if base:
                exe = Path(base) / "Programs" / "Ollama" / "ollama.exe"
                if exe.is_file():
                    return [str(exe)]
                exe = Path(base) / "Ollama" / "ollama.exe"
                if exe.is_file():
                    return [str(exe)]
    return None


def is_reachable(base_url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/api/tags", timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


class OllamaServer:
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def started_by_us(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def ensure_running(
        self,
        base_url: str,
        command: str | list[str] = DEFAULT_COMMAND,
        progress: Callable[[str], None] | None = None,
    ) -> bool:
        """Make sure something answers at `base_url`. Returns True if a server was started here.

        Does nothing for a remote address. Raises ProviderError when Ollama is
        not installed or does not come up in time.
        """
        with self._lock:
            if is_reachable(base_url):
                return False
            if not is_local(base_url):
                raise ProviderError(
                    f"I can't reach Ollama at {base_url}. It isn't on this computer, so I can't start it for you."
                )
            if self.started_by_us:
                # Started earlier and still alive, but not answering: give it a moment more.
                self._wait_until_up(base_url, progress)
                return False
            command_line = find_command(command)
            if command_line is None:
                raise ProviderError(NOT_INSTALLED_MESSAGE)
            if progress:
                progress("Starting Ollama...")
            self._process = self._spawn(command_line + ["serve"], base_url)
            self._wait_until_up(base_url, progress)
            return True

    def stop(self) -> None:
        """Stop the server if, and only if, Alter Ego started it."""
        with self._lock:
            process = self._process
            self._process = None
            if process is None or process.poll() is not None:
                return
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    # ----- Internals -----

    @staticmethod
    def _spawn(command_line: list[str], base_url: str) -> subprocess.Popen:
        env = dict(os.environ)
        parsed = urlparse(base_url)
        if parsed.port and parsed.port != 11434:
            env["OLLAMA_HOST"] = f"{parsed.hostname}:{parsed.port}"
        kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "env": env}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            return subprocess.Popen(command_line, **kwargs)
        except OSError as error:
            raise ProviderError(f"I couldn't start Ollama ({command_line[0]}): {error}") from None

    def _wait_until_up(self, base_url: str, progress: Callable[[str], None] | None) -> None:
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if is_reachable(base_url, timeout=1.0):
                return
            process = self._process
            if process is not None and process.poll() is not None:
                self._process = None
                raise ProviderError(
                    "Ollama started but stopped again at once. Is another Ollama already using the port, "
                    "or did the install go wrong? Try running 'ollama serve' in a terminal to see why."
                )
            time.sleep(POLL_INTERVAL_S)
        raise ProviderError(f"Ollama didn't answer at {base_url} within {START_TIMEOUT_S} seconds.")


# The one server handle for the whole app.
ollama_server = OllamaServer()
