"""Tests for the first-run setup: installing Ollama, choosing a model, the voice download.

Nothing real is downloaded or installed: a fake web server hands out a fake
"installer" (a Python script run with the test's own interpreter), a fake Ollama
server answers the model requests, and a fake voice stands in for Kokoro.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from alter_ego.core.first_run import (  # noqa: E402
    MODEL_CHOICES,
    SetupChoices,
    SetupPlan,
    SetupRunner,
    SetupStep,
    has_model,
    make_plan,
)
from alter_ego.providers import ollama_install  # noqa: E402
from alter_ego.providers.base import ProviderError  # noqa: E402
from alter_ego.settings.config import Config  # noqa: E402
from test_providers import FakeOllamaHandler  # noqa: E402

# Signals and threads need an application object; one per test process is enough.
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

# The fake installer: "installs" Ollama by writing the file named in FAKE_INSTALL_TARGET.
FAKE_INSTALLER = textwrap.dedent("""
    import os, sys
    target = os.environ["FAKE_INSTALL_TARGET"]
    with open(target, "w") as out:
        out.write(" ".join(sys.argv[1:]))
    sys.exit(int(os.environ.get("FAKE_INSTALL_EXIT", "0")))
""").encode()


def process_events_until(condition, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        _app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class FakeDownloadHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/OllamaSetup.exe":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(FAKE_INSTALLER)))
        self.end_headers()
        self.wfile.write(FAKE_INSTALLER)


class FakeVoice:
    """Stands in for the Kokoro/RVC synthesizer: only what the setup uses."""

    def __init__(self, error: str | None = None):
        self.error = error
        self.needs_download = True
        self.download_size_mb = 873
        self.prepared = 0

    def prepare(self) -> str:
        self.prepared += 1
        if self.error:
            raise RuntimeError(self.error)
        self.needs_download = False
        return "My voice is downloaded and ready."


def serve(handler) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class OllamaInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.base_url = serve(FakeDownloadHandler)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.target = self.folder / "ollama"
        os.environ["FAKE_INSTALL_TARGET"] = str(self.target)
        os.environ.pop("FAKE_INSTALL_EXIT", None)
        self._saved = (ollama_install.WINDOWS_INSTALLER_URL, list(ollama_install.INSTALLER_PREFIX))
        ollama_install.WINDOWS_INSTALLER_URL = self.base_url + "/OllamaSetup.exe"
        ollama_install.INSTALLER_PREFIX[:] = [sys.executable]

    def tearDown(self):
        ollama_install.WINDOWS_INSTALLER_URL, prefix = self._saved
        ollama_install.INSTALLER_PREFIX[:] = prefix
        os.environ.pop("FAKE_INSTALL_TARGET", None)
        os.environ.pop("FAKE_INSTALL_EXIT", None)

    def test_download_reports_progress_and_leaves_no_partial_file(self):
        progress = []
        target = self.folder / "setup.exe"
        ollama_install.download(self.base_url + "/OllamaSetup.exe", target, lambda t, p: progress.append(p), "x")
        self.assertEqual(target.read_bytes(), FAKE_INSTALLER)
        self.assertEqual(progress[-1], 100)
        self.assertFalse(target.with_suffix(".exe.part").exists())

    def test_failed_download_is_explained_and_cleaned_up(self):
        target = self.folder / "setup.exe"
        with self.assertRaises(ProviderError) as caught:
            ollama_install.download(self.base_url + "/missing.exe", target, lambda t, p: None, "x")
        self.assertIn("couldn't download Ollama", str(caught.exception))
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_windows_installer_is_downloaded_and_run_silently(self):
        progress = []
        ollama_install._install_windows(lambda text, percent: progress.append(text))
        self.assertIn("/VERYSILENT", self.target.read_text())
        self.assertIn("Downloading Ollama...", progress)
        self.assertTrue(any("Installing Ollama" in text for text in progress))

    @unittest.skipUnless(sys.platform == "win32", "install() takes the Windows route only on Windows")
    def test_install_confirms_that_ollama_is_there_afterwards(self):
        ollama_install.install(lambda text, percent: None, command=str(self.target))
        self.assertTrue(ollama_install.is_installed(str(self.target)))

    def test_installer_error_is_explained(self):
        os.environ["FAKE_INSTALL_EXIT"] = "3"
        with self.assertRaises(ProviderError) as caught:
            ollama_install._install_windows(lambda text, percent: None)
        self.assertIn("code 3", str(caught.exception))

    def test_linux_without_pkexec_gives_the_terminal_command(self):
        with mock.patch.object(ollama_install.sys, "platform", "linux"), \
                mock.patch.object(ollama_install.shutil, "which", return_value=None):
            self.assertFalse(ollama_install.can_install())
            with self.assertRaises(ProviderError) as caught:
                ollama_install._install_linux(lambda text, percent: None)
        self.assertIn(ollama_install.LINUX_INSTALL_COMMAND, str(caught.exception))

    def test_nothing_happens_when_ollama_is_already_installed(self):
        self.target.write_text("installed")
        ollama_install.WINDOWS_INSTALLER_URL = self.base_url + "/missing.exe"  # Would fail if it were used.
        ollama_install.install(lambda text, percent: None, command=str(self.target))


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.base_url = serve(FakeOllamaHandler)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeOllamaHandler.models = ["llama3.2:latest"]
        FakeOllamaHandler.pulled.clear()
        self.config = Config(Path(tempfile.mkdtemp()) / "config.json")
        self.config.set("ollama", "base_url", self.base_url)
        self.config.set("ollama", "command", sys.executable)  # Any file that exists counts as installed.

    def test_choices_become_steps_in_order(self):
        self.assertEqual(SetupChoices().steps(), [])
        self.assertEqual(SetupChoices(True, "llama3.2", True).steps(),
                         [SetupStep.OLLAMA, SetupStep.MODEL, SetupStep.VOICE])
        self.assertEqual(SetupChoices(model="", voice=True).steps(), [SetupStep.VOICE])

    def test_model_names_match_with_or_without_tag(self):
        self.assertTrue(has_model(["llama3.2:latest"], "llama3.2"))
        self.assertTrue(has_model(["llama3.2:1b"], "llama3.2:1b"))
        self.assertFalse(has_model(["llama3.2:latest"], "llama3.2:1b"))
        self.assertEqual(MODEL_CHOICES[0].name, "llama3.2")

    def test_nothing_missing_means_no_setup(self):
        plan = make_plan(self.config, None)
        self.assertTrue(plan.uses_ollama and plan.ollama_installed)
        self.assertEqual(plan.models, ["llama3.2:latest"])
        self.assertFalse(plan.anything_missing)

    def test_missing_model_and_voice_are_found(self):
        FakeOllamaHandler.models = []
        plan = make_plan(self.config, FakeVoice())
        self.assertTrue(plan.needs_model)
        self.assertTrue(plan.voice_needed)
        self.assertEqual(plan.voice_size_mb, 873)

    def test_voice_switched_off_is_not_offered(self):
        self.config.set("voice", "enabled", False)
        self.assertFalse(make_plan(self.config, FakeVoice()).voice_needed)

    def test_other_providers_skip_ollama(self):
        self.config.provider = "claude_code"
        plan = make_plan(self.config, None)
        self.assertFalse(plan.uses_ollama)
        self.assertFalse(plan.needs_ollama or plan.needs_model)

    def test_setup_done_is_saved(self):
        self.assertFalse(self.config.setup_done)
        self.assertFalse(self.config.get("ollama", "auto_pull"))  # The setup asks; nothing is pulled silently.
        self.config.set("setup", "done", True)
        self.config.save()
        self.assertTrue(Config.load(self.config.path).setup_done)


class RunnerTests(PlanTests):
    def run_setup(self, choices: SetupChoices, voice: FakeVoice | None = None) -> tuple[SetupRunner, list]:
        events: list = []
        runner = SetupRunner(self.config, voice)
        runner.step_done.connect(lambda step, text: events.append(("done", step, text)))
        runner.step_failed.connect(lambda step, text: events.append(("failed", step, text)))
        finished = []
        runner.finished.connect(lambda: finished.append(True))
        plan = make_plan(self.config, voice)
        self.assertTrue(runner.start(plan, choices))
        self.assertTrue(process_events_until(lambda: bool(finished), 10))
        self.assertFalse(runner.running)
        return runner, events

    def test_chosen_model_is_downloaded_and_saved(self):
        FakeOllamaHandler.models = []
        _runner, events = self.run_setup(SetupChoices(model="llama3.2:1b"))
        self.assertEqual(FakeOllamaHandler.pulled, ["llama3.2:1b"])
        self.assertEqual(events[0][:2], ("done", SetupStep.MODEL))
        self.assertEqual(self.config.get("ollama", "model"), "llama3.2:1b")
        self.assertEqual(Config.load(self.config.path).get("ollama", "default_model"), "llama3.2:1b")

    def test_a_model_already_there_is_not_downloaded_again(self):
        _runner, events = self.run_setup(SetupChoices(model="llama3.2"))
        self.assertEqual(FakeOllamaHandler.pulled, [])
        self.assertIn("already there", events[0][2])

    def test_declining_the_model_downloads_nothing(self):
        FakeOllamaHandler.models = []
        voice = FakeVoice()
        _runner, events = self.run_setup(SetupChoices(model="", voice=True), voice)
        self.assertEqual(FakeOllamaHandler.pulled, [])
        self.assertEqual([event[1] for event in events], [SetupStep.VOICE])
        self.assertEqual(self.config.get("ollama", "model"), "")

    def test_a_failed_step_does_not_stop_the_next(self):
        FakeOllamaHandler.models = []
        voice = FakeVoice()
        runner, events = self.run_setup(SetupChoices(model="broken", voice=True), voice)
        self.assertEqual(events[0][:2], ("failed", SetupStep.MODEL))
        self.assertEqual(events[1][:2], ("done", SetupStep.VOICE))
        self.assertEqual(voice.prepared, 1)
        self.assertFalse(runner.results[SetupStep.MODEL][0])
        self.assertTrue(runner.results[SetupStep.VOICE][0])

    def test_voice_failure_is_reported(self):
        _runner, events = self.run_setup(SetupChoices(voice=True), FakeVoice(error="disk full"))
        self.assertEqual(events, [("failed", SetupStep.VOICE, "disk full")])


WIZARD_SCRIPT = textwrap.dedent("""
    import sys
    sys.path.insert(0, sys.argv[1])
    from PySide6.QtWidgets import QApplication
    from alter_ego.core.first_run import SetupPlan, SetupRunner, SetupStep
    from alter_ego.settings.config import Config
    from alter_ego.setup_wizard import SetupWizard

    app = QApplication([])
    config = Config(None)
    plan = SetupPlan(uses_ollama=True, ollama_installed=False, can_install_ollama=True, models=None,
                     voice_needed=True, voice_size_mb=873)
    runner = SetupRunner(config, None)
    wizard = SetupWizard(plan, runner)
    assert wizard.page_index == 0
    choices = wizard.choices()
    assert choices.install_ollama and choices.model == "llama3.2" and choices.voice, choices
    wizard._ollama_box.setChecked(False)
    assert wizard.choices().model == "", "no Ollama means no model"
    completed = []
    wizard.completed.connect(lambda: completed.append(True))
    wizard.close()
    assert completed == [True]

    ready = SetupWizard(SetupPlan(uses_ollama=True, ollama_installed=True, can_install_ollama=True,
                                  models=["llama3.2:latest"]), runner)
    assert ready.page_index == 2, "nothing missing goes straight to the last page"
    print("ok")
""")


class WizardTests(unittest.TestCase):
    def test_pages_and_choices(self):
        # A separate process, because the other tests already made a non-GUI application object here.
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", WIZARD_SCRIPT, str(PROJECT_ROOT / "src")],
                                capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
