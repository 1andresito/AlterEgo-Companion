"""Starting and stopping the local Ollama server on Alter Ego's behalf.

When Ollama is the chosen provider, Alter Ego should just work: if nothing is
listening at the local address, it runs `ollama serve` itself and waits until
the server answers. When Alter Ego quits, or the user switches to another
provider, Ollama is switched off so its model stops taking memory: the
process started here, and on Windows also the Ollama tray app and the model
runners (the owner's choice: Ollama runs only while Alter Ego uses it).

    OllamaServer.ensure_running(base_url, command, progress)  -> starts if needed
    OllamaServer.stop()                                      -> stops what we started
    OllamaServer.stop_all()                                  -> stops every local Ollama

On Windows the process started here sits in a Job Object that the system kills
together with Alter Ego, so even a crash does not leave Ollama running, and it
is stopped with its whole process tree: `ollama serve` loads models in a child
"runner" process, which a plain terminate() would leave behind holding the RAM.

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
# Windows image names of everything Ollama runs: the tray app, the server and its model runners.
WINDOWS_IMAGES = ("ollama app.exe", "ollama.exe", "ollama_llama_server.exe")
# Set for a server started here: one model in memory and one reply at a time keep RAM use low.
LEAN_ENV = {"OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1"}

NOT_INSTALLED_MESSAGE = (
    f"Ollama isn't installed on this computer, so I have no AI model to think with. "
    f"Get it from {DOWNLOAD_URL}, then talk to me again."
)


def direct_url(base_url: str) -> str:
    """The same address with "localhost" spelled 127.0.0.1.

    On Windows "localhost" resolves to the IPv6 address first; Ollama listens on IPv4
    only, so every request waited about two seconds for the IPv6 attempt to fail
    before trying IPv4. That was most of the delay before each reply.
    """
    parsed = urlparse(base_url)
    if (parsed.hostname or "").lower() != "localhost":
        return base_url
    netloc = "127.0.0.1" + (f":{parsed.port}" if parsed.port else "")
    return parsed._replace(netloc=netloc).geturl()


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
    # The install folders stand in only for Ollama itself; any other command that is
    # missing must be reported as missing, not quietly replaced by the installed Ollama.
    if sys.platform == "win32" and candidate.stem.lower() == "ollama":
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
        """Stop the server if Alter Ego started it, with any model runner it started."""
        with self._lock:
            process = self._process
            self._process = None
            if process is None or process.poll() is not None:
                return
            if sys.platform == "win32":
                _run_quietly(["taskkill", "/T", "/F", "/PID", str(process.pid)])
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def stop_all(self) -> None:
        """Switch Ollama off: the server started here, and on Windows every other Ollama process too.

        On Linux Ollama usually runs as a system service, which needs administrator
        rights to stop, so only the process started here is stopped there.
        """
        self.stop()
        if sys.platform != "win32":
            return
        for image in WINDOWS_IMAGES:
            _run_quietly(["taskkill", "/F", "/T", "/IM", image])

    # ----- Internals -----

    @staticmethod
    def _spawn(command_line: list[str], base_url: str) -> subprocess.Popen:
        env = dict(os.environ)
        for key, value in LEAN_ENV.items():
            env.setdefault(key, value)  # The user's own Ollama settings win.
        parsed = urlparse(base_url)
        if parsed.port and parsed.port != 11434:
            env["OLLAMA_HOST"] = f"{parsed.hostname}:{parsed.port}"
        kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "env": env}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(command_line, **kwargs)
        except OSError as error:
            raise ProviderError(f"I couldn't start Ollama ({command_line[0]}): {error}") from None
        _kill_with_this_app(process)
        return process

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


def _run_quietly(command: list[str]) -> None:
    """Run a short system command, ignoring its output and any failure (nothing to stop is fine)."""
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(command, timeout=10, check=False, **kwargs)
    except (OSError, subprocess.SubprocessError):
        pass


# Kept open for the life of the app: when Alter Ego's process ends, Windows closes it and kills the job.
_job_handle = None


def _kill_with_this_app(process: subprocess.Popen) -> None:
    """Windows only: put the process in a Job Object that dies with Alter Ego. No-op elsewhere or on failure."""
    global _job_handle
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE
        if _job_handle is None:
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                return

            class BasicLimits(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class IoCounters(ctypes.Structure):
                _fields_ = [(name, ctypes.c_uint64) for name in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class ExtendedLimits(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

            limits = ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            extended_limit_information = 9
            if not kernel32.SetInformationJobObject(job, extended_limit_information,
                                                    ctypes.byref(limits), ctypes.sizeof(limits)):
                kernel32.CloseHandle(job)
                return
            _job_handle = job
        access = 0x0100 | 0x0001  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        handle = kernel32.OpenProcess(access, False, process.pid)
        if handle:
            kernel32.AssignProcessToJobObject(_job_handle, handle)
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError) as error:
        print(f"Warning: could not tie Ollama to Alter Ego's lifetime: {error}")


# The one server handle for the whole app.
ollama_server = OllamaServer()
