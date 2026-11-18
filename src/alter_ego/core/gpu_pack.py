"""The GPU pack: CUDA PyTorch for the downloaded app, so the voice runs on an NVIDIA card.

The release downloads bundle CPU PyTorch: the CUDA build is about 3 GB, too much
for everyone to download (see AI/DECISIONS.md). On a computer with an NVIDIA
driver the app offers it as an extra, only when the user asks:

    download.pytorch.org/whl/cu128 --> data folder/gpu/site-packages (torch, torchaudio, torchvision)
                                      checked against the sha256 on the index page

The voice helper process (voice/server.py) is started with the pack's folder in
ALTER_EGO_GPU_SITE; prefer_pack() then makes `import torch` find the pack before
the bundled CPU build, in that process only. After installing, a probe run of the
helper must report a CUDA card, or the pack is removed again.

Windows only for now: there the CUDA wheels carry their own CUDA libraries; on
Linux they need about ten separate NVIDIA packages. The versions always match the
bundled ones (read from their version.py), so nothing else in the build changes.
Standard library only.
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .machine import has_nvidia_driver
from ..providers.https import urlopen
from ..settings.config import data_dir

CUDA_TAG = "cu128"
INDEX_URL = "https://download.pytorch.org/whl/" + CUDA_TAG + "/{package}/"
PACKAGES = ("torch", "torchaudio", "torchvision")
PACK_FOLDER = "gpu"
MARKER = "ok"
PYTHON_TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"
PLATFORM_TAG = "win_amd64"
CHUNK = 1 << 20
TIMEOUT_S = 60
DISK_FACTOR = 2.6  # The wheels plus their unpacked files, with some room to spare.

Progress = Callable[[str, int], None]  # text, percent (-1 = unknown)


class GpuPackError(Exception):
    """The pack could not be downloaded or used. The message is shown to the user."""


@dataclass(frozen=True)
class Wheel:
    package: str
    filename: str
    url: str
    sha256: str
    size: int = 0


# ----- Where it lives, and whether to offer it -----

def pack_dir() -> Path:
    return data_dir() / PACK_FOLDER


def site_dir() -> Path:
    return pack_dir() / "site-packages"


def installed() -> bool:
    return (pack_dir() / MARKER).is_file() and (site_dir() / "torch").is_dir()


def supported() -> bool:
    """Only the packaged Windows build gets the pack; from source, pip installs CUDA PyTorch."""
    return getattr(sys, "frozen", False) and sys.platform == "win32"


def offered() -> bool:
    """Show the download? A packaged Windows build, an NVIDIA driver, and no pack yet."""
    return supported() and has_nvidia_driver() and not installed() and bool(bundled_versions())


def bundled_versions() -> dict[str, str]:
    """{"torch": "2.11.0", ...}: the versions bundled with this build, without importing them."""
    versions: dict[str, str] = {}
    for package in PACKAGES:
        try:
            spec = importlib.util.find_spec(package)
        except (ImportError, ValueError):
            spec = None
        if spec is None or not spec.submodule_search_locations:
            continue
        version_file = Path(list(spec.submodule_search_locations)[0]) / "version.py"
        try:
            match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", version_file.read_text(encoding="utf-8"))
        except OSError:
            continue
        if match:
            versions[package] = match.group(1).split("+")[0]
    return versions


# ----- Finding the wheels -----

_ANCHOR = re.compile(r"<a\s[^>]*href=\"([^\"]+)\"[^>]*>([^<]+)</a>", re.IGNORECASE)


def parse_index(page: str, base_url: str) -> list[tuple[str, str, str]]:
    """(filename, url without fragment, sha256) for every wheel linked on a PyTorch index page."""
    entries = []
    for href, text in _ANCHOR.findall(page):
        url = urllib.parse.urljoin(base_url, href.replace("&amp;", "&"))
        url, _, fragment = url.partition("#")
        sha = fragment.split("=", 1)[1] if fragment.startswith("sha256=") else ""
        entries.append((text.strip(), url, sha))
    return entries


def pick_wheel(entries: list[tuple[str, str, str]], package: str, version: str,
               python_tag: str = PYTHON_TAG, platform_tag: str = PLATFORM_TAG) -> Wheel | None:
    wanted = f"{package}-{version}+{CUDA_TAG}-{python_tag}-{python_tag}-{platform_tag}.whl"
    for filename, url, sha in entries:
        if urllib.parse.unquote(filename) == wanted and sha:
            return Wheel(package, wanted, url, sha)
    return None


def find_wheels(fetch: Callable[[str], str] | None = None, size_of: Callable[[str], int] | None = None,
                versions: dict[str, str] | None = None) -> list[Wheel]:
    """The CUDA wheels matching the bundled versions, with their download sizes."""
    fetch = fetch or _fetch_text
    size_of = size_of or _content_length
    versions = bundled_versions() if versions is None else versions
    if not versions.get("torch"):
        raise GpuPackError("this build has no PyTorch to swap for the GPU version.")
    wheels = []
    for package, version in versions.items():
        index = INDEX_URL.format(package=package)
        try:
            wheel = pick_wheel(parse_index(fetch(index), index), package, version)
        except (urllib.error.URLError, OSError) as error:
            raise GpuPackError(f"I couldn't reach download.pytorch.org ({getattr(error, 'reason', error)}).") from None
        if wheel is None:
            raise GpuPackError(f"there is no GPU build of {package} {version} for this computer.")
        wheels.append(Wheel(wheel.package, wheel.filename, wheel.url, wheel.sha256, size_of(wheel.url)))
    return wheels


def _fetch_text(url: str) -> str:
    with urlopen(urllib.request.Request(url, headers={"User-Agent": "AlterEgo-Companion"}), timeout=TIMEOUT_S) as response:
        return response.read().decode("utf-8", errors="replace")


def _content_length(url: str) -> int:
    try:
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "AlterEgo-Companion"})
        with urlopen(request, timeout=TIMEOUT_S) as response:
            return int(response.headers.get("Content-Length") or 0)
    except (urllib.error.URLError, OSError, ValueError):
        return 0


# ----- Installing -----

def install(wheels: list[Wheel], progress: Progress, cancelled: Callable[[], bool],
            opener: Callable = None, probe: Callable[[Path], dict] | None = None) -> str:
    """Download, check and unpack the wheels, then make sure the voice helper sees the GPU."""
    opener = opener or (lambda request: urlopen(request, timeout=TIMEOUT_S))
    folder = pack_dir()
    folder.mkdir(parents=True, exist_ok=True)
    total = sum(w.size for w in wheels)
    free = shutil.disk_usage(folder).free
    if total and free < total * DISK_FACTOR:
        raise GpuPackError(f"there isn't enough free disk space (about {_gb(total * DISK_FACTOR)} needed).")
    downloads = folder / "downloads"
    downloads.mkdir(exist_ok=True)
    done = 0
    files = []
    try:
        for wheel in wheels:
            target = downloads / wheel.filename
            done = _download(wheel, target, opener, progress, cancelled, done, total)
            files.append(target)
        progress("Unpacking the GPU pack...", -1)
        unpacked = folder / "site-packages.part"
        shutil.rmtree(unpacked, ignore_errors=True)
        for target in files:
            if cancelled():
                raise GpuPackError("cancelled.")
            with zipfile.ZipFile(target) as archive:
                _extract(archive, unpacked)
        shutil.rmtree(site_dir(), ignore_errors=True)
        os.replace(unpacked, site_dir())
    finally:
        shutil.rmtree(downloads, ignore_errors=True)
    progress("Checking that my voice can use the GPU...", -1)
    result = (probe or _probe)(site_dir())
    if not result.get("cuda"):
        remove()
        reason = result.get("error") or "PyTorch didn't find a CUDA card"
        raise GpuPackError(f"the GPU pack didn't work on this computer ({reason}), so I removed it again.")
    (folder / MARKER).write_text(json.dumps(result), encoding="utf-8")
    return str(result.get("name") or "your GPU")


def remove() -> None:
    shutil.rmtree(pack_dir(), ignore_errors=True)


def _download(wheel: Wheel, target: Path, opener, progress: Progress, cancelled: Callable[[], bool],
              done: int, total: int) -> int:
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    request = urllib.request.Request(wheel.url, headers={"User-Agent": "AlterEgo-Companion"})
    try:
        with opener(request) as response, open(partial, "wb") as out:
            while True:
                if cancelled():
                    raise GpuPackError("cancelled.")
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                percent = int(100 * done / total) if total else -1
                progress(f"Downloading the GPU pack ({wheel.package})... {_gb(done)} of {_gb(total)}", percent)
    except (urllib.error.URLError, OSError) as error:
        partial.unlink(missing_ok=True)
        raise GpuPackError(f"the download stopped ({getattr(error, 'reason', error)}). Try again later.") from None
    if digest.hexdigest() != wheel.sha256.lower():
        partial.unlink(missing_ok=True)
        raise GpuPackError(f"the downloaded {wheel.package} didn't match its checksum, so I didn't use it.")
    os.replace(partial, target)
    return done


def _extract(archive: zipfile.ZipFile, folder: Path) -> None:
    root = folder.resolve()
    for member in archive.infolist():
        target = (folder / member.filename).resolve()
        if target != root and root not in target.parents:  # A path that leaves the folder: never written.
            raise GpuPackError("the GPU pack had a file in a strange place, so I didn't use it.")
    archive.extractall(folder)


def _probe(site: Path) -> dict:
    """Run the voice helper with the pack and ask whether PyTorch sees a CUDA card."""
    from ..voice.server import GPU_SITE_ENV, server_command

    env = dict(os.environ, **{GPU_SITE_ENV: str(site)})
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        done = subprocess.run(server_command(probe=True), stdin=subprocess.DEVNULL, capture_output=True,
                              env=env, timeout=300, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"cuda": False, "error": str(error)}
    for line in reversed(done.stdout.decode("utf-8", errors="replace").splitlines()):
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            if result.get("cuda") and not _inside(Path(str(result.get("file", ""))), site):
                return {"cuda": False, "error": "the bundled PyTorch was used instead of the pack"}
            return result
    return {"cuda": False, "error": "no answer from the check"}


def _gb(size: float) -> str:
    return f"{size / 1024 ** 3:.1f} GB"


def _inside(file: Path, folder: Path) -> bool:
    """Is `file` in `folder`? Compared as real paths: Windows may spell the same folder two ways
    (C:\\Users\\RUNNER~1 and C:\\Users\\runneradmin), so comparing the text is not enough."""
    try:
        file, folder = file.resolve(), folder.resolve()
    except OSError:
        return False
    return folder in file.parents


# ----- Using it (in the voice helper, before PyTorch is imported) -----

class _PackFinder(importlib.abc.MetaPathFinder):
    """Finds the packages that are in the pack (torch, torchaudio, ...) there, before anywhere else."""

    def __init__(self, site: Path):
        self.site = str(site)
        self.tops = {p.name.removesuffix(".py") for p in site.iterdir()
                     if p.is_dir() and not p.name.endswith((".dist-info", ".data")) or p.suffix == ".py"}

    def find_spec(self, fullname, path=None, target=None):
        top = fullname.partition(".")[0]
        if top not in self.tops:
            return None
        if "." not in fullname:
            return importlib.machinery.PathFinder.find_spec(fullname, [self.site])
        if path and str(list(path)[0]).startswith(self.site):
            return importlib.machinery.PathFinder.find_spec(fullname, path)
        return None


def prefer_pack(site: Path) -> bool:
    """Make the pack's packages win over the bundled ones in this process. False if there is no pack."""
    if not (site / "torch").is_dir():
        return False
    if not any(isinstance(finder, _PackFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _PackFinder(site))
    return True
