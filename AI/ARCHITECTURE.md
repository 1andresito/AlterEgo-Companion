# Architecture

How the code is laid out, how a message travels through it, and where new things go.

## The spine

```
user input ──> Assistant.send(text) ──> Responder/Provider (worker thread) ──> Conversation
                                                                                 │ signals
         ┌───────────────┬──────────────────┬───────────────────┬────────────────┤
         ▼               ▼                  ▼                   ▼                ▼
     ChatWindow    CharacterReactions    MemoryStore         Speaker         (anything new)
     (text, typing) (face)              (SQLite)            (voice out)
```

`Conversation` (`core/conversation.py`) is the single source of truth. It holds `Message` objects and emits `message_added`, `message_updated` and `cleared`. Everything that reacts to a reply observes it. Nothing writes to the UI directly.

`Assistant` (`core/assistant.py`) turns a user message into a streamed reply. It adds the user message, then runs the `Responder` on a worker thread: first `prepare()`, which may start a server and reports through `Assistant.status`, then `stream_reply()`. It strips the leading expression tag (`[shy]`), cleans stage directions and emojis, and keeps updating one assistant `Message` until it is `complete`. `warm_up()` is the lighter hook, run when a provider is chosen.

## Layers

| Layer | May use | Must not |
|---|---|---|
| `settings/` | standard library | import Qt widgets |
| `core/` | `settings/`, `providers/`, `QObject` and signals | create widgets |
| `providers/` | standard library only | import Qt, or any SDK |
| `speech/`, `voice/` | `core/`, Qt Multimedia, optional engines imported lazily | do slow work on the GUI thread |
| UI modules (`chat.py`, `character.py`, `setup_wizard.py`, `*_menu.py`) | everything above | do slow work, or own rules about how pieces work together |
| `app.py` | everything | contain feature logic that could live in a controller |

## Code layout

```text
AlterEgo-Companion/
├── AI/                        # This guide: rules, architecture, style, decisions, plans, releasing
├── .claude/                   # Claude Code instructions (they point at AI/)
├── .github/workflows/
│   └── release.yml            # Builds and publishes the downloads when a version tag is pushed
├── assets/
│   ├── animations/            # Expression PNGs (one complete image per expression)
│   ├── personality/           # alter_ego.json
│   └── voice/                 # Alter Ego's one voice: alter_ego.pth and .index (Git LFS)
├── data/                      # Created at runtime when run from source, gitignored
├── docs/                      # User reference: settings, running from source, customizing
├── packaging/
│   ├── alter_ego.spec         # PyInstaller recipe (ALTER_EGO_LITE=1 leaves out the character voice)
│   ├── AlterEgo.ico           # The program's own icon
│   ├── windows/alter_ego.iss  # Inno Setup script for the Windows installer
│   └── linux/                 # install.sh, uninstall.sh, the .desktop launcher and icon
├── src/alter_ego/
│   ├── __init__.py            # Package version
│   ├── app.py                 # Builds everything, wires the signals, tray icon, first-run setup
│   ├── setup_wizard.py        # The setup window: install Ollama, pick a model, download the voice
│   ├── ai_menu.py             # "AI" submenu: provider, model, internet and files, setup, test connection
│   ├── voice_menu.py          # "Voice" submenu: push to talk, key, microphone, engine, hands-free
│   ├── speak_menu.py          # "Spoken replies" submenu: on/off, volume, speakers
│   ├── memory_menu.py         # "Memory" submenu: on/off, forget everything
│   ├── tool_approval.py       # Asks the user before the AI first changes a file (Yes/No dialog)
│   ├── character.py           # Desktop window: drawing, effects, dragging, menus
│   ├── chat.py                # Chat panel: history, day dividers, input, talk button, typewriter
│   ├── expressions.py         # Expression list + ExpressionManager
│   ├── reactions.py           # Makes the face follow the conversation and the microphone
│   ├── core/                  # No widgets in here
│   │   ├── personality.py     # Loads the personality JSON
│   │   ├── conversation.py    # Message + Conversation history
│   │   ├── memory.py          # MemoryStore: saves the Conversation to SQLite, restores it
│   │   ├── tools.py           # ToolBox: web search, reading pages, files in one folder
│   │   ├── first_run.py       # What is missing (SetupPlan) and getting it (SetupRunner, worker thread)
│   │   └── assistant.py       # Assistant (worker thread, expression tags), responders
│   ├── providers/             # AI backends (standard library only)
│   │   ├── base.py            # Provider interface + ProviderError
│   │   ├── ollama.py          # Ollama over HTTP: chat with tool calls, model list, model download
│   │   ├── ollama_server.py   # Starts `ollama serve` when needed, switches Ollama off on quit
│   │   ├── ollama_install.py  # Installs Ollama (Windows: official installer, silent; Linux: pkexec)
│   │   ├── claude_code.py     # Claude via the `claude -p` command (the user's login)
│   │   ├── tools_mcp.py       # Alter Ego's file tools for Claude Code (a tiny MCP server)
│   │   └── openai_compat.py   # OpenAI-style /chat/completions (SSE streaming)
│   ├── speech/                # Voice input
│   │   ├── audio.py           # AudioClip: microphone PCM -> 16 kHz mono samples
│   │   ├── recorder.py        # MicrophoneRecorder (Qt Multimedia)
│   │   ├── hotkey.py          # The global push-to-talk key (Windows key polling)
│   │   ├── controller.py      # PushToTalk: hold -> record -> recognise on a worker thread
│   │   ├── vad.py             # UtteranceDetector: cuts a live stream into utterances by loudness
│   │   ├── wake.py            # Fuzzy matching of the wake phrase
│   │   ├── handsfree.py       # HandsFree: wait for the phrase -> awake -> command
│   │   ├── transcriber.py     # Transcriber interface + TranscriptionError
│   │   ├── whisper_local.py   # faster-whisper, offline
│   │   └── openai_stt.py      # /audio/transcriptions on an OpenAI-compatible API
│   ├── voice/                 # Voice output
│   │   ├── synthesizer.py     # Synthesizer interface + SynthesisError, Speech clip
│   │   ├── text.py            # Cuts a streaming reply into sentences; what is spoken
│   │   ├── effects.py         # Pitch lift, the CRT tone, PCM conversion
│   │   ├── kokoro_local.py    # kokoro-onnx, offline; downloads its model files
│   │   ├── rvc_local.py       # The character voice: Kokoro converted with the RVC model
│   │   ├── device.py          # GPU or CPU for the voice, decided per computer
│   │   ├── player.py          # SpeechPlayer (Qt Multimedia audio sink)
│   │   └── speaker.py         # Speaker: conversation -> sentences -> worker -> player, in order
│   └── settings/
│       └── config.py          # DEFAULTS, loads/saves config.json, assets_dir(), data_dir()
├── tests/                     # One file per feature area, fakes only (see CODE_STYLE.md)
├── main.py                    # Entry point; --tool-server runs the file-tool server; log file when packaged
├── requirements.txt
├── requirements-character-voice.txt  # The RVC converter and PyTorch (Python 3.10 to 3.13)
├── CHANGELOG.md
├── CONTRIBUTING.md
└── README.md
```

