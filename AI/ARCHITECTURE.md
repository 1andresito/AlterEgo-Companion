# Architecture

The README's "How the code is organized" section has the file tree and the numbered walk-through of a message's life. This page is the shorter map for deciding where something goes.

## The spine

```
user input ──> Assistant.send(text) ──> Responder/Provider (worker thread) ──> Conversation
                                                                                 │ signals
         ┌───────────────┬──────────────────┬───────────────────┬────────────────┤
         ▼               ▼                  ▼                   ▼                ▼
     ChatWindow    CharacterReactions    MemoryStore         Speaker         (anything new)
     (text, typing) (face)              (SQLite)            (voice out)
```

`Conversation` (`core/conversation.py`) is the single source of truth. It holds `Message` objects and emits `message_added`, `message_updated`, `cleared`. Everything that reacts to a reply observes it; nothing writes to the UI directly.

`Assistant` (`core/assistant.py`) turns a user message into a streamed reply: it adds the user message, runs the `Responder` on a worker thread, strips the leading expression tag (`[shy]`), cleans stage directions and emojis, and keeps updating one assistant `Message` until it is `complete`.

## Inputs

- Typing: `ChatWindow` calls `Assistant.send`.
- Push to talk: `PushToTalkKey` (global key, Windows) or the chat's talk button drive `PushToTalk` (`speech/controller.py`), which records with `MicrophoneRecorder` and runs a `Transcriber` on a worker thread; the chat sends the text.
- Hands-free: `HandsFree` (`speech/handsfree.py`) streams the microphone through `UtteranceDetector`, matches the wake phrase, and emits `command(text)`.

## Outputs

- Text: `ChatWindow` renders the history and types replies out. With a voice, its typewriter is paced by `Speaker.sentence_started`.
- Face: `CharacterReactions` maps assistant/listening/speaking states to an `Expression` on the `ExpressionManager`; `CharacterWindow` draws it with crossfades and CRT effects.
- Voice: `Speaker` (`voice/speaker.py`) cuts replies into sentences (`voice/text.py`), synthesizes on a worker thread (`Synthesizer`: Kokoro locally or an API), shapes the audio (`voice/effects.py`) and plays it in order (`SpeechPlayer`).
- Memory: `MemoryStore` writes every message to SQLite and restores the last conversation at start.

## Coordination lives in app.py

`app.run()` builds everything, connects the signals between controllers, and holds the small cross-cutting rules (hands-free is paused while push-to-talk records or the voice speaks; holding the talk key interrupts speech; the chat opens when listening starts). It also defines `apply_settings()`, which rebuilds engines from `Config` after any menu change. Keep these rules there, not inside the controllers, so the controllers stay independent and testable.

## Adding things

| You want to add | Where |
|---|---|
| Another AI backend | `providers/<name>.py` implementing `Provider`; register in `providers/__init__.py`; add to the AI menu if it needs settings |
| Another speech-recognition engine | `speech/<name>.py` implementing `Transcriber`; `build_transcriber` in `speech/__init__.py`; `TRANSCRIBER_LABELS` |
| Another text-to-speech engine | `voice/<name>.py` implementing `Synthesizer`; `build_synthesizer` in `voice/__init__.py`; `SYNTHESIZER_LABELS` |
| A new reaction of the face | `reactions.py` only |
| A new setting | `DEFAULTS` in `settings/config.py` (with comment), the menu module, `apply_settings` in `app.py`, the README defaults block |
| A new way to talk to Alter Ego | A controller `QObject` with a `state_changed` signal and a `command`/`transcribed`-style text signal; wire it in `app.py`; the chat sends the text |
| Something that must happen after a reply is fully delivered | Connect to `ChatWindow.typing_finished` (it waits for the voice too) |
| Platform-specific code | Its own module with a `supported` flag and a graceful no-op elsewhere, like `speech/hotkey.py` |

## Data on disk

All under `data/` (gitignored; `ALTER_EGO_DATA_DIR` overrides): `config.json`, `memory.db`, `claude_code/session`, `voices/` (Kokoro files). Whisper models go to the Hugging Face cache. Nothing else is written anywhere.
