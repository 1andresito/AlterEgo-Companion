"""Tests for the quick wake reply, the voice preload, the device choice and the unspoken stammer.

Reuses the fakes of test_voice.py and test_handsfree.py: no microphone,
speakers, GPU, model files or network.

Run from the project root with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from alter_ego.core.assistant import ProviderResponder  # noqa: E402
from alter_ego.core.personality import Personality  # noqa: E402
from alter_ego.expressions import Expression  # noqa: E402
from alter_ego.providers.base import ChatMessage, Provider, ProviderError  # noqa: E402
from alter_ego.settings.config import Config  # noqa: E402
from alter_ego.speech.handsfree import HandsFreeState  # noqa: E402
from alter_ego.voice import device  # noqa: E402
from alter_ego.voice.speaker import Speaker, VoiceStyle  # noqa: E402
from alter_ego.voice.synthesizer import SynthesisError  # noqa: E402
from alter_ego.voice.text import speakable  # noqa: E402
import test_handsfree  # noqa: E402  (a module import, so its test class is not collected twice)
from test_voice import FakePlayer, FakeSynthesizer, process_events_until  # noqa: E402

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)
PERSONALITY_FILE = PROJECT_ROOT / "assets" / "personality" / "alter_ego.json"


class StammerTests(unittest.TestCase):
    def test_stammer_is_spoken_once(self):
        self.assertEqual(speakable("I-I think so."), "I think so.")
        self.assertEqual(speakable("Th-thank you!"), "thank you!")
        self.assertEqual(speakable("W-w-what?"), "what?")

    def test_real_hyphenated_words_stay(self):
        text = "an e-mail, a well-known co-op, re-read it"
        self.assertEqual(speakable(text), text)


class DeviceTests(unittest.TestCase):
    def setUp(self):
        device._reset_for_tests()
        self.addCleanup(device._reset_for_tests)

    def test_environment_forces_the_cpu(self):
        with mock.patch.dict(os.environ, {device.DEVICE_ENV: "cpu"}):
            self.assertEqual(device.compute_device(), device.CPU)
            self.assertTrue(device.describe_device().startswith("CPU, "))

    def test_no_usable_gpu_means_cpu_and_never_raises(self):
        broken = mock.MagicMock()
        broken.cuda.is_available.side_effect = RuntimeError("driver trouble")
        with mock.patch.dict(sys.modules, {"torch": broken}), mock.patch.dict(os.environ, {device.DEVICE_ENV: ""}):
            self.assertEqual(device.compute_device(), device.CPU)

    def test_gpu_is_used_when_present_and_can_be_given_up(self):
        torch = mock.MagicMock()
        torch.cuda.is_available.return_value = True
        torch.cuda.get_device_name.return_value = "Test GPU"
        with mock.patch.dict(sys.modules, {"torch": torch}), mock.patch.dict(os.environ, {device.DEVICE_ENV: ""}):
            self.assertEqual(device.compute_device(), device.CUDA)
            self.assertEqual(device.describe_device(), "GPU (Test GPU)")
            device.use_cpu()
            self.assertEqual(device.compute_device(), device.CPU)


class PreloadTests(unittest.TestCase):
    def make(self, **kwargs):
        player = FakePlayer()
        engine = FakeSynthesizer(**kwargs)
        speaker = Speaker(player, engine)
        speaker.set_style(VoiceStyle(pitch_semitones=0, speed=1.0, crt_effect=False))
        log = {"status": [], "prepared": [], "failed": []}
        speaker.status.connect(log["status"].append)
        speaker.prepared.connect(log["prepared"].append)
        speaker.failed.connect(log["failed"].append)
        self.addCleanup(speaker.shutdown)
        return speaker, player, engine, log

    def test_preload_is_silent_and_renders_the_quick_lines(self):
        speaker, player, engine, log = self.make()
        speaker.quick_lines = [("Yes?", Expression.HAPPY)]
        self.assertTrue(speaker.preload())
        self.assertTrue(process_events_until(lambda: speaker.has_ready("Yes?")))
        self.assertEqual(engine.prepared, 1)
        self.assertEqual((log["status"], log["prepared"], log["failed"]), ([], [], []))

        rendered = len(engine.spoken)
        self.assertTrue(speaker.say("Yes?", Expression.HAPPY))
        self.assertTrue(player.playing)  # at once, from the ready clip
        self.assertEqual(len(engine.spoken), rendered)  # no new synthesis

    def test_preload_never_downloads(self):
        speaker, player, engine, log = self.make()
        engine.needs_download = True
        self.assertFalse(speaker.preload())
        speaker.set_enabled(False)
        engine.needs_download = False
        self.assertFalse(speaker.preload())

    def test_a_failed_preload_stays_quiet(self):
        speaker, player, engine, log = self.make()
        engine.prepare = mock.Mock(side_effect=SynthesisError("nope"))
        self.assertTrue(speaker.preload())
        self.assertTrue(process_events_until(lambda: speaker._prepare_worker is None))
        self.assertEqual(log["failed"], [])
        self.assertFalse(speaker._broken)  # the first reply will explain, in character


class WakeReplyTests(test_handsfree.HandsFreeTests):
    """Runs the hands-free fakes again, checking the new `listening` signal and the resumed timer."""

    def test_listening_only_when_the_wake_phrase_comes_alone(self):
        controller, recorder, wake, command, log = self.make(["Hey Alter Ego", "Hey Alter Ego what time is it"], [])
        heard = []
        controller.listening.connect(lambda: heard.append(1))
        controller.start()
        recorder.say()
        self.settle(controller, HandsFreeState.AWAKE)
        self.assertEqual(heard, [1])
        controller.stop()
        controller.start()
        recorder.say()
        self.assertTrue(process_events_until(lambda: log["commands"]))
        self.assertEqual(heard, [1])  # a command in the same breath needs no "yes?"

    def test_resume_gives_the_whole_listening_window_again(self):
        controller, recorder, wake, command, log = self.make(["Hey Alter Ego"], [], awake_s=0.3)
        controller.start()
        recorder.say()
        self.settle(controller, HandsFreeState.AWAKE)
        controller.pause()  # Alter Ego says "yes?"
        process_events_until(lambda: False, 0.2)
        controller.resume()
        self.assertGreater(controller._awake_timer.remainingTime(), 250)

    def test_personality_has_wake_replies(self):
        replies = Personality.load(PERSONALITY_FILE).wake_replies
        self.assertIn("Yes?", replies)
        self.assertEqual(Personality.default().wake_replies, ("Yes?",))


class LocalAddressTests(unittest.TestCase):
    def test_localhost_is_spelled_127_0_0_1(self):
        from alter_ego.providers.ollama import OllamaProvider
        from alter_ego.providers.ollama_server import direct_url

        self.assertEqual(direct_url("http://localhost:11434"), "http://127.0.0.1:11434")
        self.assertEqual(direct_url("http://192.168.1.2:11434"), "http://192.168.1.2:11434")
        self.assertEqual(OllamaProvider("http://localhost:11434/").base_url, "http://127.0.0.1:11434")


class ModelPreloadTests(unittest.TestCase):
    class FakeProvider(Provider):
        id = "fake"
        label = "fake"

        def __init__(self, models, fail=False):
            self.models = models
            self.fail = fail
            self.loaded: list[str] = []

        def describe(self):
            return "fake"

        def list_models(self):
            return self.models

        def stream_reply(self, messages: list[ChatMessage], model, cancelled, progress=None):
            yield "hi"

        def load_model(self, model):
            if self.fail:
                raise ProviderError("down")
            self.loaded.append(model)

    def test_warm_up_loads_the_model_ahead_of_time(self):
        provider = self.FakeProvider(["llama3.2:latest"])
        progress = []
        ProviderResponder(provider, Config(Path("unused.json"))).warm_up(progress.append)
        self.assertEqual(provider.loaded, ["llama3.2:latest"])
        self.assertEqual(progress[-1], "")

    def test_problems_are_left_for_the_first_reply(self):
        for provider in (self.FakeProvider([]), self.FakeProvider(["m"], fail=True)):
            ProviderResponder(provider, Config(Path("unused.json"))).warm_up(lambda _: None)  # must not raise
            self.assertEqual(provider.loaded, [])


# The inherited hands-free cases already run in test_handsfree.py; skip them here.
for _name in [n for n in dir(test_handsfree.HandsFreeTests) if n.startswith("test_")]:
    if _name not in WakeReplyTests.__dict__:
        setattr(WakeReplyTests, _name, None)


if __name__ == "__main__":
    unittest.main()
