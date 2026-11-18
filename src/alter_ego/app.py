from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from .ai_menu import add_ai_menu
from .character import CharacterWindow
from .chat import ChatWindow
from .core.assistant import Assistant, OfflineResponder, ProviderResponder, Responder
from .core.conversation import Conversation
from .core.first_run import SetupRunner, SetupStep, make_plan
from .core.memory import MEMORY_FILENAME, MemoryStore
from .core.personality import Personality
from .expressions import Expression, ExpressionManager
from .gpu_prompt import GpuPackPrompt
from .loading_window import LoadingWindow
from .memory_menu import add_memory_menu
from .providers import create_provider, ollama_server
from .providers.ollama import OllamaProvider
from .providers.tools_mcp import ApprovalServer
from .reactions import CharacterReactions
from .setup_wizard import SetupWizard
from .settings.config import Config, assets_dir, data_dir
from .single_instance import SingleInstance
from .speech import build_transcriber, build_wake_transcriber, transcriber_signature, wake_signature
from .speech.controller import ListeningState, PushToTalk
from .speech.handsfree import HandsFree
from .speech.hotkey import PushToTalkKey
from .speech.recorder import MicrophoneRecorder
from .speak_menu import add_speak_menu
from .tool_approval import ToolApproval
from .update_prompt import UpdatePrompt
from .voice import Speaker, SpeakingState, SpeechPlayer, build_voice, synthesizer_signature
from .voice_menu import add_voice_menu

# Gap between the character and the chat panel when they sit side by side.
CHAT_GAP = 12
# The start-up update check waits a little, so it doesn't compete with loading the voice and the AI.
UPDATE_CHECK_DELAY_MS = 8000


class EngineCache:
    """Keeps an engine while the settings it is built from stay the same.

    Every menu change runs apply_settings(); without this, each click rebuilt
    the voice (43 s to reload the character voice, two copies in RAM meanwhile)
    and the speech models, even when the change was about something else.
    """

    def __init__(self) -> None:
        self._engines: dict[str, tuple[tuple, object]] = {}

    def get(self, name: str, signature: tuple, build: Callable[[], object]):
        kept = self._engines.get(name)
        if kept is not None and kept[0] == signature:
            return kept[1]
        if kept is not None:
            _close(kept[1])  # The voice helper of a replaced voice would otherwise keep its memory.
        engine = build()
        self._engines[name] = (signature, engine)
        return engine

    def close_all(self) -> None:
        """Stop engines that run outside this process (the voice helper). Called when quitting."""
        for _, engine in self._engines.values():
            _close(engine)


def _close(engine: object) -> None:
    close = getattr(engine, "close", None)
    if callable(close):
        try:
            close()
        except Exception as error:  # noqa: BLE001 - quitting must not fail over a helper
            print(f"Warning: could not stop {type(engine).__name__}: {error}")


def build_responder(config: Config, approval: ToolApproval | None = None,
                    approval_server: ApprovalServer | None = None) -> Responder:
    """Pick the responder the settings ask for. Offline if no provider is configured.

    `approval` asks the user before the AI changes a file (Ollama calls it directly,
    Claude Code's tool server through `approval_server`).
    """
    provider = create_provider(
        config.provider,
        config,
        approve=approval.ask if approval is not None else None,
        approval_address=approval_server.address if approval_server is not None else "",
    )
    if provider is None:
        return OfflineResponder()
    return ProviderResponder(provider, config)


ICON_FILE = "AlterEgoIcon.jpg"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def make_app_icon(assets: Path) -> QIcon:
    """The tray/taskbar icon: the user's artwork cropped to a circle with a green ring.

    Falls back to a drawn "AE" badge if the image is missing. The icon is
    rendered at several sizes so Windows can pick a sharp one for each place.
    """
    source = QPixmap(str(assets / ICON_FILE))
    icon = QIcon()
    for size in ICON_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        ring = max(1.0, size / 24)
        inner = pixmap.rect().adjusted(int(ring), int(ring), -int(ring), -int(ring))

        if source.isNull():
            painter.setBrush(QColor("#10250d"))
            painter.setPen(QPen(QColor("#8dff45"), ring))
            painter.drawEllipse(inner)
            painter.setPen(QColor("#baff85"))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "AE")
        else:
            # Clip to a circle, draw the artwork scaled to cover it, then the ring on top.
            clip = QPainterPath()
            clip.addEllipse(inner)
            painter.setClipPath(clip)
            scaled = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
            painter.setClipping(False)
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            painter.setPen(QPen(QColor("#8dff45"), ring))
            painter.drawEllipse(inner)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def show_window(window: QWidget) -> None:
    window.show()
    window.raise_()
    window.activateWindow()