## The life of a message

1. The chat panel calls `Assistant.send(text)`.
2. The `Assistant` adds the user's message to the `Conversation`, switches to `THINKING`, and starts a worker thread. The worker first lets the `Responder` prepare (with Ollama: start the server), then asks it for a reply. Network waits happen on that thread, so the desktop stays responsive. **Test connection** and the warm-up after choosing a provider run on the same kind of worker.
3. `ProviderResponder` builds the prompt (personality system prompt + tag instruction + recent history) and streams text from the `Provider`. If the model asks for a tool (a web search, writing a file), the provider runs it from the `ToolBox`, reports it in the chat ("Searching the web..."), and lets the model continue with the result. The offline responder plugs into the same slot.
4. As pieces arrive, the `Assistant` strips the leading expression tag, adds the reply to the `Conversation` and keeps updating its text (`message_updated`).
5. The chat panel types the growing text out. `CharacterReactions` sets the face as soon as the tag is known. When typing finishes, it waits a few seconds and returns the face to Happy.
6. The `MemoryStore` listens to the same signals: it inserts each new message, writes a streamed reply once it is complete, and marks the conversation as ended when the chat is cleared. At start-up it loads the last conversation before the windows are connected.
7. The `Speaker` listens too. It cuts each reply into sentences as the text grows, synthesizes them on a worker thread and plays them in order. It emits `sentence_started(message, end, seconds)`, which paces the chat's typewriter, and `finished(message)` after the last clip. Only then does the chat emit `typing_finished`.
8. Voice comes in from the side. The global key (or the talk button) drives `PushToTalk`, which records, transcribes on a worker thread and emits the text. The chat then calls `Assistant.send(text)` as if it had been typed. `HandsFree` streams the microphone through the `UtteranceDetector`, matches the wake phrase with a small model, and emits `woke` and then `command(text)`.

## First run

`app.run()` checks `config.setup_done`. If it is false, `core/first_run.make_plan()` looks at what is there: is Ollama installed, are there models (only when the server already answers), does the voice need downloading. If nothing is missing, setup is marked done silently. Otherwise `SetupWizard` opens after the character appears, and the start-up warm-up is skipped, so nothing fails noisily behind it. The wizard collects `SetupChoices`. `SetupRunner` runs them on a worker: `ollama_install.install()`, then `ollama_server.ensure_running()` and `OllamaProvider.pull()`, then `synthesizer.prepare()`. Each step reports on its own, and a failing step does not stop the next. When the window closes, `app.py` sets `setup.done`, applies the settings and preloads the voice. The same wizard opens from **AI** → **Set up Ollama and my voice...**.

