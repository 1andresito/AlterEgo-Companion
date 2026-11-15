# Alter Ego

An open-source desktop companion built with Python and PySide6, inspired by the digital character Alter Ego from Danganronpa.

**Current version: v0.3.0 — AI Integration.** Alter Ego lives on your desktop inside a green CRT monitor, opens a chat panel when you click it, and talks to you through a local AI model served by [Ollama](https://ollama.com). Replies stream in word by word, and the character's face follows the mood of what it says. Voice and memory are planned for later versions (see [Roadmap](#roadmap)).

> Without Ollama, Alter Ego falls back to a small set of in-character "offline" lines, so the app always runs. Cloud providers (Claude, OpenAI-compatible APIs) are planned next.

> This is an unofficial, fan-inspired project. It is not affiliated with or endorsed by Spike Chunsoft or the Danganronpa franchise.

## Features

- Frameless, always-on-top window. Everything outside the CRT artwork is transparent.
- Click Alter Ego to open a CRT-styled chat panel with message history and a text input.
- Local AI through Ollama: pick any installed model, replies stream in as they are generated, the window never freezes.
- The AI chooses an expression for each reply; the character's face follows (thinking → reply expression → back to idle).
- Modular provider system: the chat, personality and reactions do not care which AI backend is answering.
- Personality lives in `assets/personality/alter_ego.json`, not in the code.
- Settings (provider, model, server URL) live in `data/config.json`, which is never committed.
- Offline fallback with friendly, in-character error messages when the AI cannot be reached.
- Eight character expressions, switchable from the right-click menu or the tray menu.
- Smooth crossfade when the expression changes.
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

## Set up the AI (Ollama)

1. Install Ollama from <https://ollama.com> and make sure it is running (it sits in the tray).
2. Download a model. A small one is fine for chatting:

   ```powershell
   ollama pull llama3.2
   ```

3. Start Alter Ego. Right-click the character → **AI** → **Model** to pick the model (the first installed one is used by default), and **AI** → **Test connection** to have Alter Ego confirm it can reach Ollama.

If Ollama is on another machine or port, edit `data/config.json` (created the first time you change a setting):

```json
{
  "provider": "ollama",
  "ollama": {
    "base_url": "http://localhost:11434",
    "model": "llama3.2"
  }
}
```

Set `"provider": "offline"` (or use **AI** → **Provider**) to run without any AI.

## Controls

| Action | How |
|---|---|
| Move | Left-click and drag Alter Ego |
| Open / close chat | Left-click Alter Ego (without dragging), or right-click → **Chat...**, or tray menu → **Chat...** |
| Send a message | Type in the chat panel and press **Enter** or click **send** |
| Clear the conversation | **clear** in the chat panel header |
| Hide the chat | **×** in the header, or press **Esc** |
| Move the chat | Drag it by its header. It follows Alter Ego until you move it yourself. |
| Choose AI provider / model | Right-click Alter Ego → **AI**, or tray menu → **AI** |
| Check the AI connection | **AI** → **Test connection** (Alter Ego answers in the chat) |
| Change expression | Right-click Alter Ego → **Expression**, or tray menu → **Expression** |
| Change size | Right-click Alter Ego → **Size** |
| Hide / show | Left-click the tray icon, or use either menu |
| Quit | Right-click menu or tray menu → **Quit** |

## Personality

Alter Ego's character is defined in `assets/personality/alter_ego.json`:

| Key | Used for |
|---|---|
| `name` | Shown in the chat panel |
| `greeting` | The first thing Alter Ego says when the chat opens |
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

Only use artwork you created or have permission to redistribute. Do not commit ripped game sprites, official character art, or voice clips without the relevant rights.

## How the code is organized

```text
AlterEgo-Companion/
├── assets/
│   ├── animations/           # Expression PNGs
│   └── personality/          # alter_ego.json
├── data/                     # Created at runtime, gitignored: config.json
├── src/
│   └── alter_ego/
│       ├── __init__.py       # Package version
│       ├── app.py            # Starts the app, wires everything together, tray icon
│       ├── ai_menu.py        # "AI" submenu: provider, model, test connection
│       ├── character.py      # Desktop window: drawing, effects, dragging, menus
│       ├── chat.py           # Chat panel: history, input, typewriter reveal
│       ├── expressions.py    # Expression list + ExpressionManager
│       ├── reactions.py      # Makes the face follow the conversation
│       ├── core/             # No UI in here
│       │   ├── personality.py    # Loads the personality JSON
│       │   ├── conversation.py   # Message + Conversation history
│       │   └── assistant.py      # Assistant (worker thread, expression tags), responders
│       ├── providers/        # AI backends
│       │   ├── base.py           # Provider interface + ProviderError
│       │   └── ollama.py         # Ollama over HTTP (standard library only)
│       └── settings/
│           └── config.py         # Loads/saves data/config.json
├── tests/
│   ├── test_core.py
│   └── test_providers.py     # Runs the Ollama provider against a fake local server
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

Adding another backend means writing one `Provider` subclass in `providers/` and registering it in `providers/__init__.py`. Nothing else changes.

## Running the tests

```powershell
python -m unittest discover -s tests -v
```

The tests cover the non-visual parts: personality and config loading, conversation history, expression-tag parsing, the assistant's streaming send/reply cycle (including failures and cancellation), and the Ollama provider against a fake local Ollama server. They do not need Ollama installed.

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
- [ ] v0.3.1: Cloud providers (Claude API, OpenAI-compatible APIs)
- [ ] v0.4.0: Local wake-word detection and push-to-talk
- [ ] v0.5.0: Speech recognition and text-to-speech
- [ ] v0.6.0: Persistent memory
- [ ] v0.7.0: Scheduled updates and notifications

## Privacy

- **Microphone:** not used. Voice features will arrive later with explicit controls.
- **Network:** the only connection Alter Ego makes is to the Ollama server in your settings, `http://localhost:11434` by default, which is your own computer. Your messages, the conversation history and the personality prompt are sent there to generate replies. Nothing is sent anywhere else. In offline mode no network is used at all.
- **Storage:** conversations are kept in memory only and are gone when the app quits. The only file written is `data/config.json` with your provider settings.

When cloud providers are added, using one will be an explicit choice, and the README will say exactly what leaves your machine.