def toggle_character(character: CharacterWindow) -> None:
    if character.isVisible():
        character.disappear()
    else:
        character.appear()


def place_chat_near(character: QWidget, chat: QWidget) -> None:
    """Put the chat panel beside the character: left if there is room, else right, else below."""
    screen = QApplication.screenAt(character.frameGeometry().center()) or QApplication.primaryScreen()
    if screen is None:
        return
    available: QRect = screen.availableGeometry()
    char = character.frameGeometry()

    x = char.left() - chat.width() - CHAT_GAP
    y = char.top()
    if x < available.left():
        x = char.right() + CHAT_GAP
    if x + chat.width() > available.right():
        x = max(available.left(), char.right() - chat.width())
        y = char.bottom() + CHAT_GAP

    # Keep the panel fully on screen.
    x = min(max(x, available.left()), available.right() - chat.width())
    y = min(max(y, available.top()), available.bottom() - chat.height())
    chat.move(x, y)


def run(on_single_copy: Callable[[], None] | None = None) -> int:
    """Start Alter Ego. `on_single_copy` runs once this is known to be the only copy (main.py starts the log)."""
    app = QApplication(sys.argv)
    app.setApplicationName("Alter Ego")
    # Closing/hiding the window must not quit: the app keeps running in the tray.
    app.setQuitOnLastWindowClosed(False)

    # Only one Alter Ego: a second start brings the running one forward and quits (single_instance.py).
    instance = SingleInstance(data_dir())
    if not instance.acquire():
        shown = instance.ask_running_copy_to_show()
        print("Alter Ego is already running" + ("; showing it." if shown else ", but it did not answer."))
        return 0
    app.aboutToQuit.connect(instance.release)
    if on_single_copy is not None:
        on_single_copy()

    assets = assets_dir()
    app_icon = make_app_icon(assets)
    app.setWindowIcon(app_icon)  # Taskbar, Alt-Tab and the window list use this.
    config = Config.load()
    personality = Personality.load(assets / "personality" / "alter_ego.json")
    conversation = Conversation()

    # Persistent memory: restore the last conversation before any window is
    # listening, so the old messages appear at once instead of being typed out.
    memory = MemoryStore(data_dir() / MEMORY_FILENAME)
    if config.memory_enabled:
        restored = memory.restore(conversation)
        memory.attach(conversation)
        if restored:
            print(f"Alter Ego: remembered {restored} message(s) from last time ({memory.path})")

    # The AI asks before changing files: a dialog, reached directly by Ollama and through a local socket by Claude.
    chat_holder: dict[str, QWidget | None] = {"chat": None}
    approval = ToolApproval(lambda: chat_holder["chat"])
    try:
        approval_server: ApprovalServer | None = ApprovalServer(approval.ask)
    except OSError as error:
        print(f"Warning: no approval server ({error}); Claude won't be able to work with files.")
        approval_server = None

    assistant = Assistant(personality, conversation, build_responder(config, approval, approval_server))
    # Ollama is switched off again when Alter Ego quits or stops using it (see ollama_server.py).
    ollama_used = {"value": config.provider == OllamaProvider.id}
    print(f"Alter Ego: {assistant.responder.describe()} (settings: {config.path})")

    # Push to talk: a global key (or the chat's talk button) records, a speech engine transcribes.
    recorder = MicrophoneRecorder(str(config.get("speech", "microphone", "") or ""))
    engines = EngineCache()

    def transcriber():
        return engines.get("transcriber", transcriber_signature(config), lambda: build_transcriber(config))

    push_to_talk = PushToTalk(recorder, transcriber())
    hotkey = PushToTalkKey(str(config.get("speech", "push_to_talk_key", "F9") or "F9"))
    hotkey.pressed.connect(push_to_talk.start)
    hotkey.released.connect(push_to_talk.stop)

    # Hands-free: its own microphone stream, paused while the push-to-talk key is held.
    hands_free_recorder = MicrophoneRecorder(str(config.get("speech", "microphone", "") or ""))
    hands_free = HandsFree(hands_free_recorder)
    # Printed so a miss can be diagnosed from the terminal: was it not heard, or heard wrong?
    hands_free.heard.connect(
        lambda text, matched: print(f"Hands-free heard: {text!r} -> {'wake phrase' if matched else 'no match'}")
    )

    # Spoken replies: a text-to-speech engine on a worker thread, played through the speakers.
    player = SpeechPlayer(str(config.get("voice", "speaker", "") or ""))
    def synthesizer():
        return engines.get("synthesizer", synthesizer_signature(config), lambda: build_voice(config))

    speaker = Speaker(player, synthesizer())  # The voice's style is fixed: VoiceStyle's defaults.
    speaker.attach(conversation)
    # Rendered ahead of time whenever the voice loads, so the answer to "Hey Alter Ego" plays at once.
    speaker.quick_lines = [(line, Expression.HAPPY) for line in personality.wake_replies]

    # The microphone must not hear Alter Ego's own voice, and hands-free must wait while
    # the push-to-talk key is held: hands-free is paused while either is going on. The one
    # exception: with "interrupt by talking" on, the reply to a hands-free request keeps the
    # microphone open, so the user can talk over it.
    def update_hands_free_pause() -> None:
        if push_to_talk.state is ListeningState.LISTENING:
            hands_free.pause()
        elif speaker.speaking:
            if hands_free.interruptible:
                hands_free.watch_for_interrupt()
            else:
                hands_free.pause()
        else:
            hands_free.stop_watching()
            hands_free.resume()

    push_to_talk.state_changed.connect(lambda _state: update_hands_free_pause())
    speaker.state_changed.connect(lambda _state: update_hands_free_pause())

    # Holding the key while Alter Ego is talking interrupts it: the user wants a word.
    def interrupt_when_listening(state: ListeningState) -> None:
        if state is ListeningState.LISTENING:
            speaker.stop()

    push_to_talk.state_changed.connect(interrupt_when_listening)
    hands_free.interrupted.connect(speaker.stop)  # Talking over a hands-free reply (when allowed) stops it.

    def number(key: str, default: float) -> float:
        try:
            return float(config.get("speech", key, default))
        except (TypeError, ValueError):
            return default

    def apply_speech_settings() -> None:
        device = str(config.get("speech", "microphone", "") or "")
        recorder.set_device(device)
        hands_free_recorder.set_device(device)
        main_transcriber = transcriber()
        push_to_talk.set_transcriber(main_transcriber)
        hotkey.set_key(str(config.get("speech", "push_to_talk_key", "F9") or "F9"))
        if config.speech_enabled:
            hotkey.start()
        else:
            hotkey.stop()
        chat.review_before_sending = bool(config.get("speech", "review_before_sending", False))

        hands_free.stop()
        hands_free.set_phrase(str(config.get("speech", "wake_phrase", "") or ""))
        hands_free.set_timings(number("awake_seconds", 3))
        hands_free.set_interrupt_by_voice(bool(config.get("speech", "interrupt_by_voice", False)))
        hands_free.set_sensitivity(str(config.get("speech", "wake_sensitivity", "normal") or "normal"))
        wake = engines.get("wake", wake_signature(config), lambda: build_wake_transcriber(config, main_transcriber))
        hands_free.set_transcribers(wake, main_transcriber)
        if config.hands_free_enabled:
            hands_free.start()

    def apply_voice_settings() -> None:
        player.set_device(str(config.get("voice", "speaker", "") or ""))
        player.set_volume(number_in("voice", "volume", 0.8))
        voice = synthesizer()
        was_ready = speaker.enabled and voice is speaker.synthesizer
        if voice is not speaker.synthesizer:
            speaker.set_synthesizer(voice)  # Only a real change stops speech and reloads the voice.
        speaker.set_enabled(config.voice_enabled)
        if not was_ready:
            speaker.preload()  # A new or re-enabled voice loads in the background, before the next reply.

    def number_in(section: str, key: str, default: float) -> float:
        try:
            return float(config.get(section, key, default))
        except (TypeError, ValueError):
            return default

    def apply_settings() -> None:
        assistant.set_responder(build_responder(config, approval, approval_server))
        if config.provider == OllamaProvider.id:
            ollama_used["value"] = True
        elif ollama_used["value"]:
            ollama_used["value"] = False
            ollama_server.stop_all()  # Switched away from Ollama: free the memory its model holds.
        assistant.warm_up()  # Choosing Ollama starts its server at once, so the first reply is not delayed.
        if config.memory_enabled:
            memory.attach(conversation)
        else:
            memory.detach()
        apply_speech_settings()
        apply_voice_settings()
        listening_engine = push_to_talk.transcriber
        print(
            f"Alter Ego: now using {assistant.responder.describe()}; memory {'on' if memory.recording else 'off'}; "
            f"push to talk {listening_engine.describe() if listening_engine else 'off'}; "
            f"hands-free {'on' if hands_free.active else 'off'}; "
            f"voice {speaker.synthesizer.describe() if speaker.enabled else 'off'}"
        )

    # Stop any reply still streaming so the worker thread ends before the app does,
    # then save whatever was said and close the database.
    app.aboutToQuit.connect(assistant.cancel)

    def stop_ollama() -> None:
        if ollama_used["value"]:
            ollama_server.stop_all()  # Also the tray app and runners on Windows: Ollama runs only while we use it.
        else:
            ollama_server.stop()

    app.aboutToQuit.connect(stop_ollama)
    if approval_server is not None:
        app.aboutToQuit.connect(approval_server.close)
    app.aboutToQuit.connect(push_to_talk.cancel)
    app.aboutToQuit.connect(hands_free.stop)
    app.aboutToQuit.connect(speaker.shutdown)
    app.aboutToQuit.connect(engines.close_all)  # After the speaker: ends the voice helper process.
    app.aboutToQuit.connect(memory.close)

    expressions = ExpressionManager(assets / "animations")
    character = CharacterWindow(expressions)
    chat = ChatWindow(assistant, push_to_talk, hands_free, speaker)
    chat_holder["chat"] = chat
    reactions = CharacterReactions(expressions, assistant, chat, push_to_talk, hands_free)  # noqa: F841 (kept alive by reference)
    chat.typing_finished.connect(hands_free.reply_finished)

    # First run: if Ollama, a model or the voice is missing, the setup window asks for them. Until it
    # closes, nothing is started that would only fail (Ollama) or is still being downloaded (the voice).
    setup_holder: dict[str, object] = {"wizard": None, "runner": None}
    first_run = not config.setup_done
    if first_run and not make_plan(config, speaker.synthesizer).anything_missing:
        config.set("setup", "done", True)
        config.save()
        first_run = False

    def restart_voice() -> None:
        """The GPU pack was added or removed: the voice helper starts again with or without it."""
        close = getattr(speaker.synthesizer, "close", None)
        if callable(close):
            close()
        speaker.preload()

    gpu_prompt = GpuPackPrompt(restart_voice)
    app.aboutToQuit.connect(gpu_prompt.wait)

    def finish_setup() -> None:
        setup_holder["wizard"] = None
        config.set("setup", "done", True)
        config.save()
        apply_settings()
        runner = setup_holder["runner"]
        gpu_added = isinstance(runner, SetupRunner) and runner.results.get(SetupStep.GPU, (False, ""))[0]
        if gpu_added:
            restart_voice()
        else:
            speaker.preload()  # The voice may have just been downloaded: load it and get "Yes?" ready.

    def open_setup() -> None:
        wizard = setup_holder["wizard"]
        if isinstance(wizard, SetupWizard):
            show_window(wizard)
            return
        runner = setup_holder["runner"]
        if not isinstance(runner, SetupRunner):
            runner = SetupRunner(config, speaker.synthesizer)
            setup_holder["runner"] = runner
            app.aboutToQuit.connect(runner.wait)
        runner.set_synthesizer(speaker.synthesizer)
        wizard = SetupWizard(make_plan(config, speaker.synthesizer), runner)
        wizard.setWindowIcon(app_icon)
        wizard.completed.connect(finish_setup)
        setup_holder["wizard"] = wizard
        show_window(wizard)

    # Load the voice first, in the background: it is the slowest part of starting (about 15 s on a
    # GPU, 25 s on a CPU), and the first reply waits for it. The chat shows "Waking up..." meanwhile.
    # Skipped when the voice is off or not downloaded yet.
    player.set_volume(number_in("voice", "volume", 0.8))
    speaker.preload()
    if not first_run:
        assistant.warm_up()  # With Ollama chosen, start its server and load the model, alongside the voice.
    apply_speech_settings()
    if push_to_talk.transcriber is not None:
        print(f"Alter Ego: push to talk with {push_to_talk.transcriber.describe()}, hold {hotkey.name}")
    if hands_free.active:
        print(f'Alter Ego: hands-free on, say "{hands_free.phrase}"')
    if speaker.enabled and speaker.synthesizer is not None:
        where = " (voice files not downloaded yet: see Spoken replies in the menu)" if speaker.synthesizer.needs_download else ""
        print(f"Alter Ego: spoken replies with {speaker.synthesizer.describe()}{where}")

    # The loading window shows what is still waking up (the AI model, the voice); the character
    # switches on when they are ready. Skipped on the first run, where the setup window comes instead.
    loading = LoadingWindow(app_icon)
    if not first_run:
        if not isinstance(assistant.responder, OfflineResponder) and assistant.warming_up:
            loading.add_step("brain", "Starting my brain")
            assistant.warmed_up.connect(lambda: loading.step_done("brain"))
        if speaker.loading:
            loading.add_step("voice", "Loading my voice")
            speaker.loading_finished.connect(lambda: loading.step_done("voice"))

    def show_character() -> None:
        # Start near the upper-right corner instead of covering the center of the screen.
        screen = app.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            character.move(available.right() - character.width() - 32, available.top() + 48)
        character.power_on()  # Like an old TV switching on.
        if first_run:
            open_setup()

    loading.finished.connect(show_character)
    loading.start()

    # Quitting switches the TV off first (the chat goes at once), then the app ends.
    def quit_app() -> None:
        chat.hide()
        character.power_off(app.quit)

    character.quit_requested.connect(quit_app)

    # Updates: at start-up Alter Ego asks GitHub for the latest release and, if it is newer, asks
    # the user before installing it. Skipped right after a fresh install (the first run).
    update_prompt = UpdatePrompt(config, quit_app, lambda: chat_holder["chat"])
    app.aboutToQuit.connect(update_prompt.wait)
    if update_prompt.method is None:
        print("Alter Ego: running from source, so updates come from git (git pull).")
    elif not first_run and bool(config.get("updates", "check", True)):
        QTimer.singleShot(UPDATE_CHECK_DELAY_MS, update_prompt.check)

    # The chat follows the character until the user drags the chat somewhere else.
    docked = {"value": True}

    def open_chat() -> None:
        docked["value"] = True
        place_chat_near(character, chat)
        show_window(chat)
        assistant.greet()

    def toggle_chat() -> None:
        if chat.isVisible():
            chat.hide()
        else:
            open_chat()

    def follow_character() -> None:
        if docked["value"] and chat.isVisible():
            place_chat_near(character, chat)

    def undock() -> None:
        docked["value"] = False

    character.activated.connect(toggle_chat)
    character.moved.connect(follow_character)
    chat.dragged.connect(undock)

    # Holding the key with the chat hidden opens it, so the user sees what was heard.
    def show_chat_when_listening(state: ListeningState) -> None:
        if state is ListeningState.LISTENING and not chat.isVisible():
            open_chat()

    push_to_talk.state_changed.connect(show_chat_when_listening)

    # "Hey Alter Ego" while hidden in the tray: come back on screen and open the chat.
    def wake_up() -> None:
        if not character.isVisible():
            character.appear()
        if not chat.isVisible():
            open_chat()

    hands_free.woke.connect(wake_up)
    instance.show_requested.connect(wake_up)  # Alter Ego was started again: come forward instead.

    # The wake phrase alone: answer "Yes?" out loud so the user knows Alter Ego is listening.
    # The lines are rendered ahead of time (see the preload below), so the answer comes at once.
    def answer_wake() -> None:
        if speaker.enabled:
            speaker.say(random.choice(personality.wake_replies), Expression.HAPPY)

    hands_free.listening.connect(answer_wake)

    # The character's right-click menu is rebuilt each time, so it asks for the shared submenus here.
    def add_shared_menus(menu: QMenu) -> None:
        add_ai_menu(menu, assistant, config, apply_settings, open_setup, lambda: update_prompt.check(manual=True))
        add_voice_menu(menu, push_to_talk, assistant, config, apply_settings)
        add_speak_menu(menu, speaker, config, apply_settings, gpu_prompt)
        add_memory_menu(menu, memory, assistant, config, apply_settings)

    character.extra_menu_builder = add_shared_menus

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("Warning: no system tray available. Right-click Alter Ego to quit.")

    tray = QSystemTrayIcon(app_icon, app)
    tray.setToolTip("Alter Ego - desktop companion")

    menu = QMenu()
    menu.addAction("Show Alter Ego", character.appear)
    menu.addAction("Hide Alter Ego", character.disappear)
    menu.addAction("Chat...", open_chat)
    add_shared_menus(menu)
    menu.addSeparator()
    menu.addAction("Quit", quit_app)
    tray.setContextMenu(menu)

    # Left-clicking the tray icon toggles the character window.
    tray.activated.connect(
        lambda reason: toggle_character(character)
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()

    return app.exec()
