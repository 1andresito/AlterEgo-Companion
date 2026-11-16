# Alter Ego

An open-source desktop companion built with Python and PySide6, inspired by the digital character Alter Ego from Danganronpa.

**Current version: v0.4.0 — persistent memory.** Alter Ego lives on your desktop inside a green CRT monitor, opens a chat panel when you click it, and talks to you through the AI of your choice: a local model via [Ollama](https://ollama.com), **Claude through your existing Claude Code login (no API key)**, or any OpenAI-compatible API (ChatGPT, Groq, LM Studio, ...). Replies stream in word by word, and the character's face follows the mood of what it says. Conversations are now saved locally, so Alter Ego picks up where you left off after a restart (see [Memory](#memory)). Voice is planned for the next versions (see [Roadmap](#roadmap)).

> Without any provider, Alter Ego falls back to a small set of in-character "offline" lines, so the app always runs.

> This is an unofficial, fan-inspired project. It is not affiliated with or endorsed by Spike Chunsoft or the Danganronpa franchise.

## Features

- Frameless, always-on-top window. Everything outside the CRT artwork is transparent.
- Click Alter Ego to open a CRT-styled chat panel with message history and a text input.
- Three AI providers, switchable from the menu: Ollama (local), Claude via Claude Code (your subscription, no key), OpenAI-compatible APIs (your key).
- Replies stream in as they are generated; the window never freezes.
- Persistent memory: the conversation is saved in a local SQLite file and restored on the next start, with day dividers in the chat and a "welcome back" line after a long pause. Switch it off or wipe it from the **Memory** menu.
- With Claude via Claude Code, the Claude session is resumed after a restart too, so Claude remembers as much as the chat panel shows.
- The AI chooses an expression for each reply; the character's face follows (thinking → reply expression → back to idle).
- Modular provider system: the chat, personality and reactions do not care which AI backend is answering.
- Personality lives in `assets/personality/alter_ego.json`, not in the code.
- Replies are spoken words only: stage directions like `*giggles*`, emojis and markdown are filtered out.
- TV-static effect when Alter Ego appears and disappears.
- Settings (provider, model, server URL) live in `data/config.json`, which is never committed. Memory lives in `data/memory.db`, also never committed.
- Offline fallback with friendly, in-character error messages when the AI cannot be reached.
- Eight character expressions, chosen automatically by the conversation, with a smooth crossfade between them.
- Subtle CRT "refresh sweep" that passes over the screen every few seconds.
- Four size presets: Small, Medium, Large, Full size.
- Drag the companion anywhere with the left mouse button.
- System tray icon: left-click to show/hide, right-click for the menu.
- Keeps running in the tray when hidden.
- Still starts if artwork is missing, showing a placeholder that names the missing file.

## Requirements

- Windows 10 or 11 (initial target)
- Python 3.10+
- A working desktop session

## Run from source

Open PowerShell in this folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

If PowerShell blocks activation, run this once in the current terminal, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Choose an AI provider

Right-click Alter Ego → **AI** → **Provider**. Settings live in `data/config.json`; **AI** → **Edit settings file...** opens it in your editor. Restart is not needed: changes from the menu apply at once, edits to the file apply on the next start.

### Option A: Claude through Claude Code (no API key)

Uses the Claude login you already have in [Claude Code](https://claude.com/claude-code), so a Claude subscription is enough.

1. Install Claude Code, open a terminal, run `claude` and sign in with `/login`. Close it.
2. In Alter Ego: **AI** → **Provider** → **Claude (via Claude Code login)**, then **AI** → **Test connection**.
3. Optional: **AI** → **Model** to pick `opus`, `sonnet` or `haiku` (`default` = whatever Claude Code uses).

How it works: for each message Alter Ego runs `claude -p` in the background with the personality as system prompt, **all tools disabled** (it cannot read your files or run commands) and your coding hooks/plugins switched off. Claude Code keeps the conversation context in its own session; clearing the chat starts a new one. Expect 3–8 seconds before the first word, since a new process starts each time. Set `"effort": "low"` under `claude_code` in the settings file for faster answers.

> **Terms:** this drives the official Claude Code command on your own computer with your own account. Whether a Claude subscription may be used by a third-party application like this one is governed by Anthropic's usage policies, which can change. Check them before relying on it, and use the API-key route if in doubt.

### Option B: OpenAI-compatible API (ChatGPT and many others)

Works with OpenAI, Groq, OpenRouter, Mistral, LM Studio, llama.cpp server, and anything else that offers `/v1/chat/completions`.

1. **AI** → **Edit settings file...** and fill in the `openai` section:

   ```json
   "openai": {
     "base_url": "https://api.openai.com/v1",
     "api_key": "sk-...",
     "model": "gpt-4o-mini"
   }
   ```

   The key can also come from the `OPENAI_API_KEY` environment variable. For Groq use `https://api.groq.com/openai/v1`, for LM Studio `http://localhost:1234/v1` (no key needed).
2. Restart Alter Ego, then **AI** → **Provider** → **OpenAI-compatible API** and **AI** → **Model**.

Your conversation text goes to that service; you pay for usage with your own key. Never commit `data/config.json`.

### Option C: Ollama (local, free)

1. Install Ollama from <https://ollama.com> and make sure it is running (it sits in the tray).
2. Download a model. A small one is fine for chatting:

   ```powershell
   ollama pull llama3.2
   ```

3. Start Alter Ego. Right-click the character → **AI** → **Model** to pick the model (the first installed one is used by default), and **AI** → **Test connection** to have Alter Ego confirm it can reach Ollama.

If Ollama is on another machine or port, change `base_url` under `ollama` in the settings file.

### The settings file

`data/config.json` is created the first time a setting is changed. All keys with their defaults:

```json
{
  "provider": "ollama",
  "ollama":      { "base_url": "http://localhost:11434", "model": "" },
  "claude_code": { "command": "claude", "model": "", "effort": "" },
  "openai":      { "base_url": "https://api.openai.com/v1", "api_key": "", "model": "" },
  "memory":      { "enabled": true, "context_messages": 30 }
}
```

`provider` is one of `offline`, `ollama`, `claude_code`, `openai`. An empty `model` means "the first one available". The `memory` keys are explained under [Memory](#memory).

## Controls

| Action | How |
|---|---|
| Move | Left-click and drag Alter Ego |
| Open / close chat | Left-click Alter Ego (without dragging), or right-click → **Chat...**, or tray menu → **Chat...** |
| Send a message | Type in the chat panel and press **Enter** or click **send** |
| Clear the conversation | **clear** in the chat panel header (the old conversation stays in memory on disk, it is just no longer shown) |
| Turn memory on or off | Right-click Alter Ego → **Memory** → **Remember conversations** |
| Wipe all memory | **Memory** → **Forget everything...** (asks for confirmation) |
| Hide the chat | **×** in the header, or press **Esc** |
| Move the chat | Drag it by its header. It follows Alter Ego until you move it yourself. |
| Choose AI provider / model | Right-click Alter Ego → **AI**, or tray menu → **AI** |
| Check the AI connection | **AI** → **Test connection** (Alter Ego answers in the chat) |
| Change size | Right-click Alter Ego → **Size** |
| Hide / show | Left-click the tray icon, or use either menu (with a burst of static) |
| Quit | Right-click menu or tray menu → **Quit** |

## Memory

Alter Ego remembers what you talked about. Everything stays on your computer.

- Every message is written to `data/memory.db`, a SQLite database (Python's built-in `sqlite3`, no extra install). When you start Alter Ego again, the last conversation is loaded back into the chat panel, up to the most recent 100 messages, and a divider shows where each day starts.
- If more than an hour has passed since the last message, Alter Ego greets you with its `return_greeting` instead of the first-time `greeting`.
- The AI gets the most recent `context_messages` messages (30 by default) as context with every reply, so it remembers recent exchanges without the prompt growing forever. Set it to `0` to send the whole conversation; raise it if your model has a large context window.
- **clear** in the chat panel ends the current conversation and starts a new one. Older conversations are kept in the database but are not shown or sent to the AI. A later version may use them for long-term recall.
- **Memory** → **Remember conversations** switches saving off (and on). Off means nothing new is written and nothing is restored at start.
- **Memory** → **Forget everything...** deletes the whole database after a confirmation. With Claude via Claude Code it also drops the Claude session, so the next message starts fresh.
- Claude via Claude Code keeps its own conversation history inside Claude Code. Alter Ego stores the session id in `data/claude_code/session` and resumes it after a restart while memory is on. If Claude Code no longer has that session, a new one starts automatically.

## Personality

Alter Ego's character is defined in `assets/personality/alter_ego.json`:

| Key | Used for |
|---|---|
| `name` | Shown in the chat panel |
| `greeting` | The first thing Alter Ego says when the chat opens |
| `return_greeting` | What Alter Ego says when the chat reopens after more than an hour with earlier messages remembered |
| `traits`, `description` | Reference for contributors |
| `system_prompt` | Instructions sent to the AI model before every conversation. Written as a list of lines for readability. |

Edit the file and restart the app. If the file is missing or broken, a small built-in default personality is used and a warning is printed.

### How the AI picks a face

Alongside the system prompt, Alter Ego asks the model to begin every reply with one tag such as `[shy]`, `[passionate]` or `[nervous]`. The tag is stripped before the text is shown and tells the character which expression to make. Small models occasionally forget the tag; the reply is then shown as-is with the neutral "Talk" face.

## Expression artwork

Expressions are loaded from `assets/animations/`. Each expression is **one complete PNG**, including the CRT frame, with a transparent background outside the frame. These are individual images, not sprite sheets.

| Expression (menu name) | File |
|---|---|
| Happy (default) | `AlterEgo_Happy.png` |
| Talk | `AlterEgo_Talk.png` |
| Passionate | `AlterEgo_PassionTalk.png` |
| Shy | `AlterEgo_ShyTalk.png` |
| Side glance | `AlterEgo_SideTalk.png` |
| Sad | `AlterEgo_Sad.png` |
| Surprised | `AlterEgo_SuprisedTalk.png` |
| Nervous | `AlterEgo_SweatTalk.png` |

To use your own artwork, replace these files and keep the same names. Requirements:

- All images should be the same size (the supplied ones are 676 × 391).
- Use a transparent PNG, so the desktop shows through around the monitor.
- The CRT sweep effect is drawn inside the screen area defined by `SOURCE_SCREEN_RECT` in `src/alter_ego/character.py`. Update it if your frame has a different shape.

The included artwork is fan-made for this non-commercial passion project. If you fork the project for anything else, use artwork you created or have permission to redistribute.

### Tray and taskbar icon

`assets/AlterEgoIcon.jpg` is cropped to a circle with a green ring and used for the tray icon, the taskbar and Alt-Tab. Replace it with any square image (PNG works too if you change `ICON_FILE` in `src/alter_ego/app.py`). Without the file, a simple "AE" badge is drawn instead.

For a packaged `.exe`, Task Manager and Explorer show the executable's own icon, so also pass `--icon your_icon.ico` to PyInstaller.

## How the code is organized

```text
AlterEgo-Companion/
├── assets/
│   ├── animations/           # Expression PNGs
│   └── personality/          # alter_ego.json
├── data/                     # Created at runtime, gitignored: config.json, memory.db
├── src/
│   └── alter_ego/
│       ├── __init__.py       # Package version
│       ├── app.py            # Starts the app, wires everything together, tray icon
│       ├── ai_menu.py        # "AI" submenu: provider, model, test connection
│       ├── memory_menu.py    # "Memory" submenu: on/off, what is stored, forget everything
│       ├── character.py      # Desktop window: drawing, effects, dragging, menus
│       ├── chat.py           # Chat panel: history, day dividers, input, typewriter reveal
│       ├── expressions.py    # Expression list + ExpressionManager
│       ├── reactions.py      # Makes the face follow the conversation
│       ├── core/             # No UI in here
│       │   ├── personality.py    # Loads the personality JSON
│       │   ├── conversation.py   # Message + Conversation history
│       │   ├── memory.py         # MemoryStore: saves the Conversation to SQLite, restores it
│       │   └── assistant.py      # Assistant (worker thread, expression tags), responders
│       ├── providers/        # AI backends (all standard library, no SDKs)
│       │   ├── base.py           # Provider interface + ProviderError
│       │   ├── ollama.py         # Ollama over HTTP
│       │   ├── claude_code.py    # Claude via the `claude -p` command (your login)
│       │   └── openai_compat.py  # OpenAI-style /chat/completions (SSE streaming)
│       └── settings/
│           └── config.py         # Loads/saves data/config.json
├── tests/
│   ├── test_core.py
│   ├── test_memory.py        # Memory store, context trimming, welcome-back, session file
│   ├── test_providers.py     # Providers against fake servers and a fake `claude`
│   └── fake_claude.py        # Stand-in for the Claude Code command
├── main.py                   # Entry point: python main.py
├── requirements.txt
├── LICENSE
└── README.md
```

How the pieces talk to each other (all through Qt signals, so modules stay independent):

1. The chat panel calls `Assistant.send(text)`.
2. The `Assistant` adds the user's message to the `Conversation`, switches to `THINKING`, and starts a worker thread that asks its `Responder` for a reply. Network waits happen on that thread, so the desktop stays responsive.
3. `ProviderResponder` builds the prompt (personality system prompt + tag instruction + history) and streams text from the `Provider` (`OllamaProvider`). The offline responder plugs into the same slot.
4. As pieces arrive, the `Assistant` strips the leading expression tag, adds the reply to the `Conversation` and keeps updating its text (`message_updated`).
5. The chat panel types the growing text out; `CharacterReactions` sets the face as soon as the tag is known; when typing finishes it waits a few seconds and returns the face to Happy.
6. The `MemoryStore` listens to the same `Conversation` signals: it inserts each new message, writes a streamed reply once when it is complete, and marks the conversation as ended when the chat is cleared. At start-up it loads the last conversation into the `Conversation` before the windows are connected.

Adding another backend means writing one `Provider` subclass in `providers/` and registering it in `providers/__init__.py`. Nothing else changes.

## Running the tests

```powershell
python -m unittest discover -s tests -v
```

The tests cover the non-visual parts: personality and config loading, conversation history, expression-tag parsing and reply clean-up, the assistant's streaming send/reply cycle (including failures and cancellation), the memory store (saving, restoring, clearing, forgetting), context trimming, and all three providers against fakes (a fake Ollama server, a fake OpenAI server and a fake `claude` command). They need neither Ollama, Claude Code nor an API key, and they write only to temporary folders.

## Build a Windows executable

```powershell
pip install pyinstaller
pyinstaller --noconfirm --clean --windowed --name AlterEgo `
  --add-data "assets;assets" `
  --paths src `
  main.py
```

The executable will be in `dist/AlterEgo/AlterEgo.exe`. The app finds the bundled `assets` folder automatically.

## Roadmap

- [x] v0.1.0: CRT desktop companion, draggable window, system tray
- [x] v0.1.1: Expression system, crossfade transitions, CRT sweep, size presets
- [x] v0.2.0: Chat panel, character reactions, personality configuration
- [x] v0.3.0: Provider framework, Ollama, streaming replies, AI-chosen expressions
- [x] v0.3.1: Claude via Claude Code login, OpenAI-compatible APIs
- [x] v0.4.0: Persistent memory (conversations survive restarts, Memory menu)
- [ ] v0.5.0: Local wake-word detection and push-to-talk
- [ ] v0.6.0: Speech recognition and text-to-speech
- [ ] v0.7.0: Scheduled updates and notifications
- [ ] Later: long-term recall of older conversations

## Privacy

- **Microphone:** not used. Voice features will arrive later with explicit controls.
- **Network:** depends on the provider you choose, and nothing is sent anywhere else.
  - *Offline:* no network at all.
  - *Ollama:* your messages, the conversation history and the personality prompt go to the Ollama server in your settings (`http://localhost:11434` by default, your own computer).
  - *Claude via Claude Code:* the same text is sent to Anthropic by the Claude Code command under your own account, subject to Anthropic's privacy terms. Claude Code also stores the session transcript locally under its own folder (`~/.claude/`).
  - *OpenAI-compatible:* the same text is sent to the service at `base_url` with your API key, subject to that service's terms.
- **Storage:** Alter Ego writes two files, both in `data/` (gitignored) and both only on your computer:
  - `config.json`: your settings and, if you use one, your API key. Keep it private.
  - `memory.db`: your conversations, as plain SQLite. Switch saving off with **Memory** → **Remember conversations**, or delete everything with **Memory** → **Forget everything...**. With memory off, conversations are kept in RAM only and are gone when the app quits.
  - With Claude via Claude Code, `data/claude_code/session` holds the id of the Claude Code session being resumed; Claude Code itself keeps the transcript under `~/.claude/`.
