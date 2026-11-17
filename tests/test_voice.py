"""Tests for spoken replies (v0.6.0): sentence splitting, the voice effects, the
local engine without its package, the character voice with a fake converter,
how the one fixed voice is chosen, and the Speaker state machine with a fake
engine and a fake player. No speakers, no model files and no network needed.

Run from the project root with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import array
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PySide6.QtCore import QCoreApplication, QObject, Signal  # noqa: E402

from alter_ego.core.conversation import Conversation, Message, Role  # noqa: E402
from alter_ego.expressions import Expression  # noqa: E402
from alter_ego.settings.config import Config  # noqa: E402
from alter_ego.voice import (  # noqa: E402
    CharacterVoiceSynthesizer,
    KokoroSynthesizer,
    Speaker,
    SpeakingState,
    Speech,
    SynthesisError,
    VoiceStyle,
    build_synthesizer,
    character_dir,
    character_model,
)
from alter_ego.voice.effects import crt_voice, from_pcm16, pitch_factor, resample, to_pcm16, with_tail  # noqa: E402
from alter_ego.voice.kokoro_local import PRESET_VOICE, VOICES, voice_language  # noqa: E402
from alter_ego.voice.player import PlaybackError  # noqa: E402
from alter_ego.voice.rvc_local import (  # noqa: E402
    BASE_DOWNLOAD_MB,
    DEFAULT_F0_METHOD,
    DEFAULT_INDEX_RATE,
    DEFAULT_PITCH,
    HUBERT_FILES,
    MODEL_HINT,
    find_character_model,
    find_index,
)
from alter_ego.voice.speaker import EXPRESSION_SPEED, NO_SYNTHESIZER_MESSAGE  # noqa: E402
from alter_ego.voice.text import MIN_CHARS, speakable, take_sentences  # noqa: E402

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


def process_events_until(condition, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        _app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def tone(seconds: float, rate: int = 24000, amplitude: float = 0.5, hz: float = 220.0) -> Speech:
    count = int(seconds * rate)
    return Speech(array.array("f", (amplitude * math.sin(2 * math.pi * hz * i / rate) for i in range(count))), rate)


# ----- Sentences -----

class SentenceTests(unittest.TestCase):
    def test_complete_sentences_are_taken_and_the_rest_waits(self):
        text = "Oh! H-hello. I'm Alter Ego. I'll be right"
        sentences, used = take_sentences(text, final=False)
        self.assertEqual(sentences, ["Oh! H-hello.", "I'm Alter Ego."])
        self.assertEqual(text[used:].strip(), "I'll be right")

    def test_short_fragment_joins_the_next_sentence(self):
        sentences, _ = take_sentences("Oh! That's wonderful news. ", final=False)
        self.assertEqual(sentences, ["Oh! That's wonderful news."])
        self.assertLess(len("Oh!"), MIN_CHARS)

    def test_final_takes_everything(self):
        sentences, used = take_sentences("One thing to say. and a tail without punctuation", final=True)
        self.assertEqual(sentences, ["One thing to say.", "and a tail without punctuation"])
        self.assertEqual(used, len("One thing to say. and a tail without punctuation"))
        self.assertEqual(take_sentences("   ", final=True), ([], 3))
        self.assertEqual(take_sentences("", final=False), ([], 0))

    def test_numbers_quotes_and_newlines(self):
        sentences, _ = take_sentences('Version 3.5 is out. "Really?" she asked.\nNew paragraph here', final=True)
        self.assertEqual(sentences, ["Version 3.5 is out.", '"Really?" she asked.', "New paragraph here"])
        # A sentence that ends the text without trailing whitespace is only taken when final.
        self.assertEqual(take_sentences("Is it done?", final=False), ([], 0))
        self.assertEqual(take_sentences("Is it done?", final=True), (["Is it done?"], 11))

    def test_long_sentences_are_chunked(self):
        text = ", ".join(["a clause that goes on"] * 40) + "."
        sentences, _ = take_sentences(text, final=True)
        self.assertGreater(len(sentences), 1)
        self.assertTrue(all(len(s) <= 400 for s in sentences))
        self.assertEqual(" ".join(sentences).replace(", ", ",").replace(" ", ""), text.replace(" ", ""))

    def test_speakable_drops_markup(self):
        self.assertEqual(speakable("Hello **there** `friend`  ▌"), "Hello there friend")
        self.assertEqual(speakable("(...sorry, I lost the connection: x)"), "(sorry, I lost the connection: x)")


# ----- Effects -----

class EffectTests(unittest.TestCase):
    def test_pitch_factor(self):
        self.assertAlmostEqual(pitch_factor(0), 1.0)
        self.assertAlmostEqual(pitch_factor(6), 2 ** 0.5)
        self.assertAlmostEqual(pitch_factor(100), pitch_factor(8))  # clamped

    def test_resample_changes_length_and_pitch(self):
        clip = tone(1.0, hz=220.0)
        faster = resample(clip, 1.25)
        self.assertAlmostEqual(faster.duration, 0.8, places=2)
        self.assertEqual(faster.sample_rate, clip.sample_rate)
        crossings = sum(1 for a, b in zip(faster.samples, faster.samples[1:]) if a < 0 <= b)
        self.assertAlmostEqual(crossings / faster.duration, 275, delta=4)  # 220 Hz * 1.25
        self.assertIs(resample(clip, 1.0), clip)

    def test_crt_effect_keeps_length_and_stays_in_range(self):
        clip = tone(0.5, amplitude=0.9)
        shaped = crt_voice(clip)
        self.assertEqual(len(shaped.samples), len(clip.samples))
        self.assertLessEqual(max(abs(v) for v in shaped.samples), 1.0)
        self.assertGreater(max(abs(v) for v in shaped.samples), 0.3)
        self.assertIs(crt_voice(clip, amount=0), clip)

    def test_pcm_round_trip_and_tail(self):
        clip = Speech(array.array("f", [0.0, 0.5, -0.5, 1.0, -1.0, 2.0]), 24000)
        pcm = to_pcm16(clip)
        self.assertEqual(len(pcm), 12)
        back = from_pcm16(pcm, 24000)
        self.assertAlmostEqual(back.samples[1], 0.5, places=3)
        self.assertAlmostEqual(back.samples[5], 1.0, places=3)  # clipped
        stereo = from_pcm16(to_pcm16(Speech(array.array("f", [1.0, 0.0, 0.5, 0.5]), 24000)), 24000, channels=2)
        self.assertEqual(len(stereo.samples), 2)
        self.assertAlmostEqual(stereo.samples[0], 0.5, places=3)
        self.assertAlmostEqual(with_tail(clip, 0.1).duration, clip.duration + 0.1, places=4)
        self.assertEqual(Speech.silence(0.5, 24000).duration, 0.5)


# ----- Local engine without files or package -----

class KokoroTests(unittest.TestCase):
    def test_needs_download_and_explains_missing_package(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = KokoroSynthesizer("alter_ego", "standard", folder)
            self.assertTrue(engine.needs_download)
            self.assertFalse(engine.ready)
            self.assertGreater(engine.download_size_mb, 300)
            self.assertIn("'alter_ego'", engine.describe())
            saved = sys.modules.get("kokoro_onnx")
            sys.modules["kokoro_onnx"] = None
            try:
                with self.assertRaises(SynthesisError) as caught:
                    engine.synthesize("hello")
                self.assertIn("pip install kokoro-onnx", str(caught.exception))
            finally:
                if saved is None:
                    del sys.modules["kokoro_onnx"]
                else:
                    sys.modules["kokoro_onnx"] = saved

    def test_download_is_never_silent(self):
        # Files missing + package present -> a message pointing at the menu, no network access.
        with tempfile.TemporaryDirectory() as folder:
            engine = KokoroSynthesizer("af_heart", "small", folder)
            try:
                import kokoro_onnx  # noqa: F401
            except ImportError:
                self.skipTest("kokoro-onnx not installed")
            with self.assertRaises(SynthesisError) as caught:
                engine.synthesize("hello")
            self.assertIn("Download my voice", str(caught.exception))

    def test_voices_and_languages(self):
        self.assertIn(PRESET_VOICE, VOICES)
        self.assertEqual(voice_language("alter_ego"), "en-us")
        self.assertEqual(voice_language("bf_emma"), "en-gb")
        self.assertEqual(voice_language("jf_alpha"), "ja")
        self.assertEqual(KokoroSynthesizer("no_such_voice").voice, PRESET_VOICE)


# ----- Character voice: Kokoro + RVC with a fake Kokoro and a fake converter -----

class FakeKokoro:
    def __init__(self, needs_download=False):
        self.needs_download = needs_download
        self.download_size_mb = 338 if needs_download else 0
        self.ready = False
        self.spoken: list[tuple[str, float]] = []

    def prepare(self):
        self.ready = True
        self.needs_download = False

    def synthesize(self, text, speed=1.0):
        self.spoken.append((text, speed))
        return tone(0.5, rate=24000) if text.strip() else Speech.empty()


class FakeConverter:
    """Returns 16-bit samples at 40 kHz, like the real package, twice as long as the input."""

    def __init__(self):
        self.conf = None
        self.calls = 0

    def apply_conf(self, **kwargs):
        self.conf = kwargs

    def generate_from_cache(self, audio_data, tag):
        samples, rate = audio_data
        self.calls += 1
        import numpy as np

        return (np.full(len(samples) * 40000 // rate, 16384, dtype=np.int16), 40000)


class CharacterVoiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.model = self.root / "character.pth"
        self.model.write_bytes(b"fake")

    def base_models(self, present=True):
        rvc = self.root / "rvc"
        (rvc / "hubert_base").mkdir(parents=True, exist_ok=True)
        if present:
            (rvc / "rmvpe.pt").write_bytes(b"x")
            for name in HUBERT_FILES:
                (rvc / "hubert_base" / name).write_bytes(b"x")
        return rvc

    def make(self, converter=None, kokoro=None, **kwargs):
        converter = converter or FakeConverter()
        engine = CharacterVoiceSynthesizer(
            kokoro or FakeKokoro(), model_path=kwargs.pop("model_path", self.model), models_dir=self.base_models(),
            converter_factory=lambda rmvpe, hubert: converter, **kwargs,
        )
        return engine, converter

    def test_download_accounting(self):
        engine = CharacterVoiceSynthesizer(FakeKokoro(), self.model, models_dir=self.root / "rvc")
        self.assertTrue(engine.needs_download)
        self.assertEqual(engine.download_size_mb, BASE_DOWNLOAD_MB)
        engine = CharacterVoiceSynthesizer(FakeKokoro(needs_download=True), self.model, models_dir=self.base_models())
        self.assertTrue(engine.needs_download)
        self.assertEqual(engine.download_size_mb, 338)
        engine = CharacterVoiceSynthesizer(FakeKokoro(), self.model, models_dir=self.base_models())
        self.assertFalse(engine.needs_download)
        self.assertFalse(engine.shape_voice)
        self.assertIn("'character'", engine.describe())

    def test_converts_kokoro_speech_with_the_chosen_settings(self):
        (self.root / "character.index").write_bytes(b"i")
        engine, converter = self.make(pitch_semitones=2.4, index_rate=0.7, f0_method="pm")
        speech = engine.synthesize("Hello there.", speed=0.9)
        self.assertEqual(speech.sample_rate, 40000)
        self.assertAlmostEqual(speech.duration, 0.5, places=3)
        self.assertAlmostEqual(speech.samples[0], 0.5, places=3)  # int16 16384 -> 0.5
        self.assertEqual(converter.conf["pitch_lvl"], 2)
        self.assertEqual(converter.conf["pitch_algo"], "pm")
        self.assertEqual(converter.conf["index_influence"], 0.7)
        self.assertEqual(converter.conf["file_index"], str(self.root / "character.index"))
        self.assertEqual(engine.kokoro.spoken, [("Hello there.", 0.9)])
        engine.synthesize("   ")  # empty speech is passed through untouched
        self.assertEqual(converter.calls, 1)
        self.assertFalse(engine.ready)  # Kokoro itself has not been prepared yet
        self.assertIn("'character'", engine.prepare())
        self.assertTrue(engine.ready)

    def test_index_is_found_next_to_the_model(self):
        self.assertIsNone(find_index(self.model))
        other = self.root / "added_IVF256_Flat_nprobe_1_v2.index"
        other.write_bytes(b"i")
        self.assertEqual(find_index(self.model), other)
        (self.root / "second.index").write_bytes(b"i")
        self.assertIsNone(find_index(self.model))  # two candidates: no guessing
        (self.root / "character.index").write_bytes(b"i")
        self.assertEqual(find_index(self.model), self.root / "character.index")

    def test_missing_model_package_and_base_files_are_explained(self):
        engine, _ = self.make(model_path="")
        with self.assertRaises(SynthesisError) as caught:
            engine.synthesize("x")
        self.assertIn(MODEL_HINT, str(caught.exception))
        engine, _ = self.make(model_path=self.root / "gone.pth")
        with self.assertRaises(SynthesisError) as caught:
            engine.synthesize("x")
        self.assertIn("can't find", str(caught.exception))

        engine = CharacterVoiceSynthesizer(FakeKokoro(), self.model, models_dir=self.root / "empty")
        with self.assertRaises(SynthesisError) as caught:
            engine.synthesize("x")
        self.assertIn("Download my voice", str(caught.exception))

        saved = sys.modules.get("infer_rvc_python")
        sys.modules["infer_rvc_python"] = None
        try:
            engine = CharacterVoiceSynthesizer(FakeKokoro(), self.model, models_dir=self.base_models())
            with self.assertRaises(SynthesisError) as caught:
                engine.synthesize("x")
            self.assertIn("requirements-character-voice.txt", str(caught.exception))
        finally:
            if saved is None:
                del sys.modules["infer_rvc_python"]
            else:
                sys.modules["infer_rvc_python"] = saved

    def test_tuning_is_fixed_in_the_code(self):
        engine, converter = self.make()
        engine.synthesize("Hello.")
        self.assertEqual(converter.conf["pitch_lvl"], DEFAULT_PITCH)
        self.assertEqual(converter.conf["pitch_algo"], DEFAULT_F0_METHOD)
        self.assertEqual(converter.conf["index_influence"], DEFAULT_INDEX_RATE)


# ----- The one voice: chosen by what is in the character folder, never by settings -----

class OneVoiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.config = Config(Path("x.json"), {"voice": {"models_dir": str(self.root)}})
        self.characters = self.root / "voice"

    def test_the_voice_ships_in_the_assets_folder(self):
        self.assertEqual(character_dir(), PROJECT_ROOT / "assets" / "voice")

    def test_only_alter_ego_pth_counts(self):
        self.assertIsNone(character_model(self.characters))  # the folder does not even exist yet
        self.characters.mkdir()
        (self.characters / "someone_else.pth").write_bytes(b"m")
        self.assertIsNone(character_model(self.characters))  # any other model is ignored
        model = self.characters / "alter_ego.pth"
        model.write_bytes(b"m")
        self.assertEqual(find_character_model(self.characters), model)

    def test_an_lfs_pointer_is_not_a_model(self):
        self.characters.mkdir()
        model = self.characters / "alter_ego.pth"
        model.write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 55175216\n")
        self.assertIsNone(character_model(self.characters))
        self.assertIsInstance(build_synthesizer(self.config, self.characters), KokoroSynthesizer)

    def test_stand_in_voice_only_when_the_file_is_missing(self):
        self.assertIsNone(build_synthesizer(Config(Path("x.json"), {"voice": {"enabled": False}})))
        stand_in = build_synthesizer(self.config, self.characters)
        self.assertIsInstance(stand_in, KokoroSynthesizer)
        self.assertEqual(stand_in.voice, PRESET_VOICE)
        self.assertEqual(stand_in.model_path.parent, self.root)

        self.characters.mkdir()
        (self.characters / "alter_ego.pth").write_bytes(b"m")
        engine = build_synthesizer(self.config, self.characters)
        self.assertIsInstance(engine, CharacterVoiceSynthesizer)
        self.assertEqual(engine.model_path, self.characters / "alter_ego.pth")
        self.assertEqual(engine.pitch_semitones, DEFAULT_PITCH)
        self.assertEqual(engine.rmvpe_path, self.root / "rvc" / "rmvpe.pt")
        self.assertEqual(engine.kokoro.voice, PRESET_VOICE)

    def test_old_voice_settings_change_nothing(self):
        self.characters.mkdir()
        (self.characters / "alter_ego.pth").write_bytes(b"m")
        config = Config(Path("x.json"), {"voice": {
            "models_dir": str(self.root), "synthesizer": "openai", "kokoro_voice": "am_adam", "kokoro_model": "small",
            "rvc_model": str(self.root / "someone_else.pth"), "rvc_pitch": 12, "rvc_f0_method": "pm",
        }})
        engine = build_synthesizer(config, self.characters)
        self.assertIsInstance(engine, CharacterVoiceSynthesizer)
        self.assertEqual(engine.model_path, self.characters / "alter_ego.pth")
        self.assertEqual(engine.pitch_semitones, DEFAULT_PITCH)
        self.assertEqual(engine.kokoro.voice, PRESET_VOICE)
        self.assertEqual(engine.kokoro.model_path.name, "kokoro-v1.0.onnx")
        self.assertEqual(set(EXPRESSION_SPEED), set(Expression))


# ----- Speaker state machine -----

class FakeSynthesizer:
    def __init__(self, error: str | None = None, delay_s: float = 0.0, seconds_per_char: float = 0.01):
        self.error = error
        self.delay_s = delay_s
        self.seconds_per_char = seconds_per_char
        self.spoken: list[tuple[str, float]] = []
        self.ready = False
        self.needs_download = False
        self.download_size_mb = 0
        self.shape_voice = True
        self.prepared = 0

    def describe(self):
        return "fake voice"

    def prepare(self):
        self.ready = True
        self.prepared += 1
        return "fake voice ready"

    def synthesize(self, text, speed=1.0):
        time.sleep(self.delay_s)
        if self.error:
            raise SynthesisError(self.error)
        self.spoken.append((text, round(speed, 3)))
        return Speech.silence(len(text) * self.seconds_per_char / speed, 24000)


class FakePlayer(QObject):
    """Plays clips instantly: finished is emitted when the test calls end_clip()."""

    finished = Signal()

    def __init__(self, fail: bool = False):
        super().__init__()
        self.fail = fail
        self.playing = False
        self.played: list[float] = []

    def play(self, speech):
        if self.fail:
            raise PlaybackError("no speakers")
        self.playing = True
        self.played.append(round(speech.duration, 3))

    def stop(self):
        if self.playing:
            self.playing = False
            self.finished.emit()

    def end_clip(self):
        self.stop()


class SpeakerTests(unittest.TestCase):
    def make(self, engine=True, **kwargs):
        player = FakePlayer(fail=kwargs.pop("player_fails", False))
        synthesizer = FakeSynthesizer(**kwargs) if engine else None
        speaker = Speaker(player, synthesizer)
        speaker.set_style(VoiceStyle(pitch_semitones=0, speed=1.0, crt_effect=False))
        conversation = Conversation()
        speaker.attach(conversation)
        log = {"states": [], "status": [], "sentences": [], "finished": [], "failed": [], "prepared": []}
        speaker.state_changed.connect(log["states"].append)
        speaker.status.connect(log["status"].append)
        speaker.sentence_started.connect(lambda m, end, sec: log["sentences"].append((end, round(sec, 3))))
        speaker.finished.connect(log["finished"].append)
        speaker.failed.connect(log["failed"].append)
        speaker.prepared.connect(log["prepared"].append)
        self.addCleanup(speaker.shutdown)
        return speaker, player, synthesizer, conversation, log

    def wait_playing(self, player):
        self.assertTrue(process_events_until(lambda: player.playing), "no clip started playing")

    def test_streamed_reply_is_spoken_sentence_by_sentence(self):
        speaker, player, engine, conversation, log = self.make()
        message = Message(Role.ASSISTANT, "", expression=Expression.SHY_TALK, complete=False)
        conversation.add(message)
        self.assertIs(speaker.state, SpeakingState.SPEAKING)
        self.assertIs(speaker.current_message, message)

        # The stammer stays in the chat text but is not spoken (see voice/text.py speakable).
        conversation.update(message, text="Oh! H-hello. I'm Alter")
        self.wait_playing(player)
        self.assertEqual(engine.spoken[0], ("Oh! hello.", round(EXPRESSION_SPEED[Expression.SHY_TALK], 3)))
        shy = EXPRESSION_SPEED[Expression.SHY_TALK]
        self.assertEqual(log["sentences"][0][0], 12)
        self.assertAlmostEqual(log["sentences"][0][1], 0.10 / shy, places=2)
        self.assertIn("Loading my voice...", log["status"])

        conversation.update(message, text="Oh! H-hello. I'm Alter Ego. Nice to", complete=False)
        conversation.update(message, text="Oh! H-hello. I'm Alter Ego. Nice to meet you", complete=True)
        player.end_clip()
        self.wait_playing(player)
        self.assertEqual(log["sentences"][1][0], 27)
        self.assertAlmostEqual(log["sentences"][1][1], 0.14 / shy, places=2)
        player.end_clip()
        self.wait_playing(player)
        self.assertEqual(log["sentences"][2][0], len(message.text))
        self.assertEqual([t for t, _ in engine.spoken], ["Oh! hello.", "I'm Alter Ego.", "Nice to meet you"])
        self.assertEqual(log["finished"], [])
        player.end_clip()
        self.assertTrue(process_events_until(lambda: log["finished"]))
        self.assertEqual(log["finished"], [message])
        self.assertIs(speaker.state, SpeakingState.IDLE)
        self.assertIsNone(speaker.current_message)
        self.assertEqual(log["states"], [SpeakingState.SPEAKING, SpeakingState.IDLE])
        self.assertEqual(engine.prepared, 1)

    def test_complete_message_and_user_messages(self):
        speaker, player, engine, conversation, log = self.make()
        conversation.add(Message(Role.USER, "Hello there, how are you?"))
        self.assertIs(speaker.state, SpeakingState.IDLE)
        greeting = Message(Role.ASSISTANT, "Hi! I'm fine, thanks. And you?", expression=Expression.HAPPY)
        conversation.add(greeting)
        self.wait_playing(player)
        player.end_clip()
        self.wait_playing(player)
        player.end_clip()
        self.assertTrue(process_events_until(lambda: log["finished"]))
        self.assertEqual([t for t, _ in engine.spoken], ["Hi! I'm fine, thanks.", "And you?"])

    def test_stop_interrupts_and_drops_pending_clips(self):
        speaker, player, engine, conversation, log = self.make(delay_s=0.05)
        message = Message(Role.ASSISTANT, "First sentence here. Second sentence here. Third one here.", expression=Expression.TALK)
        conversation.add(message)
        self.wait_playing(player)
        speaker.stop()
        self.assertFalse(player.playing)
        self.assertEqual(log["finished"], [message])
        self.assertIs(speaker.state, SpeakingState.IDLE)
        process_events_until(lambda: False, 0.3)  # late clips from the worker must be ignored
        self.assertFalse(player.playing)
        self.assertEqual(len(log["sentences"]), 1)

    def test_new_reply_supersedes_the_old_one_and_clear_stops(self):
        speaker, player, engine, conversation, log = self.make()
        first = Message(Role.ASSISTANT, "A long first reply sentence.", expression=Expression.TALK)
        conversation.add(first)
        self.wait_playing(player)
        second = Message(Role.ASSISTANT, "The second reply sentence.", expression=Expression.TALK)
        conversation.add(second)
        self.assertEqual(log["finished"], [first])
        self.assertIs(speaker.current_message, second)
        self.wait_playing(player)
        conversation.clear()
        self.assertEqual(log["finished"], [first, second])
        self.assertFalse(player.playing)

    def test_engine_failure_is_reported_once(self):
        speaker, player, engine, conversation, log = self.make(error="voice exploded")
        conversation.add(Message(Role.ASSISTANT, "Something to say out loud.", expression=Expression.TALK))
        self.assertTrue(process_events_until(lambda: log["failed"]))
        self.assertEqual(log["failed"], ["voice exploded"])
        self.assertIs(speaker.state, SpeakingState.IDLE)
        self.assertEqual(len(log["finished"]), 1)
        conversation.add(Message(Role.ASSISTANT, "Another sentence to say.", expression=Expression.TALK))
        self.assertIs(speaker.state, SpeakingState.IDLE)  # quiet now, no second complaint
        process_events_until(lambda: False, 0.1)
        self.assertEqual(log["failed"], ["voice exploded"])
        # New settings give it another chance.
        speaker.set_synthesizer(FakeSynthesizer())
        conversation.add(Message(Role.ASSISTANT, "Third time lucky, maybe.", expression=Expression.TALK))
        self.wait_playing(player)

    def test_speakers_failure(self):
        speaker, player, engine, conversation, log = self.make(player_fails=True)
        conversation.add(Message(Role.ASSISTANT, "Something to say out loud.", expression=Expression.TALK))
        self.assertTrue(process_events_until(lambda: log["failed"]))
        self.assertEqual(log["failed"], ["no speakers"])
        self.assertIs(speaker.state, SpeakingState.IDLE)

    def test_download_is_asked_for_not_done(self):
        speaker, player, engine, conversation, log = self.make()
        engine.needs_download = True
        engine.download_size_mb = 340
        conversation.add(Message(Role.ASSISTANT, "Something to say out loud.", expression=Expression.TALK))
        self.assertIs(speaker.state, SpeakingState.IDLE)
        self.assertEqual(len(log["failed"]), 1)
        self.assertIn("340 MB", log["failed"][0])
        self.assertEqual(engine.spoken, [])
        # prepare() does the download (here: nothing) and speech works afterwards.
        self.assertTrue(speaker.prepare())
        self.assertFalse(speaker.prepare())  # already busy
        self.assertTrue(process_events_until(lambda: log["prepared"]))
        self.assertIn("Downloading my voice (about 340 MB", log["status"][0])
        engine.needs_download = False
        conversation.add(Message(Role.ASSISTANT, "Now I can talk.", expression=Expression.TALK))
        self.wait_playing(player)

    def test_disabled_and_no_engine(self):
        speaker, player, engine, conversation, log = self.make(engine=False)
        self.assertFalse(speaker.enabled)
        self.assertFalse(speaker.say("hello"))
        self.assertFalse(speaker.prepare())
        self.assertEqual(log["failed"], [NO_SYNTHESIZER_MESSAGE])
        conversation.add(Message(Role.ASSISTANT, "Nothing happens here.", expression=Expression.TALK))
        self.assertIs(speaker.state, SpeakingState.IDLE)

        speaker, player, engine, conversation, log = self.make()
        speaker.set_enabled(False)
        conversation.add(Message(Role.ASSISTANT, "Nothing happens here either.", expression=Expression.TALK))
        self.assertIs(speaker.state, SpeakingState.IDLE)
        speaker.set_enabled(True)
        self.assertTrue(speaker.say("Testing my voice.", Expression.PASSION_TALK))
        self.wait_playing(player)
        self.assertIsNone(speaker.current_message)
        self.assertEqual(engine.spoken[0][1], round(EXPRESSION_SPEED[Expression.PASSION_TALK], 3))
        player.end_clip()
        self.assertTrue(process_events_until(lambda: log["finished"]))
        self.assertEqual(log["finished"], [None])

    def test_pitch_lift_slows_the_engine_and_speeds_the_clip(self):
        speaker, player, engine, conversation, log = self.make(seconds_per_char=0.1)
        speaker.set_style(VoiceStyle(pitch_semitones=6, speed=1.0, crt_effect=True))
        speaker.say("abcdefghij")  # 10 chars -> 1.0 s at natural pitch
        self.wait_playing(player)
        self.assertEqual(engine.spoken[0][1], 0.707)  # produced slower by the pitch factor...
        self.assertAlmostEqual(player.played[0], 1.0, places=1)  # ...and played back faster by it: same length

    def test_character_voice_is_played_exactly_as_converted(self):
        speaker, player, engine, conversation, log = self.make()
        speaker.set_style(VoiceStyle())  # the fixed style: pitch lift and CRT tone on for the stand-in voice
        engine.shape_voice = False
        source = tone(0.2)
        engine.synthesize = lambda text, speed=1.0: (engine.spoken.append((text, round(speed, 3))), source)[1]
        clips = []
        player.play = lambda speech: (clips.append(speech), setattr(player, "playing", True))
        speaker.say("Hello there.")
        self.wait_playing(player)
        self.assertEqual(engine.spoken[0][1], 1.0)  # no slow-down for a pitch lift
        self.assertEqual(clips[0].samples, source.samples)  # no pitch change, no CRT tone


if __name__ == "__main__":
    unittest.main()
