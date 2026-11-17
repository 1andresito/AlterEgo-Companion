"""Tests for updating Alter Ego: the version check, the download, and the hand-over script.

Nothing real is downloaded or replaced: a fake web server plays GitHub, the
"releases" are small archives built here, and the Linux hand-over script is run
against a scratch program folder.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from alter_ego.core import updates  # noqa: E402
from alter_ego.core.updates import Asset, Method, Release, UpdateError  # noqa: E402

FILES: dict[str, bytes] = {}  # path on the fake server -> body


class FakeGitHub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = FILES.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def tar_gz(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in entries.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


class VersionTests(unittest.TestCase):
    def test_newer_versions_compare_by_number_not_text(self):
        self.assertTrue(updates.is_newer("v0.10.0", "0.9.3"))
        self.assertTrue(updates.is_newer("0.8.0", "0.7.0"))
        self.assertFalse(updates.is_newer("v0.7.0", "0.7.0"))
        self.assertFalse(updates.is_newer("0.8", "0.8.0"))
        self.assertFalse(updates.is_newer("0.6.9", "0.7.0"))
        self.assertFalse(updates.is_newer("nightly", "0.7.0"))

    def test_a_skipped_version_is_only_offered_when_checking_by_hand(self):
        release = Release("0.8.0", "https://example.invalid")
        self.assertTrue(updates.should_offer(release, "", manual=False, local="0.7.0"))
        self.assertFalse(updates.should_offer(release, "0.8.0", manual=False, local="0.7.0"))
        self.assertTrue(updates.should_offer(release, "0.8.0", manual=True, local="0.7.0"))
        self.assertFalse(updates.should_offer(None, "", manual=True, local="0.7.0"))
        self.assertFalse(updates.should_offer(release, "", manual=True, local="0.8.0"))


class MethodTests(unittest.TestCase):
    def test_running_from_source_never_updates_itself(self):
        self.assertIsNone(updates.install_method(frozen=False))

    def test_the_kind_of_copy_picks_the_download(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            self.assertIs(updates.install_method(True, "win32", path), Method.WINDOWS_PORTABLE)
            self.assertIs(updates.install_method(True, "linux", path), Method.LINUX)
            (path / "unins000.exe").write_bytes(b"")
            self.assertIs(updates.install_method(True, "win32", path), Method.WINDOWS_SETUP)
        self.assertEqual(updates.asset_name(Method.WINDOWS_SETUP, "0.8.0"), "AlterEgo-Setup-v0.8.0.exe")
        self.assertEqual(updates.asset_name(Method.LINUX, "0.8.0"), "AlterEgo-v0.8.0-linux-x86_64.tar.gz")


class CheckAndDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FILES.clear()
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)

    def tearDown(self):
        self.scratch.cleanup()

    def publish(self, version: str, files: dict[str, bytes]) -> None:
        FILES["/releases/latest"] = json.dumps({
            "tag_name": f"v{version}",
            "html_url": f"{self.base}/page",
            "body": "What's new",
            "assets": [
                {"name": name, "browser_download_url": f"{self.base}/{name}", "size": len(data)}
                for name, data in files.items()
            ],
        }).encode()
        for name, data in files.items():
            FILES[f"/{name}"] = data

    def test_the_latest_release_is_read_from_github(self):
        self.publish("0.8.0", {"AlterEgo-Setup-v0.8.0.exe": b"setup"})
        release = updates.check_latest(f"{self.base}/releases/latest")
        self.assertEqual(release.version, "0.8.0")
        self.assertEqual(release.notes, "What's new")
        self.assertEqual(release.asset_for(Method.WINDOWS_SETUP).size, 5)
        self.assertIsNone(release.asset_for(Method.LINUX))

    def test_no_release_yet_is_not_an_error(self):
        self.assertIsNone(updates.check_latest(f"{self.base}/releases/latest"))

    def test_an_unreachable_server_is_explained(self):
        with self.assertRaises(UpdateError):
            updates.check_latest("http://127.0.0.1:9/releases/latest")

    def test_the_installed_windows_copy_runs_the_new_installer_silently(self):
        self.publish("0.8.0", {"AlterEgo-Setup-v0.8.0.exe": b"setup"})
        release = updates.check_latest(f"{self.base}/releases/latest")
        relaunch = updates.prepare(release, Method.WINDOWS_SETUP, lambda *_: None, folder=self.root, pid=1)
        installer = Path(relaunch.command[0])
        self.addCleanup(lambda: __import__("shutil").rmtree(installer.parent, ignore_errors=True))
        self.assertEqual(installer.read_bytes(), b"setup")
        self.assertIn("/VERYSILENT", relaunch.command)
        self.assertIn("/RELAUNCH=1", relaunch.command)

    def test_a_cancelled_download_leaves_nothing_behind(self):
        target = self.root / "big.exe"
        FILES["/big.exe"] = b"x" * 10
        with self.assertRaises(UpdateError):
            updates.download(Asset("big.exe", f"{self.base}/big.exe", 10), target, lambda *_: None, lambda: True)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_short_download_is_refused(self):
        FILES["/short.exe"] = b"abc"
        with self.assertRaises(UpdateError):
            updates.download(Asset("short.exe", f"{self.base}/short.exe", 99), self.root / "short.exe", lambda *_: None)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_zip_that_writes_outside_its_folder_is_refused(self):
        self.publish("0.8.0", {"AlterEgo-v0.8.0-windows-portable.zip": zip_bytes({"../evil.txt": b"no"})})
        release = updates.check_latest(f"{self.base}/releases/latest")
        with self.assertRaises(UpdateError):
            updates.prepare(release, Method.WINDOWS_PORTABLE, lambda *_: None, folder=self.root, pid=1)

    def test_the_portable_windows_zip_is_unpacked_and_a_script_swaps_it_in(self):
        self.publish("0.8.0", {"AlterEgo-v0.8.0-windows-portable.zip": zip_bytes({"AlterEgo/AlterEgo.exe": b"new"})})
        release = updates.check_latest(f"{self.base}/releases/latest")
        relaunch = updates.prepare(release, Method.WINDOWS_PORTABLE, lambda *_: None, folder=self.root, pid=4242)
        script = Path(relaunch.command[-1])
        self.addCleanup(lambda: __import__("shutil").rmtree(script.parent, ignore_errors=True))
        text = script.read_text()
        self.assertIn('PID eq 4242', text)
        self.assertIn(f'start "" "{self.root}\\AlterEgo.exe"', text)
        self.assertEqual((script.parent / "new" / "AlterEgo" / "AlterEgo.exe").read_bytes(), b"new")

    @unittest.skipUnless(sys.platform.startswith("linux"), "runs the Linux hand-over script")
    def test_linux_update_replaces_the_program_and_starts_it_again(self):
        program = self.root / "alter-ego"
        (program / "_internal").mkdir(parents=True)
        (program / "_internal" / "old_only.txt").write_text("old")
        (program / "AlterEgo").write_text("#!/bin/sh\necho old\n")
        started = self.root / "started.txt"
        new_exe = f"#!/bin/sh\necho started > {started}\n".encode()
        name = "AlterEgo-v0.8.0-linux-x86_64"
        self.publish("0.8.0", {f"{name}.tar.gz": tar_gz({
            f"{name}/AlterEgo/AlterEgo": new_exe,
            f"{name}/AlterEgo/_internal/new.txt": b"new",
            f"{name}/install.sh": b"",
        })})
        release = updates.check_latest(f"{self.base}/releases/latest")
        progress: list[tuple[str, int]] = []
        relaunch = updates.prepare(release, Method.LINUX, lambda text, pct: progress.append((text, pct)),
                                   folder=program, pid=999_999_999)  # A process that isn't running.
        self.assertIn(100, [pct for _text, pct in progress])
        work = Path(relaunch.command[-1]).parent
        subprocess.run(relaunch.command, check=True, timeout=30)
        for _ in range(100):  # The new program is started in the background.
            if started.exists():
                break
            threading.Event().wait(0.05)
        self.assertEqual((program / "AlterEgo").read_bytes(), new_exe)
        self.assertFalse((program / "_internal" / "old_only.txt").exists())
        self.assertEqual((program / "_internal" / "new.txt").read_text(), "new")
        self.assertTrue(started.exists())
        self.assertFalse(work.exists())
        self.assertTrue(os.access(program / "AlterEgo", os.X_OK))


PROMPT_SCRIPT = """
import sys, tempfile, time
from pathlib import Path
from unittest import mock
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QMessageBox
from alter_ego.core import updates
from alter_ego.core.updates import Asset, Method, Release, Relaunch
from alter_ego.settings.config import Config
from alter_ego.update_prompt import UpdatePrompt

