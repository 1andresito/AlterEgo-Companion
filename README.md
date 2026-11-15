# Alter Ego

An open-source desktop companion built with Python and PySide6, inspired by the digital character Alter Ego from Danganronpa.

**Current version: v0.2.0 — Conversation Interface.** Alter Ego lives on your desktop inside a green CRT monitor, opens a chat panel when you click it, reacts to the conversation with eight expressions, and runs quietly from the system tray. Real AI replies, voice, and memory are planned for later versions (see [Roadmap](#roadmap)).

> **No AI model is connected yet.** In v0.2.0 Alter Ego answers with a handful of short, in-character "offline" lines. v0.3.0 plugs an AI provider (Ollama first) into the same chat.

> This is an unofficial, fan-inspired project. It is not affiliated with or endorsed by Spike Chunsoft or the Danganronpa franchise.

## Features

- Frameless, always-on-top window. Everything outside the CRT artwork is transparent.
- Click Alter Ego to open a CRT-styled chat panel with message history and a text input.
- Replies are typed out letter by letter; the character's face follows the conversation (thinking → reply expression → back to idle).
- Personality lives in `assets/personality/alter_ego.json`, not in the code.
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

## Controls

| Action | How |
|---|---|
| Move | Left-click and drag Alter Ego |
| Open / close chat | Left-click Alter Ego (without dragging), or right-click → **Chat...**, or tray menu → **Chat...** |
| Send a message | Type in the chat panel and press **Enter** or click **send** |
| Clear the conversation | **clear** in the chat panel header |
| Hide the chat | **×** in the header, or press **Esc** |
| Move the chat | Drag it by its header. It follows Alter Ego until you move it yourself. |
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
| `system_prompt` | Instructions for the AI model (used from v0.3.0). Written as a list of lines for readability. |

Edit the file and restart the app. If the file is missing or broken, a small built-in default personality is used and a warning is printed.

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
├── src/
│   └── alter_ego/
│       ├── __init__.py       # Package version
│       ├── app.py            # Starts the app, wires everything together, tray icon
│       ├── character.py      # Desktop window: drawing, effects, dragging, menus
│       ├── chat.py           # Chat panel: history, input, typewriter reveal
│       ├── expressions.py    # Expression list + ExpressionManager
│       ├── reactions.py      # Makes the face follow the conversation
│       └── core/             # No UI in here
│           ├── personality.py    # Loads the personality JSON
│           ├── conversation.py   # Message + Conversation history
│           └── assistant.py      # Assistant, Responder, OfflineResponder
├── tests/
│   └── test_core.py
├── main.py                   # Entry point: python main.py
├── requirements.txt
├── LICENSE
└── README.md
```

How the pieces talk to each other (all through Qt signals, so modules stay independent):

1. The chat panel calls `Assistant.send(text)`.
2. The `Assistant` adds the user's message to the `Conversation`, switches to `THINKING`, asks its `Responder` for a reply, and adds that too.
3. The `Conversation` emits `message_added`. The chat panel hears it and types the reply out; `CharacterReactions` hears it and sets the face to the reply's expression.
4. When typing finishes, the reactions controller waits a few seconds and returns the face to Happy.

The `Responder` is the only part that will change in v0.3.0: the offline rule-based one gets swapped for an AI provider, and nothing else needs to know.

## Running the tests

```powershell
python -m unittest discover -s tests -v
```

The tests cover the non-visual core: personality loading, conversation history and the assistant's send/reply cycle.

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
- [ ] v0.3.0: Ollama / AI provider integration
- [ ] v0.4.0: Local wake-word detection and push-to-talk
- [ ] v0.5.0: Speech recognition and text-to-speech
- [ ] v0.6.0: Persistent memory
- [ ] v0.7.0: Scheduled updates and notifications

## Privacy

v0.2.0 does not access the microphone, does not use the network, and sends no data anywhere. Conversations are kept only in memory while the app runs and are gone when it quits. Voice activation, AI connectivity and persistent memory will come in later versions, with explicit user controls.
