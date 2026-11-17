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

`Assistant` (`core/assistant.py`) turns a user message into a streamed reply: it adds the user message, runs the `Responder` on a worker thread (first `prepare()`, which may start a server or download a model and reports through `Assistant.status`, then `stream_reply()`), strips the leading expression tag (`[shy]`), cleans stage directions and emojis, and keeps updating one assistant `Message` until it is `complete`. `Provider.warm_up()` is the lighter hook run when a provider is chosen; `providers/ollama_server.py` holds the one process handle for a server Alter Ego started, and `stop_all()` switches Ollama off on quit or when the user picks another provider (owner's decision: on Windows also the tray app and runners).

## Tools

`core/tools.py` holds the `ToolBox`: what the AI may do besides talking (web search, reading a page, files in one folder). `create_provider` builds one from the `tools` settings and hands it to the provider. `OllamaProvider` offers it through Ollama's tool calling and runs the calls itself (`stream_reply` loops: reply, tool calls, results, reply). `ClaudeCodeProvider` uses Claude Code's own `WebSearch`/`WebFetch` and reaches the file tools through `providers/tools_mcp.py`, an MCP server that is Alter Ego itself started with `--tool-server`. A file change first asks the user: `tool_approval.ToolApproval.ask()` (worker thread waits, GUI shows a Yes/No dialog), reached directly by Ollama and through `ApprovalServer` (127.0.0.1, one-time token) by the tool server. Tool progress goes to the chat through the `progress` callback of `stream_reply` and `Assistant.status`. Tools never raise and cap their results; paths outside the folder are refused.

## Inputs

- Typing: `ChatWindow` calls `Assistant.send`.
- Push to talk: `PushToTalkKey` (global key, Windows) or the chat's talk button drive `PushToTalk` (`speech/controller.py`), which records with `MicrophoneRecorder` and runs a `Transcriber` on a worker thread; the chat sends the text.
- Hands-free: `HandsFree` (`speech/handsfree.py`) streams the microphone through `UtteranceDetector`, matches the wake phrase, and emits `command(text)`.

## Outputs

- Text: `ChatWindow` renders the history and types replies out. With a voice, its typewriter is paced by `Speaker.sentence_started`.
- Face: `CharacterReactions` maps assistant/listening/speaking states to an `Expression` on the `ExpressionManager`; `CharacterWindow` draws it with crossfades and CRT effects.
- Voice: `Speaker` (`voice/speaker.py`) cuts replies into sentences (`voice/text.py`), synthesizes on a worker thread (`Synthesizer`), shapes the audio (`voice/effects.py`) and plays it in order (`SpeechPlayer`). There is one voice and it is not a setting: `build_synthesizer` returns Kokoro converted with the RVC model shipped in `assets/voice/alter_ego.pth` (Git LFS), or the Kokoro blend as a stand-in if that file is missing or only an LFS pointer. Do not add menu items or config keys that change the voice; tuning lives in constants in `rvc_local.py`. Where it runs is decided per machine by `voice/device.py` (CUDA when PyTorch sees an NVIDIA card, else the CPU at half the cores; `ALTER_EGO_DEVICE=cpu` overrides), never by a setting. `app.py` preloads the voice at start (`Speaker.preload()`, silent, never downloads) and has it render `quick_lines` (the wake replies) so `say()` plays them at once.
- Memory: `MemoryStore` writes every message to SQLite and restores the last conversation at start.

## Coordination lives in app.py

`app.run()` builds everything, connects the signals between controllers, and holds the small cross-cutting rules (hands-free is paused while push-to-talk records or the voice speaks; holding the talk key interrupts speech; the chat opens when listening starts). It also defines `apply_settings()`, which rebuilds engines from `Config` after any menu change. Keep these rules there, not inside the controllers, so the controllers stay independent and testable.

## Adding things

| You want to add | Where |
|---|---|
| Another AI backend | `providers/<name>.py` implementing `Provider`; register in `providers/__init__.py`; add to the AI menu if it needs settings |
| Something new the AI can do (a tool) | A spec and a branch in `core/tools.py` (`WEB_TOOLS`/`FILE_TOOLS`, `run`); a progress line in `progress_text`; anything that changes the computer goes through the approval |
| Another speech-recognition engine | `speech/<name>.py` implementing `Transcriber`; `build_transcriber` in `speech/__init__.py`; `TRANSCRIBER_LABELS` |
| A different way of producing Alter Ego's one voice | `voice/<name>.py` implementing `Synthesizer`; make `build_synthesizer` in `voice/__init__.py` return it (no user choice) |
| A new reaction of the face | `reactions.py` only |
| A new setting | `DEFAULTS` in `settings/config.py` (with comment), the menu module, `apply_settings` in `app.py`, the README defaults block |
| A new way to talk to Alter Ego | A controller `QObject` with a `state_changed` signal and a `command`/`transcribed`-style text signal; wire it in `app.py`; the chat sends the text |
| Something that must happen after a reply is fully delivered | Connect to `ChatWindow.typing_finished` (it waits for the voice too) |
| Platform-specific code | Its own module with a `supported` flag and a graceful no-op elsewhere, like `speech/hotkey.py` |

## Data on disk

All under `data/` (gitignored; `ALTER_EGO_DATA_DIR` overrides): `config.json`, `memory.db`, `claude_code/session`, `claude_code/mcp.json` (how Claude Code starts the file-tool server), `voices/` (Kokoro files, RVC base models in `rvc/`; the voice model itself is in `assets/voice/`, not here). Whisper models go to the Hugging Face cache. The AI's file tools write only in `Documents/Alter Ego` (`tools.folder`), after the user said yes. Nothing else is written anywhere.
