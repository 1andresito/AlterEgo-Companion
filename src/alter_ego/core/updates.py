"""Updating Alter Ego to a new release, with the user's consent.

At start-up (and from AI -> Check for updates now) Alter Ego asks GitHub for the
latest release. If it is newer, the user is asked; nothing is downloaded before
they say yes. The check sends no personal details: it is one request to the
GitHub API for the latest version number.

    check_latest()          -> Release, or None when there is no release yet
    install_method()        -> how this copy of Alter Ego can be replaced, or None
    prepare(release, ...)   -> downloads and unpacks; returns a Relaunch
    relaunch.start()        -> starts the hand-over; the app then quits

How each copy is replaced (the program folder is never changed while it runs):

- Windows, installed: the new AlterEgo-Setup-vX.Y.Z.exe runs silently, closes
  this copy, and starts the new one (`/RELAUNCH=1`, see packaging/windows).
- Windows portable and Linux: the new download is unpacked to a temporary
  folder; a small script waits for this process to end, copies the new program
  over the old folder, and starts it again.
- Running from source: no update; a Git checkout is updated with `git pull`.

The download and unpacking run on a worker thread (UpdateJob). The settings
and memories live in the data folder, outside the program folder, so they stay.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import traceback
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal

from .. import __version__
from ..providers.https import urlopen

# A constant so the tests can point it at a fake server.
LATEST_RELEASE_URL = "https://api.github.com/repos/1andresito/AlterEgo-Companion/releases/latest"
USER_AGENT = "AlterEgo-Companion"
CHECK_TIMEOUT_S = 10
CHUNK_BYTES = 1 << 20

Progress = Callable[[str, int], None]  # text, percent (-1 = unknown)


class UpdateError(Exception):
    """Something went wrong; the message is written for the user."""


class Method(Enum):
    WINDOWS_SETUP = "windows-setup"        # installed with AlterEgo-Setup-*.exe
    WINDOWS_PORTABLE = "windows-portable"  # unzipped from the portable zip
    LINUX = "linux"                        # unpacked from the tar.gz (installed with install.sh or not)


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int = 0


@dataclass(frozen=True)
class Release:
    version: str                 # "0.8.0", without the "v"
    page_url: str                # the release page, for "Open the download page"
    notes: str = ""
    assets: dict[str, Asset] = field(default_factory=dict)

    def asset_for(self, method: Method | None) -> Asset | None:
        if method is None:
            return None
        return self.assets.get(asset_name(method, self.version))


# ----- Versions -----

def parse_version(text: str) -> tuple[int, ...]:
    """'v0.10.2' -> (0, 10, 2). Anything after the numbers (a '-beta' suffix) is ignored."""
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(remote: str, local: str = __version__) -> bool:
    remote_parts, local_parts = parse_version(remote), parse_version(local)
    if not remote_parts:
        return False
    width = max(len(remote_parts), len(local_parts))
    pad = lambda parts: parts + (0,) * (width - len(parts))  # noqa: E731 - "0.8" equals "0.8.0"
    return pad(remote_parts) > pad(local_parts)


# ----- Which copy is this, and what replaces it -----

def program_dir() -> Path:
    return Path(sys.executable).resolve().parent


def install_method(frozen: bool | None = None, platform: str = sys.platform,
                   folder: Path | None = None) -> Method | None:
    """How this copy can update itself; None when it can't (from source, or a folder it may not write)."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return None
    folder = folder or program_dir()
    if platform == "win32":
        if any(folder.glob("unins*.exe")):
            return Method.WINDOWS_SETUP
        return Method.WINDOWS_PORTABLE if os.access(folder, os.W_OK) else None
    if platform.startswith("linux"):
        return Method.LINUX if os.access(folder, os.W_OK) else None
    return None


