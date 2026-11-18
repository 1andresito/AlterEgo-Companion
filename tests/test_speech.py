"""Tests for push to talk (v0.5.0): audio conversion, the key table, the API
transcriber against a fake server, and the push-to-talk state machine with a
fake microphone and a fake engine. No real microphone or speech model needed.

Run from the project root with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import array
import io
import json
import math
import struct
import sys
import threading
import time
import unittest
import wave
from email.parser import BytesParser
from email.policy import default as default_policy
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from alter_ego.settings.config import Config  # noqa: E402
from alter_ego.speech import OpenAITranscriber, WhisperTranscriber, build_transcriber  # noqa: E402
from alter_ego.speech.audio import SAMPLE_RATE, AudioClip, clip_from_pcm  # noqa: E402
from alter_ego.speech.controller import (  # noqa: E402
    MIN_DURATION_S,
    NO_TRANSCRIBER_MESSAGE,
    SILENCE_MESSAGE,
    ListeningState,
    PushToTalk,
)
from alter_ego.speech.hotkey import DEFAULT_KEY, KEY_CODES, PushToTalkKey, key_name  # noqa: E402
from alter_ego.speech.recorder import MicrophoneError  # noqa: E402
from alter_ego.speech.transcriber import TranscriptionError  # noqa: E402

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


def process_events_until(condition, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        _app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def tone(seconds: float, amplitude: float = 0.5, hz: float = 440.0) -> AudioClip:
    count = int(seconds * SAMPLE_RATE)
    return AudioClip(array.array("f", (amplitude * math.sin(2 * math.pi * hz * i / SAMPLE_RATE) for i in range(count))))


# ----- Audio -----

class AudioTests(unittest.TestCase):
    def test_int16_mono_round_trip(self):
        values = [0, 16384, -16384, 32767, -32768]
        clip = clip_from_pcm(struct.pack("<5h", *values), SAMPLE_RATE, 1, "int16")
        self.assertEqual(len(clip.samples), 5)
        self.assertAlmostEqual(clip.samples[1], 0.5, places=4)
        self.assertAlmostEqual(clip.samples[2], -0.5, places=4)
        self.assertAlmostEqual(clip.samples[4], -1.0, places=4)

    def test_other_sample_formats(self):
        self.assertAlmostEqual(clip_from_pcm(bytes([128, 255]), SAMPLE_RATE, 1, "uint8").samples[0], 0.0, places=4)
        self.assertAlmostEqual(clip_from_pcm(struct.pack("<i", 2**30), SAMPLE_RATE, 1, "int32").samples[0], 0.5, places=4)
        self.assertAlmostEqual(clip_from_pcm(struct.pack("<f", 0.25), SAMPLE_RATE, 1, "float").samples[0], 0.25, places=4)
        with self.assertRaises(ValueError):
            clip_from_pcm(b"", SAMPLE_RATE, 1, "int24")

    def test_stereo_is_averaged(self):
        data = struct.pack("<4h", 32767, -32767, 16384, 16384)  # two frames of (L, R)
        clip = clip_from_pcm(data, SAMPLE_RATE, 2, "int16")
        self.assertEqual(len(clip.samples), 2)
        self.assertAlmostEqual(clip.samples[0], 0.0, places=3)
        self.assertAlmostEqual(clip.samples[1], 0.5, places=3)

    def test_trailing_partial_frame_is_dropped(self):
        clip = clip_from_pcm(b"\x00\x00\x00", SAMPLE_RATE, 1, "int16")
        self.assertEqual(len(clip.samples), 1)

    def test_resampling_48k_to_16k(self):
        source_rate = 48000
        seconds = 0.5
        samples = struct.pack(
            f"<{int(source_rate * seconds)}h",
            *(int(10000 * math.sin(2 * math.pi * 100 * i / source_rate)) for i in range(int(source_rate * seconds))),
        )
        clip = clip_from_pcm(samples, source_rate, 1, "int16")
        self.assertAlmostEqual(clip.duration, seconds, places=2)
        # A 100 Hz wave crosses zero upwards 100 times per second; 50 times in half a second.
        crossings = sum(1 for a, b in zip(clip.samples, clip.samples[1:]) if a < 0 <= b)
        self.assertIn(crossings, (49, 50, 51))

    def test_wav_export_and_peak(self):
        clip = tone(0.1, amplitude=0.25)
        self.assertAlmostEqual(clip.peak(), 0.25, places=2)
        with wave.open(io.BytesIO(clip.to_wav_bytes()), "rb") as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, SAMPLE_RATE))
            self.assertEqual(wav.getnframes(), len(clip.samples))
        self.assertEqual(AudioClip.empty().duration, 0.0)
        self.assertEqual(AudioClip.empty().peak(), 0.0)


# ----- Key names -----

class HotkeyTests(unittest.TestCase):
    def test_key_names_are_forgiving(self):
        self.assertEqual(key_name("F9"), "F9")
        self.assertEqual(key_name("f9"), "F9")
        self.assertEqual(key_name("scroll_lock"), "Scroll Lock")
        self.assertEqual(key_name("Right Ctrl"), "Right Ctrl")
        self.assertEqual(key_name("rctrl"), "Right Ctrl")
        self.assertEqual(key_name("mouse4"), "Mouse 4 (side button)")
        self.assertEqual(key_name("Mouse 4 (side button)"), "Mouse 4 (side button)")
        self.assertIsNone(key_name("Windows"))

    def test_unknown_key_falls_back_to_default(self):
        watcher = PushToTalkKey("not a key")
        self.assertEqual(watcher.name, DEFAULT_KEY)
        watcher.set_key("Pause")
        self.assertEqual(watcher.name, "Pause")
        self.assertFalse(watcher.watching)

    def test_every_key_has_a_code(self):
        self.assertTrue(all(0 < code < 256 for code in KEY_CODES.values()))
        self.assertEqual(KEY_CODES["F1"], 0x70)
        self.assertEqual(KEY_CODES["F12"], 0x7B)


# ----- API transcriber against a fake server -----

class FakeTranscriptionHandler(BaseHTTPRequestHandler):
    received: list[dict] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer good-key":
            return self._json(401, {"error": {"message": "Incorrect API key"}})
        self._json(200, {"data": [{"id": "whisper-1"}]})

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer good-key":
            return self._json(401, {"error": {"message": "Incorrect API key"}})
        if self.path != "/v1/audio/transcriptions":
            return self._json(404, {"error": {"message": "no such route"}})
        body = self.rfile.read(int(self.headers["Content-Length"]))
        message = BytesParser(policy=default_policy).parsebytes(
            b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body
        )
        parts = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
        audio = parts["file"].get_payload(decode=True)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            frames = wav.getnframes()
        self.received.append({
            "model": parts["model"].get_content().strip(),
            "language": parts["language"].get_content().strip() if "language" in parts else None,
            "filename": parts["file"].get_filename(),
            "frames": frames,
        })
        self._json(200, {"text": "  Hello there.  "})

    def _json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class OpenAITranscriberTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeTranscriptionHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeTranscriptionHandler.received.clear()

    def test_uploads_wav_and_returns_text(self):
        transcriber = OpenAITranscriber(self.base_url, api_key="good-key", model="whisper-1", language="en")
        clip = tone(0.5)
        self.assertEqual(transcriber.transcribe(clip), "Hello there.")
        sent = FakeTranscriptionHandler.received[0]
        self.assertEqual(sent["model"], "whisper-1")
        self.assertEqual(sent["language"], "en")
        self.assertEqual(sent["filename"], "speech.wav")
        self.assertEqual(sent["frames"], len(clip.samples))

    def test_language_is_optional_and_prepare_checks_the_server(self):
        transcriber = OpenAITranscriber(self.base_url, api_key="good-key")
        transcriber.transcribe(tone(0.2))
        self.assertIsNone(FakeTranscriptionHandler.received[0]["language"])
        self.assertIn("whisper-1", transcriber.prepare())

    def test_bad_key_is_explained(self):
        transcriber = OpenAITranscriber(self.base_url, api_key="bad-key")
        with self.assertRaises(TranscriptionError) as caught:
            transcriber.transcribe(tone(0.2))
        self.assertIn("rejected the API key", str(caught.exception))

    def test_server_down_is_explained(self):
        transcriber = OpenAITranscriber("http://127.0.0.1:9/v1", api_key="x")
        with self.assertRaises(TranscriptionError) as caught:
            transcriber.transcribe(tone(0.2))
        self.assertIn("couldn't connect", str(caught.exception))


# ----- Local Whisper without the package -----

class WhisperTranscriberTests(unittest.TestCase):
    def test_missing_package_is_explained(self):
        saved = sys.modules.get("faster_whisper")
        sys.modules["faster_whisper"] = None  # makes "import faster_whisper" raise ImportError
        try:
            transcriber = WhisperTranscriber("base")
            self.assertFalse(transcriber.ready)
            with self.assertRaises(TranscriptionError) as caught:
                transcriber.transcribe(tone(0.5))
            self.assertIn("pip install faster-whisper", str(caught.exception))
        finally:
            if saved is None:
                del sys.modules["faster_whisper"]
            else:
                sys.modules["faster_whisper"] = saved

    def test_describe(self):
        self.assertIn("'small'", WhisperTranscriber("small", "en").describe())
        self.assertIn("auto-detect", WhisperTranscriber().describe())


class BuildTranscriberTests(unittest.TestCase):
    def test_from_config(self):
        self.assertIsNone(build_transcriber(Config(Path("x.json"), {"speech": {"enabled": False}})))
        whisper = build_transcriber(Config(Path("x.json"), {"speech": {"whisper_model": "tiny.en"}}))
        self.assertIsInstance(whisper, WhisperTranscriber)
        self.assertIn("tiny.en", whisper.describe())
        api = build_transcriber(Config(Path("x.json"), {
            "speech": {"transcriber": "openai", "openai_model": "whisper-large-v3"},
            "openai": {"base_url": "https://api.groq.com/openai/v1", "api_key": "k"},
        }))
        self.assertIsInstance(api, OpenAITranscriber)
        self.assertEqual(api.model, "whisper-large-v3")
        self.assertEqual(api.base_url, "https://api.groq.com/openai/v1")
        self.assertIsInstance(build_transcriber(Config(Path("x.json"), {"speech": {"transcriber": "bogus"}})), WhisperTranscriber)


# ----- Push-to-talk state machine -----

class FakeRecorder:
    def __init__(self, clip: AudioClip, fail: bool = False):
        self.clip = clip
        self.fail = fail
        self.recording = False
        self.starts = 0

    def start(self):
        if self.fail:
            raise MicrophoneError("no mic")
        self.recording = True
        self.starts += 1

    def stop(self):
        self.recording = False
        return self.clip


class FakeTranscriber:
    def __init__(self, text="hello world", error: str | None = None, delay_s: float = 0.0):
        self.text = text
        self.error = error
        self.delay_s = delay_s
        self.calls = 0
        self.ready = False

    def describe(self):
        return "fake"

    def prepare(self):
        self.ready = True
        return "fake ready"

    def transcribe(self, clip):
        self.calls += 1
        time.sleep(self.delay_s)
        if self.error:
            raise TranscriptionError(self.error)
        return self.text


class PushToTalkTests(unittest.TestCase):
    def make(self, clip=None, text="hello world", error=None, transcriber=True, mic_fails=False):
        recorder = FakeRecorder(clip or tone(1.0), fail=mic_fails)
        engine = FakeTranscriber(text, error) if transcriber else None
        controller = PushToTalk(recorder, engine)
        log = {"states": [], "status": [], "text": [], "failed": [], "prepared": []}
        controller.state_changed.connect(log["states"].append)
        controller.status.connect(log["status"].append)
        controller.transcribed.connect(log["text"].append)
        controller.failed.connect(log["failed"].append)
        controller.prepared.connect(log["prepared"].append)
        self.addCleanup(self.settle, controller)
        return controller, recorder, engine, log

    def settle(self, controller):
        """Wait for the worker thread to end and be deleted. The state turns IDLE while the thread
        may still be returning from run(); a controller collected then takes a running QThread with
        it and crashes the test process."""
        worker = controller._worker
        if worker is not None:
            worker.wait(5000)
        self.assertTrue(process_events_until(lambda: controller._worker is None))
        process_events_until(lambda: False, 0.05)  # let the queued deleteLater run

    def wait_idle(self, controller):
        self.assertTrue(process_events_until(lambda: controller.state is ListeningState.IDLE))
        self.settle(controller)

    def test_hold_and_release_produces_text(self):
        controller, recorder, engine, log = self.make()
        controller.start()
        self.assertTrue(recorder.recording)
        self.assertIs(controller.state, ListeningState.LISTENING)
        controller.start()  # a second press while listening changes nothing
        self.assertEqual(recorder.starts, 1)

        controller.stop()
        self.assertFalse(recorder.recording)
        self.wait_idle(controller)
        self.assertEqual(log["text"], ["hello world"])
        self.assertEqual(log["failed"], [])
        self.assertEqual(log["states"], [ListeningState.LISTENING, ListeningState.TRANSCRIBING, ListeningState.IDLE])
        self.assertIn("Listening... release to send", log["status"])
        self.assertEqual(log["status"][-1], "")  # status cleared at the end
        self.assertEqual(engine.calls, 1)

    def test_short_press_is_ignored(self):
        controller, _, engine, log = self.make(clip=tone(MIN_DURATION_S / 2))
        controller.start()
        controller.stop()
        self.assertIs(controller.state, ListeningState.IDLE)
        self.assertEqual(engine.calls, 0)
        self.assertEqual(log["text"], [])

    def test_silence_is_reported_without_transcribing(self):
        controller, _, engine, log = self.make(clip=tone(1.0, amplitude=0.0))
        controller.start()
        controller.stop()
        self.assertEqual(engine.calls, 0)
        self.assertEqual(log["failed"], [SILENCE_MESSAGE])

    def test_engine_error_is_reported(self):
        controller, _, _, log = self.make(error="model exploded")
        controller.start()
        controller.stop()
        self.wait_idle(controller)
        self.assertEqual(log["failed"], ["model exploded"])
        self.assertEqual(log["text"], [])

    def test_no_words_gives_empty_text(self):
        controller, _, _, log = self.make(text="   ")
        controller.start()
        controller.stop()
        self.wait_idle(controller)
        self.assertEqual(log["text"], [""])

    def test_without_engine_or_microphone(self):
        controller, _, _, log = self.make(transcriber=False)
        controller.start()
        self.assertIs(controller.state, ListeningState.IDLE)
        self.assertEqual(log["failed"], [NO_TRANSCRIBER_MESSAGE])

        controller, _, _, log = self.make(mic_fails=True)
        controller.start()
        self.assertIs(controller.state, ListeningState.IDLE)
        self.assertEqual(log["failed"], ["no mic"])

    def test_stop_without_start_and_cancel_while_listening(self):
        controller, recorder, engine, log = self.make()
        controller.stop()  # nothing happens
        self.assertEqual(log["states"], [])
        controller.start()
        controller.cancel()
        self.assertFalse(recorder.recording)
        self.assertIs(controller.state, ListeningState.IDLE)
        self.assertEqual(engine.calls, 0)

    def test_prepare_reports_through_signals(self):
        controller, _, engine, log = self.make()
        self.assertTrue(controller.prepare())
        self.assertFalse(controller.prepare())  # already busy
        self.assertTrue(process_events_until(lambda: bool(log["prepared"])))
        self.assertEqual(log["prepared"], ["fake ready"])
        self.assertTrue(engine.ready)
        process_events_until(lambda: log["status"] and log["status"][-1] == "", 1.0)
        self.assertEqual(log["status"][-1], "")

    def test_swapping_engine_and_availability(self):
        controller, _, _, _ = self.make(transcriber=False)
        self.assertFalse(controller.available)
        controller.set_transcriber(FakeTranscriber())
        self.assertTrue(controller.available)


if __name__ == "__main__":
    unittest.main()