## Tools

`core/tools.py` holds the `ToolBox`: what the AI may do besides talking (web search, reading a page, files in one folder).
- `create_provider` builds one from the `tools` settings.
- `OllamaProvider` offers it through Ollama's tool calling and runs the calls itself.
- `ClaudeCodeProvider` uses Claude Code's own `WebSearch`/`WebFetch`. It reaches the file tools through `providers/tools_mcp.py`, an MCP server that is Alter Ego itself started with `--tool-server` (this also works from the packaged exe).
- A file change first asks the user through `tool_approval.ToolApproval.ask()`. The worker thread waits while the GUI shows a Yes/No dialog. Ollama reaches it directly; the tool server reaches it through `ApprovalServer` (127.0.0.1, one-time token).
- Tools never raise, cap their results, and refuse paths outside the folder.

## Outputs in more detail

- **Face:** `CharacterReactions` maps assistant, listening and speaking states to an `Expression`. `CharacterWindow` draws it with crossfades and CRT effects.
- **Voice:** there is one voice, and it is not a setting.
  - `build_synthesizer` returns Kokoro converted with the RVC model in `assets/voice/alter_ego.pth`. If that file is missing, or is only a Git LFS pointer, the Kokoro blend stands in.
  - `voice/device.py` picks CUDA when PyTorch sees an NVIDIA card, else the CPU at half the cores. `ALTER_EGO_DEVICE=cpu` overrides it.
  - `app.py` preloads the voice at start. That never downloads anything. It also has the voice render the wake replies ahead of time, so "Yes?" plays at once.

## Coordination lives in app.py

`app.run()` builds everything, connects the controllers' signals, and holds the small rules that involve more than one piece:
- hands-free is paused while push to talk records or the voice speaks
- holding the talk key interrupts speech
- the chat opens when listening starts
- the setup runs before the warm-up

It also defines `apply_settings()`, which rebuilds engines from `Config` after any menu change; `EngineCache` keeps an engine while its settings stay the same. Keep these rules here, so the controllers stay independent and testable.

## Adding things

| You want to add | Where |
|---|---|
| Another AI backend | `providers/<name>.py` implementing `Provider`; register it in `providers/__init__.py`; add it to the AI menu if it needs settings |
| Something new the AI can do (a tool) | A spec and a branch in `core/tools.py` (`WEB_TOOLS`/`FILE_TOOLS`, `run`); a progress line in `progress_text`; anything that changes the computer goes through the approval |
| Another speech-recognition engine | `speech/<name>.py` implementing `Transcriber`; `build_transcriber` in `speech/__init__.py`; `TRANSCRIBER_LABELS` |
| A different way of producing Alter Ego's one voice | `voice/<name>.py` implementing `Synthesizer`; `build_synthesizer` in `voice/__init__.py` returns it (no user choice) |
| Something the first-run setup should offer | A check in `make_plan`, a `SetupStep` with a branch in `_SetupWorker._run_step`, a row in `SetupWizard`'s first page; show the size before anything downloads |
| A new reaction of the face | `reactions.py` only |
| A new setting | `DEFAULTS` in `settings/config.py` (with a comment), the menu module, `apply_settings` in `app.py`, `docs/SETTINGS.md` |
| A new way to talk to Alter Ego | A controller `QObject` with a `state_changed` signal and a text signal; wire it in `app.py`; the chat sends the text |
| Something that must happen after a reply is fully delivered | Connect to `ChatWindow.typing_finished` (it waits for the voice too) |
| Platform-specific code | Its own module with a `supported` flag and a graceful no-op elsewhere, like `speech/hotkey.py` |
| A new Python dependency | `requirements.txt` (or the voice file), a lazy import with a fallback, and `packaging/alter_ego.spec` if it ships data files or native libraries |

## Data on disk

Everything lives in one data folder (`settings/config.py` `data_dir()`):
- `data/` when run from source
- `%APPDATA%\AlterEgo` when packaged on Windows
- `~/.config/alter_ego` when packaged on Linux
- or wherever `ALTER_EGO_DATA_DIR` points

The folder holds:
- `config.json`
- `memory.db`
- `alter_ego.log` (packaged builds only)
- `claude_code/session`
- `claude_code/mcp.json`: how Claude Code starts the file-tool server
- `voices/`: the Kokoro files, plus the RVC base models in `rvc/`

The voice model itself is in `assets/voice/`, not here. Whisper models go to the Hugging Face cache. The AI's file tools write only in `Documents/Alter Ego` (`tools.folder`), after the user said yes. Nothing else is written anywhere.
