"""Tests for the voice in its own process (voice/remote.py, voice/server.py) and the GPU pack (core/gpu_pack.py).

The helper is the real one (python main.py --voice-server) with ALTER_EGO_FAKE_VOICE=1,
which speaks a plain tone, so no models are needed. GPU pack downloads use fakes.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import alter_ego.providers  # noqa: E402,F401  (import order: see core/tools.py)
from alter_ego.core import gpu_pack  # noqa: E402
from alter_ego.voice.remote import RemoteVoice  # noqa: E402
from alter_ego.voice.server import FAKE_CRASH_ENV, FAKE_ENV, server_command  # noqa: E402
from alter_ego.voice.synthesizer import SynthesisError, Synthesizer  # noqa: E402


class LocalStandIn(Synthesizer):
    """The unloaded local engine RemoteVoice asks the cheap questions."""

    id, label, shape_voice = "fake", "Fake", False

    def __init__(self, needs_download=False):
        self._needs = needs_download
        self.downloads = 0

    def describe(self):
        return "fake local voice"

    @property
    def needs_download(self):
        return self._needs

    def download(self):
        self.downloads += 1
        self._needs = False

    def synthesize(self, text, speed=1.0):
        raise AssertionError("the local engine must never speak: the helper does")


def wait_until(condition, timeout_s=10.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


class RemoteVoiceTests(unittest.TestCase):
    def make(self, **kwargs) -> tuple[RemoteVoice, LocalStandIn]:
        local = LocalStandIn(needs_download=kwargs.pop("needs_download", False))
        env = dict(os.environ, **{FAKE_ENV: "1"}, **kwargs.pop("env", {}))
        voice = RemoteVoice(local, command=server_command(), env=env, **{"keep_loaded": True, **kwargs})
        self.addCleanup(voice.close)
        return voice, local

    def test_the_helper_loads_and_speaks(self):
        voice, local = self.make()
        self.assertFalse(voice.ready)
        self.assertEqual(voice.prepare(), "fake voice ready")
        self.assertTrue(voice.ready)
        self.assertEqual(voice.device, "test")
        speech = voice.synthesize("hello")
        self.assertEqual((len(speech.samples), speech.sample_rate), (5 * 240, 24000))
        self.assertAlmostEqual(speech.samples[0], 0.25)
        self.assertEqual(voice.describe(), "fake local voice")
        self.assertGreater(voice.memory_mb(), 0)
        voice.close()
        self.assertFalse(voice.ready)

    def test_files_are_downloaded_here_and_loaded_in_the_helper(self):
        voice, local = self.make(needs_download=True)
        self.assertIn("downloaded", voice.prepare())
        self.assertEqual(local.downloads, 1)

    def test_a_crashed_helper_fails_one_sentence_then_starts_again(self):
        voice, _ = self.make(env={FAKE_CRASH_ENV: "boom"})
        voice.prepare()
        with self.assertRaises(SynthesisError):
            voice.synthesize("this goes boom")
        self.assertEqual(len(voice.synthesize("fine again").samples), 10 * 240)

    def test_on_a_smaller_computer_the_helper_closes_when_quiet(self):
        voice, _ = self.make(keep_loaded=False, idle_close_s=0.3)
        voice.synthesize("hi")  # Starts and loads the helper on first use.
        self.assertTrue(voice.ready)
        self.assertTrue(wait_until(lambda: not voice.ready))
        self.assertEqual(len(voice.synthesize("back").samples), 4 * 240)  # loads again when needed

    def test_a_helper_that_grew_too_big_is_restarted_but_stays_ready(self):
        voice, _ = self.make(idle_check_s=0.3, memory_cap_mb=1)
        voice.synthesize("hi")
        self.assertTrue(wait_until(lambda: voice.restarts >= 1))
        self.assertTrue(wait_until(lambda: voice.ready))


class GpuPackTests(unittest.TestCase):
    INDEX = textwrap.dedent("""
        <html><body>
        <a href="/whl/cu128/torch-2.11.0%2Bcu128-cp312-cp312-manylinux_2_28_x86_64.whl#sha256=aaa">torch-2.11.0+cu128-cp312-cp312-manylinux_2_28_x86_64.whl</a><br/>
        <a href="/whl/cu128/torch-2.11.0%2Bcu128-cp312-cp312-win_amd64.whl#sha256=bbb" data-requires-python="&gt;=3.10">torch-2.11.0+cu128-cp312-cp312-win_amd64.whl</a><br/>
        <a href="/whl/cu128/torch-2.10.0%2Bcu128-cp312-cp312-win_amd64.whl#sha256=ccc">torch-2.10.0+cu128-cp312-cp312-win_amd64.whl</a><br/>
        </body></html>
    """)

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        patcher = mock.patch.dict(os.environ, {"ALTER_EGO_DATA_DIR": str(self.data)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_matching_wheel_is_picked_from_the_index(self):
        base = "https://download.pytorch.org/whl/cu128/torch/"
        entries = gpu_pack.parse_index(self.INDEX, base)
        wheel = gpu_pack.pick_wheel(entries, "torch", "2.11.0", "cp312", "win_amd64")
        self.assertEqual(wheel.filename, "torch-2.11.0+cu128-cp312-cp312-win_amd64.whl")
        self.assertEqual(wheel.url, "https://download.pytorch.org/whl/cu128/torch-2.11.0%2Bcu128-cp312-cp312-win_amd64.whl")
        self.assertEqual(wheel.sha256, "bbb")
        self.assertIsNone(gpu_pack.pick_wheel(entries, "torch", "2.12.0", "cp312", "win_amd64"))

    def test_find_wheels_explains_a_missing_build(self):
        with self.assertRaises(gpu_pack.GpuPackError):
            gpu_pack.find_wheels(fetch=lambda url: self.INDEX, size_of=lambda url: 1, versions={"torch": "9.9.9"})

    def wheel_bytes(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("torch/__init__.py", "PACK = True\n")
            archive.writestr("torch-2.11.0.dist-info/METADATA", "Name: torch\n")
        return buffer.getvalue()

    def opener_for(self, data: bytes):
        return lambda request: io.BytesIO(data)

    def test_install_checks_the_download_unpacks_it_and_verifies_the_gpu(self):
        data = self.wheel_bytes()
        wheel = gpu_pack.Wheel("torch", "torch-x.whl", "https://example.invalid/torch-x.whl",
                               hashlib.sha256(data).hexdigest(), len(data))
        progress = []
        name = gpu_pack.install([wheel], lambda text, percent: progress.append(percent), lambda: False,
                                opener=self.opener_for(data), probe=lambda site: {"cuda": True, "name": "Test GPU"})
        self.assertEqual(name, "Test GPU")
        self.assertTrue(gpu_pack.installed())
        self.assertTrue((gpu_pack.site_dir() / "torch" / "__init__.py").is_file())
        self.assertFalse((gpu_pack.pack_dir() / "downloads").exists())  # the wheels are not kept
        self.assertIn(100, progress)
        gpu_pack.remove()
        self.assertFalse(gpu_pack.installed())

    def test_a_wrong_checksum_or_a_gpu_that_does_not_work_leaves_nothing_behind(self):
        data = self.wheel_bytes()
        bad = gpu_pack.Wheel("torch", "torch-x.whl", "https://example.invalid/x", "0" * 64, len(data))
        with self.assertRaises(gpu_pack.GpuPackError):
            gpu_pack.install([bad], lambda *a: None, lambda: False, opener=self.opener_for(data),
                             probe=lambda site: {"cuda": True})
        self.assertFalse(gpu_pack.installed())
        good = gpu_pack.Wheel("torch", "torch-x.whl", "https://example.invalid/x", hashlib.sha256(data).hexdigest())
        with self.assertRaises(gpu_pack.GpuPackError) as raised:
            gpu_pack.install([good], lambda *a: None, lambda: False, opener=self.opener_for(data),
                             probe=lambda site: {"cuda": False, "error": "no card"})
        self.assertIn("no card", str(raised.exception))
        self.assertFalse(gpu_pack.installed())
        self.assertFalse(gpu_pack.site_dir().exists())

    def test_only_offered_on_a_packaged_windows_build_with_an_nvidia_driver(self):
        with mock.patch.object(gpu_pack, "supported", return_value=True), \
                mock.patch.object(gpu_pack, "has_nvidia_driver", return_value=True), \
                mock.patch.object(gpu_pack, "bundled_versions", return_value={"torch": "2.11.0"}):
            self.assertTrue(gpu_pack.offered())
            with mock.patch.object(gpu_pack, "has_nvidia_driver", return_value=False):
                self.assertFalse(gpu_pack.offered())
        self.assertFalse(gpu_pack.offered() if not getattr(sys, "frozen", False) else False)

    def test_the_helper_imports_torch_from_the_pack(self):
        site = self.data / "site"
        (site / "torch" / "nn").mkdir(parents=True)
        (site / "torch" / "__init__.py").write_text("FROM_PACK = True\n", encoding="utf-8")
        (site / "torch" / "nn" / "__init__.py").write_text("NN_FROM_PACK = True\n", encoding="utf-8")
        script = textwrap.dedent("""
            import sys
            from pathlib import Path
            sys.path.insert(0, sys.argv[1])
            import alter_ego.providers
            from alter_ego.core.gpu_pack import prefer_pack
            assert prefer_pack(Path(sys.argv[2]))
            import torch, torch.nn
            print(torch.FROM_PACK, torch.nn.NN_FROM_PACK)
        """)
        done = subprocess.run([sys.executable, "-c", script, str(PROJECT_ROOT / "src"), str(site)],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-1500:])
        self.assertEqual(done.stdout.split(), ["True", "True"])

    def test_the_probe_reports_through_the_helper(self):
        site = self.data / "site"
        (site / "torch").mkdir(parents=True)
        (site / "torch" / "__init__.py").write_text(textwrap.dedent("""
            __version__ = "2.11.0+cu128"
            class cuda:
                @staticmethod
                def is_available(): return True
                @staticmethod
                def get_device_name(index): return "Pretend GPU"
        """), encoding="utf-8")
        result = gpu_pack._probe(site)
        self.assertEqual((result.get("cuda"), result.get("name")), (True, "Pretend GPU"), result)
        # The same folder spelled the short Windows way (C:\Users\RUNNER~1 on the build machines) is the same pack.
        short = short_path(site)
        if short != str(site):
            result = gpu_pack._probe(Path(short))
            self.assertEqual(result.get("cuda"), True, result)


def short_path(path: Path) -> str:
    """The 8.3 spelling of a folder on Windows (when the drive keeps one), else the path as it is."""
    if sys.platform != "win32":
        return str(path)
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    return buffer.value if 0 < length < len(buffer) else str(path)


if __name__ == "__main__":
    unittest.main()
