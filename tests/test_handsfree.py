"""Tests for hands-free mode: the utterance detector, wake-phrase matching and
the HandsFree state machine with a fake microphone stream and fake engines.

Run from the project root with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import array
import math
import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PySide6.QtCore import QCoreApplication, QObject, Signal  # noqa: E402

from alter_ego.settings.config import Config  # noqa: E402
from alter_ego.speech import WhisperTranscriber, build_transcriber, build_wake_transcriber  # noqa: E402
from alter_ego.speech.audio import SAMPLE_RATE, AudioClip  # noqa: E402
from alter_ego.speech.handsfree import (  # noqa: E402
    AWAKE_MESSAGE,
    RETRY_MESSAGE,
    HandsFree,
    HandsFreeState,
)
from alter_ego.speech.recorder import MicrophoneError  # noqa: E402
from alter_ego.speech.transcriber import TranscriptionError  # noqa: E402
from alter_ego.speech.vad import MAX_UTTERANCE_FRAMES, FRAME_SAMPLES, UtteranceDetector  # noqa: E402
from alter_ego.speech.wake import match_wake_phrase  # noqa: E402

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


def process_events_until(condition, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        _app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def samples(seconds: float, amplitude: float, hz: float = 300.0) -> array.array:
    count = int(seconds * SAMPLE_RATE)
    return array.array("f", (amplitude * math.sin(2 * math.pi * hz * i / SAMPLE_RATE) for i in range(count)))


# ----- Utterance detection -----

class UtteranceDetectorTests(unittest.TestCase):
    def feed_all(self, detector, parts, chunk=1000):
        """Feed in small chunks, as the microphone would."""
        found = []
        for part in parts:
            for start in range(0, len(part), chunk):
                found.extend(detector.feed(part[start:start + chunk]))
        return found

    def test_speech_between_silences_is_one_utterance(self):
        detector = UtteranceDetector()
        found = self.feed_all(detector, [samples(1.0, 0.0), samples(1.0, 0.3), samples(1.0, 0.0)])
        self.assertEqual(len(found), 1)
        # The speech plus the pre-roll and the closing silence, give or take a few frames.
        self.assertGreater(found[0].duration, 1.0)
        self.assertLess(found[0].duration, 2.2)
        self.assertFalse(detector.speaking)

    def test_quiet_room_noise_is_not_speech(self):
        detector = UtteranceDetector()
        found = self.feed_all(detector, [samples(3.0, 0.004)])
        self.assertEqual(found, [])

    def test_short_click_is_ignored(self):
        detector = UtteranceDetector()
        found = self.feed_all(detector, [samples(0.5, 0.0), samples(0.1, 0.5), samples(1.0, 0.0)])
        self.assertEqual(found, [])

    def test_very_long_speech_is_cut(self):
        detector = UtteranceDetector()
        seconds = MAX_UTTERANCE_FRAMES * FRAME_SAMPLES / SAMPLE_RATE + 3
        found = self.feed_all(detector, [samples(0.5, 0.0), samples(seconds, 0.3)], chunk=4000)
        self.assertGreaterEqual(len(found), 1)
        self.assertLessEqual(found[0].duration, MAX_UTTERANCE_FRAMES * FRAME_SAMPLES / SAMPLE_RATE + 0.5)

    def test_sensitivity_floor(self):
        quiet_speech = [samples(0.5, 0.0), samples(1.0, 0.012), samples(1.0, 0.0)]  # rms ~0.0085
        self.assertEqual(self.feed_all(UtteranceDetector(), quiet_speech), [])
        self.assertEqual(len(self.feed_all(UtteranceDetector(min_speech_rms=0.005), quiet_speech)), 1)

    def test_background_level_adapts(self):
        detector = UtteranceDetector()
        self.feed_all(detector, [samples(3.0, 0.03)])  # a constant hum
        self.assertGreater(detector.noise_rms, 0.015)
        # Speech only slightly louder than the hum is not an utterance any more...
        self.assertEqual(self.feed_all(detector, [samples(1.0, 0.05), samples(1.0, 0.03)]), [])
        # ...but clearly louder speech still is.
        self.assertEqual(len(self.feed_all(detector, [samples(1.0, 0.4), samples(1.0, 0.03)])), 1)


# ----- Wake phrase -----

class WakePhraseTests(unittest.TestCase):
    def test_variants_whisper_produces(self):
        for heard in ["Hey Alter Ego", "hey alter ego.", "Hey, Altar Ego!", "Hey AlterEgo", "Alter Ego",
                      "Um, hey Alter Ego", "Okay alter ego"]:
            self.assertEqual(match_wake_phrase(heard), "", heard)

    def test_command_in_the_same_breath(self):
        self.assertEqual(match_wake_phrase("Hey Alter Ego, what time is it?"), "what time is it")
        self.assertEqual(match_wake_phrase("hey alter ego tell me a joke"), "tell me a joke")

    def test_common_mishearings_still_wake(self):
        for heard in ["Hey Ultra Ego", "Hey, Otter Ego!", "Hey Alter Eagle", "Hey Alterigo", "Hay Altar Ego", "Hey Alta Igo"]:
            self.assertEqual(match_wake_phrase(heard), "", heard)
        self.assertEqual(match_wake_phrase("hey alter echo what time is it"), "what time is it")
        for heard in ["other people", "after all", "I ate a bagel", "echo location"]:
            self.assertIsNone(match_wake_phrase(heard), heard)

    def test_other_speech_does_not_wake(self):
        for heard in ["later we go to the shop", "hello there", "my ego is fine", "", "   ", "the alter ego of batman"]:
            self.assertIsNone(match_wake_phrase(heard), heard)

    def test_custom_phrase(self):
        self.assertEqual(match_wake_phrase("Computer, open the door", "computer"), "open the door")
        self.assertIsNone(match_wake_phrase("open the door computer", "computer"))


# ----- Hands-free state machine -----

class FakeStreamRecorder(QObject):
    chunk = Signal(object)

    def __init__(self, fail: bool = False):
        super().__init__()
        self.fail = fail
        self.recording = False
        self.starts = 0

    def start(self, stream=False):
        if self.fail:
            raise MicrophoneError("no mic")
        self.recording = True
        self.starts += 1

    def stop(self):
        self.recording = False
        return AudioClip.empty()

    def set_device(self, name):
        pass

    def say(self, seconds: float = 1.0):
        """Push an utterance (speech between silences) into the stream."""
        for part in (samples(0.5, 0.0), samples(seconds, 0.3), samples(1.0, 0.0)):
            self.chunk.emit(AudioClip(part))


class ScriptedTranscriber:
    """Returns the next scripted text for each call."""

    def __init__(self, texts, ready=True, error=None):
        self.texts = list(texts)
        self.calls = 0
        self.ready = ready
        self.error = error

    def describe(self):
        return "scripted"

    def prepare(self):
        self.ready = True
        return "ready"

    def transcribe(self, clip):
        self.calls += 1
        if self.error:
            raise TranscriptionError(self.error)
        return self.texts.pop(0) if self.texts else ""


class HandsFreeTests(unittest.TestCase):
    def make(self, wake_texts=(), command_texts=(), awake_s=0.3, **kwargs):
        recorder = FakeStreamRecorder(fail=kwargs.get("mic_fails", False))
        wake = ScriptedTranscriber(wake_texts) if wake_texts is not None else None
        command = ScriptedTranscriber(command_texts) if command_texts is not None else None
        controller = HandsFree(recorder, wake, command, awake_s=awake_s)
        log = {"states": [], "status": [], "woke": 0, "commands": [], "failed": []}
        controller.state_changed.connect(log["states"].append)
        controller.status.connect(log["status"].append)
        controller.woke.connect(lambda: log.__setitem__("woke", log["woke"] + 1))
        controller.command.connect(log["commands"].append)
        controller.failed.connect(log["failed"].append)
        return controller, recorder, wake, command, log

    def settle(self, controller, state):
        self.assertTrue(process_events_until(lambda: controller.state is state), f"never reached {state}")
        process_events_until(lambda: False, 0.05)

    def test_wake_then_command(self):
        controller, recorder, wake, command, log = self.make(["Hey Alter Ego"], ["what time is it"])
        self.assertTrue(controller.start())
        self.assertTrue(recorder.recording)
        self.assertIs(controller.state, HandsFreeState.WAITING)

        recorder.say()
        self.settle(controller, HandsFreeState.AWAKE)
        self.assertEqual(log["woke"], 1)
        self.assertIn(AWAKE_MESSAGE, log["status"])

        recorder.say()
        self.settle(controller, HandsFreeState.WAITING)
        self.assertEqual(log["commands"], ["what time is it"])
        self.assertEqual(wake.calls, 1)
        self.assertEqual(command.calls, 1)
        self.assertEqual(log["status"][-1], "")
        self.assertEqual(log["states"], [HandsFreeState.WAITING, HandsFreeState.AWAKE,
                                         HandsFreeState.TRANSCRIBING, HandsFreeState.WAITING])

    def test_command_in_the_same_breath(self):
        controller, recorder, _, command, log = self.make(["hey alter ego, tell me a joke"], [])
        controller.start()
        recorder.say()
        self.assertTrue(process_events_until(lambda: bool(log["commands"])))
        self.assertEqual(log["commands"], ["tell me a joke"])
        self.assertEqual(log["woke"], 1)
        self.assertIs(controller.state, HandsFreeState.WAITING)
        self.assertEqual(command.calls, 0)

    def test_phrase_said_while_a_scan_is_running_is_not_lost(self):
        wake = ScriptedTranscriber(["something unrelated", "hey alter ego"])
        wake.delay = 0.3
        original = wake.transcribe

        def slow_transcribe(clip):
            time.sleep(wake.delay)
            return original(clip)

        wake.transcribe = slow_transcribe
        recorder = FakeStreamRecorder()
        controller = HandsFree(recorder, wake, ScriptedTranscriber([]), awake_s=0.3)
        heard = []
        controller.heard.connect(lambda text, matched: heard.append((text, matched)))
        controller.start()
        recorder.say()   # scanned straight away (slowly)
        recorder.say()   # arrives while the first scan runs: queued, not dropped
        self.settle(controller, HandsFreeState.AWAKE)
        self.assertEqual(heard, [("something unrelated", False), ("hey alter ego", True)])

    def test_sensitivity_setting(self):
        controller, _, _, _, _ = self.make(["x"], [])
        self.assertEqual(controller.sensitivity, "normal")
        controller.set_sensitivity("HIGH")
        self.assertEqual(controller.sensitivity, "high")
        controller.set_sensitivity("nonsense")
        self.assertEqual(controller.sensitivity, "normal")

    def test_unrelated_speech_is_ignored(self):
        controller, recorder, wake, _, log = self.make(["nice weather today", "hmm"], [])
        controller.start()
        recorder.say()
        recorder.say()
        process_events_until(lambda: wake.calls == 2)
        self.assertEqual(log["woke"], 0)
        self.assertIs(controller.state, HandsFreeState.WAITING)

    def test_awake_times_out_back_to_waiting(self):
        controller, recorder, _, _, log = self.make(["hey alter ego"], [], awake_s=0.2)
        controller.start()
        recorder.say()
        self.settle(controller, HandsFreeState.AWAKE)
        self.settle(controller, HandsFreeState.WAITING)
        self.assertEqual(log["commands"], [])
        self.assertEqual(log["status"][-1], "")

    def test_silence_window_waits_while_the_user_is_still_talking(self):
        controller, recorder, _, _, log = self.make(["hey alter ego"], ["a long request"], awake_s=0.3)
        controller.start()
        recorder.say()
        self.settle(controller, HandsFreeState.AWAKE)

        # Speak continuously for well over the silence window, in small live chunks.
        recorder.chunk.emit(AudioClip(samples(0.3, 0.0)))
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            recorder.chunk.emit(AudioClip(samples(0.05, 0.3)))
            _app.processEvents()
            time.sleep(0.02)
        self.assertIs(controller.state, HandsFreeState.AWAKE)  # still awake: no silence yet
        recorder.chunk.emit(AudioClip(samples(1.0, 0.0)))      # now the sentence ends
        self.settle(controller, HandsFreeState.WAITING)
        self.assertEqual(log["commands"], ["a long request"])

    def test_empty_command_asks_again_then_gives_up(self):
        controller, recorder, _, _, log = self.make(["hey alter ego"], ["   "], awake_s=0.2)
        controller.start()
        recorder.say()
        self.settle(controller, HandsFreeState.AWAKE)
        recorder.say()
        self.assertTrue(process_events_until(lambda: RETRY_MESSAGE in log["status"]))
        self.assertIs(controller.state, HandsFreeState.AWAKE)
        self.settle(controller, HandsFreeState.WAITING)
        self.assertEqual(log["commands"], [])

    def test_no_listening_on_after_a_reply(self):
        controller, recorder, wake, _, log = self.make(["hey alter ego", "something else"], ["hello", "never used"])
        controller.start()
        recorder.say()
        self.settle(controller, HandsFreeState.AWAKE)
        recorder.say()
        self.settle(controller, HandsFreeState.WAITING)
        self.assertEqual(log["commands"], ["hello"])

        controller.reply_finished()  # Alter Ego answered: back to waiting for the wake phrase
        self.assertIs(controller.state, HandsFreeState.WAITING)
        recorder.say()  # without the wake phrase this is not a request
        self.assertTrue(process_events_until(lambda: wake.calls == 2))
        process_events_until(lambda: False, 0.1)
        self.assertEqual(log["commands"], ["hello"])

    def asked_hands_free(self, interrupt=True):
        controller, recorder, _, _, log = self.make(["hey alter ego"], ["hello", "stop, tell me a joke"])
        controller.set_interrupt_by_voice(interrupt)
        log["interrupted"] = 0
        controller.interrupted.connect(lambda: log.__setitem__("interrupted", log["interrupted"] + 1))
        controller.start()
        recorder.say()
        self.settle(controller, HandsFreeState.AWAKE)
        recorder.say()
        self.settle(controller, HandsFreeState.WAITING)
        return controller, recorder, log

    def test_talking_over_a_hands_free_reply_interrupts_it(self):
        controller, recorder, log = self.asked_hands_free()
        self.assertTrue(controller.interruptible)
        controller.watch_for_interrupt()  # the reply starts to play
        recorder.say()
        self.assertTrue(process_events_until(lambda: log["commands"] == ["hello", "stop, tell me a joke"]))
        self.assertEqual(log["interrupted"], 1)
        self.assertTrue(controller.interruptible)  # the new request was made hands-free too, so its reply may be cut short

    def test_interrupting_is_off_by_default_and_only_for_hands_free_replies(self):
        controller, recorder, log = self.asked_hands_free(interrupt=False)
        self.assertFalse(controller.interruptible)
        controller.reply_finished()
        controller.set_interrupt_by_voice(True)
        self.assertFalse(controller.interruptible)  # a typed or push-to-talk request: hold the key instead
        controller.watch_for_interrupt()
        self.assertEqual(log["interrupted"], 0)

    def test_pause_and_resume_for_push_to_talk(self):
        controller, recorder, wake, _, _ = self.make(["hey alter ego"], [])
        controller.start()
        controller.pause()
        self.assertFalse(recorder.recording)
        recorder.say()  # audio while paused is ignored
        process_events_until(lambda: False, 0.1)
        self.assertEqual(wake.calls, 0)
        controller.resume()
        self.assertTrue(recorder.recording)
        self.assertEqual(recorder.starts, 2)
        self.assertIs(controller.state, HandsFreeState.WAITING)

    def test_stop_and_restart(self):
        controller, recorder, _, _, log = self.make(["hey alter ego"], [])
        controller.start()
        controller.stop()
        self.assertFalse(recorder.recording)
        self.assertIs(controller.state, HandsFreeState.OFF)
        recorder.say()
        process_events_until(lambda: False, 0.05)
        self.assertEqual(log["woke"], 0)
        self.assertTrue(controller.start())
        self.assertTrue(controller.start())  # already on

    def test_cannot_start_without_engine_or_microphone(self):
        controller, _, _, _, log = self.make(None, None)
        self.assertFalse(controller.start())
        self.assertIs(controller.state, HandsFreeState.OFF)
        self.assertEqual(len(log["failed"]), 1)

        controller, _, _, _, log = self.make(["x"], [], mic_fails=True)
        self.assertFalse(controller.start())
        self.assertIn("no mic", log["failed"][0])

    def test_engine_failure_switches_hands_free_off(self):
        controller, recorder, wake, _, log = self.make(["hey alter ego"], [])
        wake.error = "model missing"
        controller.start()
        recorder.say()
        self.settle(controller, HandsFreeState.OFF)
        self.assertIn("model missing", log["failed"][0])
        self.assertIn("Hands-free is now off", log["failed"][0])
        self.assertFalse(recorder.recording)

    def test_wake_model_is_prepared_on_start(self):
        controller, _, wake, _, log = self.make(["x"], [])
        wake.ready = False
        controller.start()
        self.assertTrue(process_events_until(lambda: wake.ready))
        self.assertIn("Loading the wake-word model...", log["status"])
        self.assertTrue(process_events_until(lambda: log["status"][-1] == ""))


class BuildWakeTranscriberTests(unittest.TestCase):
    def test_from_config(self):
        off = Config(Path("x.json"), {"speech": {"hands_free": False}})
        self.assertIsNone(build_wake_transcriber(off, build_transcriber(off)))

        on = Config(Path("x.json"), {"speech": {"hands_free": True, "whisper_model": "base", "wake_model": "tiny"}})
        main = build_transcriber(on)
        wake = build_wake_transcriber(on, main)
        self.assertIsInstance(wake, WhisperTranscriber)
        self.assertEqual(wake.model_name, "tiny")
        self.assertIsNot(wake, main)

        # The wake engine is tuned on its own (fixed language, phrase hint), so it is never the main one.
        same = Config(Path("x.json"), {"speech": {"hands_free": True, "whisper_model": "tiny", "wake_model": "tiny"}})
        main = build_transcriber(same)
        wake = build_wake_transcriber(same, main)
        self.assertIsNot(wake, main)
        self.assertEqual(wake._language, "en")          # auto-detect would guess wrong on short clips
        self.assertEqual(wake._prompt, "Hey Alter Ego.")
        self.assertFalse(wake._vad_filter)
        spanish = Config(Path("x.json"), {"speech": {"hands_free": True, "language": "es"}})
        self.assertEqual(build_wake_transcriber(spanish, build_transcriber(spanish))._language, "es")

        self.assertFalse(Config(Path("x.json"), {"speech": {"enabled": False, "hands_free": True}}).hands_free_enabled)


if __name__ == "__main__":
    unittest.main()