def asset_name(method: Method, version: str) -> str:
    """The release workflow's file names (.github/workflows/release.yml)."""
    if method is Method.WINDOWS_SETUP:
        return f"AlterEgo-Setup-v{version}.exe"
    if method is Method.WINDOWS_PORTABLE:
        return f"AlterEgo-v{version}-windows-portable.zip"
    return f"AlterEgo-v{version}-linux-x86_64.tar.gz"


# ----- Checking -----

def check_latest(url: str = LATEST_RELEASE_URL) -> Release | None:
    """The latest published release (drafts and pre-releases are not), or None if there is none yet."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    try:
        with urlopen(request, timeout=CHECK_TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise UpdateError(f"GitHub answered {error.code} when I looked for a new version.") from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise UpdateError(f"I couldn't check for a new version: {getattr(error, 'reason', error)}.") from None
    return parse_release(data)


def parse_release(data: dict) -> Release | None:
    tag = str(data.get("tag_name") or "")
    if not parse_version(tag):
        return None
    assets: dict[str, Asset] = {}
    for item in data.get("assets") or []:
        name = str(item.get("name") or "")
        link = str(item.get("browser_download_url") or "")
        if name and link:
            assets[name] = Asset(name, link, int(item.get("size") or 0))
    return Release(
        version=".".join(str(part) for part in parse_version(tag)),
        page_url=str(data.get("html_url") or ""),
        notes=str(data.get("body") or "").strip(),
        assets=assets,
    )


def should_offer(release: Release | None, skipped: str, manual: bool, local: str = __version__) -> bool:
    """Offer `release`? A version the user skipped is offered again only when they check by hand."""
    if release is None or not is_newer(release.version, local):
        return False
    return manual or release.version != skipped


# ----- Downloading and handing over -----

@dataclass
class Relaunch:
    """What to start once everything is ready; the app quits right after `start()`."""

    command: list[str]
    cwd: Path | None = None

    def start(self) -> None:
        options: dict = {"cwd": str(self.cwd) if self.cwd else None, "close_fds": True,
                         "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            options["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            options["start_new_session"] = True  # Keeps running after this process ends.
        try:
            subprocess.Popen(self.command, **options)  # noqa: S603 - our own downloaded installer or script
        except OSError as error:
            raise UpdateError(f"I couldn't start the update: {error}") from None


def prepare(release: Release, method: Method, progress: Progress,
            cancelled: Callable[[], bool] = lambda: False, folder: Path | None = None,
            pid: int | None = None) -> Relaunch:
    """Download the release for `method` and get the hand-over ready. Runs on a worker thread."""
    asset = release.asset_for(method)
    if asset is None:
        raise UpdateError(f"Version {release.version} has no download for this computer yet.")
    folder = folder or program_dir()
    pid = os.getpid() if pid is None else pid
    work = Path(tempfile.mkdtemp(prefix="alter_ego_update_"))
    try:
        target = work / asset.name
        download(asset, target, progress, cancelled)
        if method is Method.WINDOWS_SETUP:
            # The installer replaces the folder itself and, with /RELAUNCH=1, starts the new version.
            return Relaunch([str(target), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                             "/CLOSEAPPLICATIONS", "/RELAUNCH=1"], cwd=work)
        progress("Unpacking the new version...", -1)
        unpacked = _unpack(target, work / "new")
        target.unlink()
        new_program = _find_program_folder(unpacked, method)
        if method is Method.WINDOWS_PORTABLE:
            script = work / "update.cmd"
            script.write_text(windows_script(pid, new_program, folder, work), encoding="utf-8")
            return Relaunch(["cmd.exe", "/c", str(script)], cwd=work.parent)
        script = work / "update.sh"
        script.write_text(linux_script(pid, new_program, folder, work), encoding="utf-8")
        script.chmod(0o755)
        return Relaunch(["/bin/sh", str(script)], cwd=work.parent)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def download(asset: Asset, target: Path, progress: Progress, cancelled: Callable[[], bool] = lambda: False) -> None:
    """Download with percent progress; a partial file never stays behind."""
    label = "Downloading the new version..."
    partial = target.with_suffix(target.suffix + ".part")
    try:
        request = urllib.request.Request(asset.url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=60) as response, open(partial, "wb") as out:
            total = int(response.headers.get("Content-Length") or asset.size or 0)
            done, last = 0, -2
            while True:
                if cancelled():
                    raise UpdateError("The update was cancelled.")
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                percent = min(100, 100 * done // total) if total else -1
                if percent != last:
                    last = percent
                    progress(label, percent)
        if asset.size and done != asset.size:
            raise UpdateError("The download was cut short. Try again in a moment.")
        os.replace(partial, target)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise UpdateError(
            f"I couldn't download the new version: {getattr(error, 'reason', error)}. "
            "Check the internet connection and try again from AI -> Check for updates now."
        ) from None
    finally:
        try:
            partial.unlink()
        except OSError:
            pass


def _unpack(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True)
    try:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.namelist():
                    if not _inside(destination, destination / member):
                        raise UpdateError("The download looks wrong (a file points outside its folder).")
                bundle.extractall(destination)
        else:
            with tarfile.open(archive, "r:gz") as bundle:
                bundle.extractall(destination, filter="data")  # "data" refuses links and paths that escape.
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as error:
        raise UpdateError(f"I couldn't unpack the new version: {error}") from None
    return destination


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _find_program_folder(unpacked: Path, method: Method) -> Path:
    """The AlterEgo/ folder in the download: at the top of the zip, one level down in the tar.gz."""
    exe = "AlterEgo.exe" if method is Method.WINDOWS_PORTABLE else "AlterEgo"
    for candidate in [unpacked / "AlterEgo", *unpacked.glob("*/AlterEgo")]:
        if (candidate / exe).is_file():
            return candidate
    raise UpdateError("The download doesn't contain the program. Try again later.")


def linux_script(pid: int, new_program: Path, folder: Path, work: Path) -> str:
    new, dest, tmp = (shlex.quote(str(path)) for path in (new_program, folder, work))
    return f"""#!/bin/sh
