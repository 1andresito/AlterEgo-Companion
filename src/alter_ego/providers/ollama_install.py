"""Installing Ollama for the user, from the first-run setup.

Ollama is the free, local AI that Alter Ego thinks with by default. Installing
it used to be the one step a new user had to do alone; this module does it
when the user ticks "Install Ollama" in the setup (never on its own):

- Windows: download the official installer (OllamaSetup.exe) and run it
  silently. It installs per user, so no administrator prompt appears.
- Linux: run the official install script through `pkexec`, which shows the
  desktop's own password prompt. Without `pkexec` the user is given the
  command to paste into a terminal.

    install(progress)  -> downloads, installs, confirms with find_command()

Runs on a worker thread (it takes minutes). Raises ProviderError with a message
for the user.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .base import ProviderError
from .https import urlopen
from .ollama_server import DEFAULT_COMMAND, DOWNLOAD_URL, find_command

# The official Windows installer. A constant so the tests can point it at a fake server.
WINDOWS_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
# Inno Setup's flags for an install with no windows and no questions.
WINDOWS_SILENT_FLAGS = ["/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES", "/SP-"]
# Put in front of the downloaded installer when it is run; the tests set [python] to run a fake one.
INSTALLER_PREFIX: list[str] = []
# The official Linux install script; it needs root, hence pkexec.
LINUX_INSTALL_COMMAND = "curl -fsSL https://ollama.com/install.sh | sh"
WINDOWS_DOWNLOAD_MB = 1100  # About the size of OllamaSetup.exe, shown in the setup before asking.
INSTALL_TIMEOUT_S = 900     # Unpacking the CUDA libraries takes a while on a slow disk.
CHUNK_BYTES = 1 << 20

Progress = Callable[[str, int], None]  # text, percent (-1 = no percentage known)


def is_installed(command: str | list[str] = DEFAULT_COMMAND) -> bool:
    return find_command(command) is not None


def can_install() -> bool:
    """Whether install() can do the job here, as opposed to only explaining how."""
    if sys.platform == "win32":
        return True
    return sys.platform.startswith("linux") and shutil.which("pkexec") is not None and shutil.which("curl") is not None


def manual_hint() -> str:
    """How to install Ollama by hand on this system, for messages."""
    if sys.platform.startswith("linux"):
        return f"run this in a terminal:  {LINUX_INSTALL_COMMAND}"
    return f"get it from {DOWNLOAD_URL}"


def install(progress: Progress, command: str | list[str] = DEFAULT_COMMAND) -> None:
    """Install Ollama, reporting progress. Runs on a worker thread; raises ProviderError."""
    if is_installed(command):
        return
    if sys.platform == "win32":
        _install_windows(progress)
    elif sys.platform.startswith("linux"):
        _install_linux(progress)
    else:
        raise ProviderError(f"I can't install Ollama on this system by myself. Please {manual_hint()}.")
    if not is_installed(command):
        raise ProviderError(
            f"The Ollama installer finished, but I still can't find Ollama. Please {manual_hint()}, "
            "then open AI -> Set up Ollama and my voice again."
        )


def download(url: str, target: Path, progress: Progress, label: str) -> None:
    """Download `url` to `target` with percent progress; a partial file never stays behind."""
    partial = target.with_suffix(target.suffix + ".part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "AlterEgo-Companion"})
        with urlopen(request, timeout=60) as response, open(partial, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            last = -1
            while True:
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                percent = 100 * done // total if total else -1
                if percent != last:
                    last = percent
                    progress(label, percent)
        os.replace(partial, target)
    except (urllib.error.URLError, OSError, ValueError) as error:
        try:
            partial.unlink()
        except OSError:
            pass
        raise ProviderError(
            f"I couldn't download Ollama: {getattr(error, 'reason', error)}. "
            "Check the internet connection and try again."
        ) from None


# ----- Internals -----

def _install_windows(progress: Progress) -> None:
    folder = Path(tempfile.mkdtemp(prefix="alter_ego_ollama_"))
    installer = folder / "OllamaSetup.exe"
    try:
        download(WINDOWS_INSTALLER_URL, installer, progress, "Downloading Ollama...")
        progress("Installing Ollama (this takes a minute or two)...", -1)
        _run_installer(INSTALLER_PREFIX + [str(installer)] + WINDOWS_SILENT_FLAGS)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _install_linux(progress: Progress) -> None:
    if not can_install():
        raise ProviderError(
            f"I can't install Ollama by myself here (I need pkexec and curl). Please {manual_hint()}, "
            "then open AI -> Set up Ollama and my voice again."
        )
    progress("Installing Ollama (your computer will ask for your password)...", -1)
    _run_installer(["pkexec", "sh", "-c", LINUX_INSTALL_COMMAND])


def _run_installer(command_line: list[str]) -> None:
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(command_line, timeout=INSTALL_TIMEOUT_S, check=False, **kwargs)
    except subprocess.TimeoutExpired:
        raise ProviderError("The Ollama installer took far too long, so I stopped waiting. Please try again.") from None
    except OSError as error:
        raise ProviderError(f"I couldn't start the Ollama installer: {error}") from None
    if result.returncode != 0:
        # pkexec returns 126 when the password prompt was cancelled, 127 when not authorised.
        if command_line[0] == "pkexec" and result.returncode in (126, 127):
            raise ProviderError(f"The password prompt was closed, so Ollama wasn't installed. Or {manual_hint()}.")
        raise ProviderError(f"The Ollama installer stopped with an error (code {result.returncode}). Please {manual_hint()}.")