button = sys.argv[2]
app = QApplication([])
name = updates.asset_name(Method.LINUX, "9.0.0")
release = Release("9.0.0", "https://example.invalid", "notes", {name: Asset(name, "unused", 1_500_000_000)})
asked, started, quit_called = [], [], []

def click(box):
    asked.append(box.text())
    for candidate in box.buttons():
        if candidate.text() == button:
            candidate.click()
    return 0

class FakeRelaunch(Relaunch):
    def start(self):
        started.append(self.command)

def fake_prepare(release, method, progress, cancelled):
    progress("Downloading the new version...", 50)
    return FakeRelaunch(["new-version"])

config = Config(Path(tempfile.mkdtemp()) / "config.json")
with mock.patch.object(updates, "check_latest", return_value=release), \\
     mock.patch.object(updates, "prepare", fake_prepare), \\
     mock.patch.object(QMessageBox, "exec", click):
    prompt = UpdatePrompt(config, lambda: quit_called.append(True))
    prompt.method = Method.LINUX
    prompt.check()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not quit_called:
        app.processEvents()
        if asked and not prompt.busy and button != "Update now":
            break
        time.sleep(0.01)
    prompt.wait()

assert "v9.0.0" in asked[0] and "1.5 GB" in asked[0], asked
if button == "Update now":
    assert started == [["new-version"]] and quit_called, (started, quit_called)
else:
    assert config.get("updates", "skipped") == "9.0.0" and not started and not quit_called
print("ok")
"""


class PromptTests(unittest.TestCase):
    """The question and the hand-over in the app, with the network and the dialogs faked."""

    def run_prompt(self, button: str) -> None:
        # A separate process, because the other tests already made a non-GUI application object here.
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", PROMPT_SCRIPT, str(PROJECT_ROOT / "src"), button],
                                capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_yes_downloads_starts_the_new_version_and_quits(self):
        self.run_prompt("Update now")

    def test_skip_is_remembered_and_nothing_is_downloaded(self):
        self.run_prompt("Skip this version")


if __name__ == "__main__":
    unittest.main()