# Alter Ego's updater: waits for the old version to quit, swaps the program folder, starts the new one.
while kill -0 {pid} 2>/dev/null; do sleep 1; done
rm -rf {dest}/_internal
cp -a {new}/. {dest}/
chmod +x {dest}/AlterEgo
rm -rf {tmp}
nohup {dest}/AlterEgo >/dev/null 2>&1 &
"""


def windows_script(pid: int, new_program: Path, folder: Path, work: Path) -> str:
    new, dest, tmp = (str(path).replace("%", "%%") for path in (new_program, folder, work))
    return f"""@echo off
rem Alter Ego's updater: waits for the old version to quit, swaps the program folder, starts the new one.
:wait
tasklist /FI "PID eq {pid}" /NH 2>NUL | find /I "AlterEgo" >NUL && (timeout /t 1 /nobreak >NUL & goto wait)
rmdir /s /q "{dest}\\_internal"
robocopy "{new}" "{dest}" /E /NFL /NDL /NJH /NJS /NP >NUL
start "" "{dest}\\AlterEgo.exe"
rmdir /s /q "{tmp}\\new"
(goto) 2>NUL & rmdir /s /q "{tmp}"
"""


# ----- Worker thread -----

class UpdateJob(QThread):
    """Runs one function off the GUI thread; the results arrive as queued signals."""

    progress = Signal(str, int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, work: Callable[[Progress, Callable[[], bool]], object]):
        super().__init__()
        self._work = work

    def run(self) -> None:
        try:
            self.succeeded.emit(self._work(self.progress.emit, self.isInterruptionRequested))
        except UpdateError as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 - an unknown failure must not take the app down
            traceback.print_exc()
            self.failed.emit(f"The update failed: {type(error).__name__}: {error}")
