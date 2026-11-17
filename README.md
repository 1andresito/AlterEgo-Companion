# Alter Ego

An open-source desktop companion built with Python and PySide6, inspired by the digital character Alter Ego from Danganronpa.

**Current version: v0.6.0 — Alter Ego talks back.** Alter Ego lives on your desktop inside a green CRT monitor, opens a chat panel when you click it, and talks to you through the AI of your choice: a local model via [Ollama](https://ollama.com), **Claude through your existing Claude Code login (no API key)**, or any OpenAI-compatible API (ChatGPT, Groq, LM Studio, ...). Replies stream in word by word, and the character's face follows the mood of what it says. Conversations are saved locally, so Alter Ego picks up where you left off after a restart (see [Memory](#memory)). You can talk: **hold F9 and speak**, or switch on hands-free mode and just say **"Hey Alter Ego"**, even while it is hidden in the tray. Speech is recognised on your own computer with Whisper (see [Push to talk](#push-to-talk) and [Hands-free](#hands-free)). And now **Alter Ego answers out loud**, in a soft, youthful voice produced on your own computer with [Kokoro](https://github.com/thewh1teagle/kokoro-onnx), sentence by sentence while the reply is still arriving, with the text typing along to the voice (see [Spoken replies](#spoken-replies)). Runs on Windows and Linux.

> Without any provider, Alter Ego falls back to a small set of in-character "offline" lines, so the app always runs.

> This is an unofficial, fan-inspired project. It is not affiliated with or endorsed by Spike Chunsoft or the Danganronpa franchise.

## Features

- Frameless, always-on-top window. Everything outside the CRT artwork is transparent.
- Click Alter Ego to open a CRT-styled chat panel with message history and a text input.
- Three AI providers, switchable from the menu: Ollama (local), Claude via Claude Code (your subscription, no key), OpenAI-compatible APIs (your key). With Ollama, Alter Ego starts the server itself, downloads a first model if there is none, and switches Ollama off again when it quits or you pick another provider, so the model stops taking memory.
- Internet when you ask for it (Ollama and Claude): Alter Ego can look things up and read a web page when a question needs it. Switch it off with **AI** → **Allow internet**.
- Files in one folder: ask Alter Ego to make, read or list text files and it works in `Documents\Alter Ego`, and nowhere else. Before the first change it asks *"I'm going to be editing your folder ... Is this okay?"*. **AI** → **Let me work with files** switches it off, **AI** → **Open my files folder** shows it.
- Honest: when Alter Ego doesn't know something and can't check it, it says "I don't know" instead of guessing.
- Replies stream in as they are generated; the window never freezes.
- Push to talk: hold **F9** anywhere in Windows (or the **talk** button in the chat), speak, release. The words are recognised locally with Whisper and sent as a message. The key, microphone, engine and model are chosen from the **Voice** menu.
- Hands-free (opt-in): say **"Hey Alter Ego"** and the character appears, answers "Yes?" out loud, listens for what you want, answers, then waits for the wake phrase again. Optionally you can cut a hands-free reply short just by talking (off by default). The wake phrase is detected locally; no audio leaves the computer and none is stored.
- Spoken replies: Alter Ego reads every reply aloud with a local, offline text-to-speech model (Kokoro). Speech starts after the first sentence, the chat text types along with the voice, the delivery follows the mood (shy replies are softer and slower, passionate ones quicker), and volume and output device are chosen from the **Spoken replies** menu. Alter Ego has one voice, fixed in the program: nobody can switch it to another.
- Character voice: the Kokoro speech is converted with Alter Ego's own RVC voice model, which ships with the project in `assets/voice/`, so Alter Ego always speaks in one voice, offline and free. It runs on an NVIDIA graphics card when there is one and on the CPU otherwise, decided per computer.
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

- Windows 10 or 11, or Linux (tested on Fedora with Wayland). macOS is untested.
- Python 3.10+ (3.14 works; the optional character voice needs 3.10 to 3.13, so 3.12 is the safe choice)
- A working desktop session; on Linux, a system tray (for example Waybar's tray module) is useful but not required
- For push to talk: a microphone. `requirements.txt` includes [faster-whisper](https://github.com/SYSTRAN/faster-whisper) for local speech recognition; the first use downloads the speech model (about 150 MB for `base`). Everything else works without it.
- For spoken replies: speakers or headphones. `requirements.txt` includes [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) for local text-to-speech; the voice files (about 340 MB) are downloaded from the menu when you ask for them, never silently. Everything else works without it.
- For the character voice (optional): `requirements-character-voice.txt` adds [infer-rvc-python](https://github.com/R3gm/infer_rvc_python) and PyTorch (CPU build about 250 MB; the NVIDIA build about 3 GB, much faster), plus two base models downloaded from the menu (535 MB), The voice model itself comes with the project. See [One voice](#one-voice).

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

On Linux (Fedora, Ubuntu, ...), from a terminal in this folder:

```bash
python3.12 -m venv .venv     # or python3; 3.12 keeps the character voice possible
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

For the character voice, add (on any platform, inside the activated environment):

```bash
pip install -r requirements-character-voice.txt --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
pip install --no-deps infer-rvc-python==1.3.1
```

On a computer with an NVIDIA graphics card, replace PyTorch with its CUDA build afterwards; the voice then runs on the card, about three times faster (measured on an RTX 5070: a sentence in a quarter of its own length instead of four fifths):

```bash
pip install torch==2.11.0 torchaudio==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
```

Nothing else changes: Alter Ego checks at start whether PyTorch can use a card and otherwise uses the CPU, so the same project runs on a desktop with a big GPU and on a small laptop. The console says which (`character voice on the GPU (...)` or `on the CPU, 6 threads`). Set the environment variable `ALTER_EGO_DEVICE=cpu` to keep the voice off a weak or busy card. If the card cannot load the voice, Alter Ego falls back to the CPU by itself.

The second line of the first block is separate on purpose: the converter pins an older `pyworld` that has no ready-made Windows build for Python 3.12, so the requirements file installs a newer one and the converter is added without its pins.

Linux notes: audio goes through PipeWire/PulseAudio via Qt, nothing extra to install. The global push-to-talk key is Windows-only for now; on Linux hold the **talk** button in the chat panel, or use hands-free mode. If your compositor has no system tray, Alter Ego still runs: right-click the character for the menu.

## Choose an AI provider

Right-click Alter Ego → **AI** → **Provider**. Settings live in `data/config.json`; **AI** → **Edit settings file...** opens it in your editor. Restart is not needed: changes from the menu apply at once, edits to the file apply on the next start.

### Option A: Claude through Claude Code (no API key)

Uses the Claude login you already have in [Claude Code](https://claude.com/claude-code), so a Claude subscription is enough.

1. Install Claude Code, open a terminal, run `claude` and sign in with `/login`. Close it.
2. In Alter Ego: **AI** → **Provider** → **Claude (via Claude Code login)**, then **AI** → **Test connection**.
3. Optional: **AI** → **Model** to pick `opus`, `sonnet` or `haiku` (`default` = whatever Claude Code uses).

How it works: for each message Alter Ego runs `claude -p` in the background with the personality as system prompt, Claude Code's coding tools **disabled** (it cannot run commands or reach your files outside the Alter Ego folder), and your coding hooks, plugins and MCP servers switched off. Only what you allow under **AI** is offered: Claude's own web search and page reading for **Allow internet**, and Alter Ego's file tools for **Let me work with files** (see [Internet and files](#internet-and-files)). With a tool in use a reply may take a few seconds longer. Claude Code keeps the conversation context in its own session; clearing the chat starts a new one. Expect 3–8 seconds before the first word, since a new process starts each time. Set `"effort": "low"` under `claude_code` in the settings file for faster answers.

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

1. Install Ollama from <https://ollama.com/download>. That is the only step that needs you.
2. Start Alter Ego and choose **AI** → **Provider** → **Ollama (local)** (it is the default). Alter Ego looks after the rest:
   - If nothing is listening at the local address, it starts `ollama serve` itself and waits for it ("Starting Ollama..." shows in the chat). Choosing Ollama in the menu, or starting Alter Ego with Ollama chosen, does this at once, so the first reply is not delayed.
   - The first time you talk to it with no model installed, it downloads `llama3.2` (about 2 GB, once) and shows the progress in the chat before answering.
   - When you quit Alter Ego, or switch to another provider, Ollama is switched off so its model no longer takes memory. On Windows that includes the Ollama tray app and the model runners, even if you started them yourself; if Alter Ego crashes, Windows still stops the server it started. On Linux only a server Alter Ego started is stopped (a system service needs administrator rights).
   - A server Alter Ego starts keeps one model in memory and answers one reply at a time, which keeps memory use low.
   - The model is loaded as soon as Ollama is up ("Waking up my brain..." shows briefly) and stays loaded for 30 minutes after the last reply, so replies do not wait for it to load. Alter Ego talks to a local Ollama at `127.0.0.1` even when the setting says `localhost`: on Windows `localhost` cost about two seconds per request. Measured with `llama3.2` on an RTX 5070: the first word about 0.1 s after you press Enter.
3. Optional: **AI** → **Model** to pick another installed model (the first one is used by default), and **AI** → **Test connection** to have Alter Ego confirm everything works. More models: `ollama pull <name>` in a terminal, or set `default_model` in the settings file before the first run.

If Ollama is not installed, Alter Ego says so in the chat with the download link; it cannot install Ollama itself. If Ollama is on another machine or port, change `base_url` under `ollama` in the settings file: a remote server is never started or stopped by Alter Ego. `auto_start` and `auto_pull` switch the two behaviours off, and `command` can point at the Ollama executable if it is not on the PATH.

### Internet and files

Both work with Ollama and with Claude via Claude Code, and both are on by default. Alter Ego uses them only when a question needs them, and the chat shows what it is doing ("Searching the web...", "Writing notes.txt...").

- **Internet** (`tools.internet`): with Claude, Claude Code's own web search and page reading. With Ollama, Alter Ego searches Wikipedia and DuckDuckGo's instant answers (free, no key) and can read any web page you or the model name. That covers facts, people, places and definitions well; the latest news may not be there. For results from the whole web, set `search_url` to a [SearXNG](https://docs.searxng.org/) server (your own, or one you trust) with its JSON output enabled.
- **Files** (`tools.files`): list, read, write and make folders in one folder only, `Documents\Alter Ego` unless `folder` says otherwise. Paths that point anywhere else are refused. Before the first change Alter Ego asks *"I'm going to be editing your folder ... Is this okay?"*. Yes holds until you quit; after a no, it asks again the next time you want a file made. Alter Ego cannot run programs or commands.
- Small local models are not always good with tools. `llama3.2` handles both; if a model can't use tools at all, Alter Ego just chats with it. Tool calls the model writes out as text are recognised and run as well.

### The settings file

`data/config.json` is created the first time a setting is changed. All keys with their defaults:

```json
{
  "provider": "ollama",
  "ollama":      { "base_url": "http://localhost:11434", "model": "", "command": "ollama",
                   "auto_start": true, "auto_pull": true, "default_model": "llama3.2" },
  "claude_code": { "command": "claude", "model": "", "effort": "" },
  "openai":      { "base_url": "https://api.openai.com/v1", "api_key": "", "model": "" },
  "tools":       { "internet": true, "files": true, "folder": "", "search_url": "" },
  "memory":      { "enabled": true, "context_messages": 30 },
  "speech": {
    "enabled": true,
    "push_to_talk_key": "F9",
    "microphone": "",
    "transcriber": "whisper",
    "whisper_model": "base",
    "openai_model": "whisper-1",
    "language": "",
    "review_before_sending": false,
    "hands_free": false,
    "wake_phrase": "hey alter ego",
    "wake_model": "tiny",
    "wake_sensitivity": "normal",
    "awake_seconds": 3,
    "interrupt_by_voice": false
  },
  "voice": {
    "enabled": true,
    "volume": 0.8,
    "speaker": "",
    "models_dir": ""
  }
}
```

`provider` is one of `offline`, `ollama`, `claude_code`, `openai`. An empty `model` means "the first one available". The `tools` keys are explained under [Internet and files](#internet-and-files), the `memory` keys are explained under [Memory](#memory), the `speech` keys under [Push to talk](#push-to-talk) and the `voice` keys under [Spoken replies](#spoken-replies).

## Controls

| Action | How |
|---|---|
| Move | Left-click and drag Alter Ego |
| Open / close chat | Left-click Alter Ego (without dragging), or right-click → **Chat...**, or tray menu → **Chat...** |
| Send a message | Type in the chat panel and press **Enter** or click **send** |
| Talk instead of typing | Hold **F9** (works in any window), speak, release. Or hold the **talk** button in the chat panel. |
| Change the talk key, microphone or speech engine | Right-click Alter Ego → **Voice** |
| Talk without touching anything | **Voice** → **Hands-free**, then say "Hey Alter Ego" followed by your request |
| Hear the replies | On by default. Right-click Alter Ego → **Spoken replies** → **Download my voice** the first time; **Test my voice** plays a line |
| Give Alter Ego its character voice | Install the character-voice packages, then **Spoken replies** → **Download my voice** and **Prepare my voice** |
| Interrupt Alter Ego mid-sentence | Hold the talk key or the **talk** button (it goes quiet and listens), or **clear** the chat. Answering a hands-free request, with **Voice** → **Interrupt by talking** on: just start talking |
| Change the volume or speakers | Right-click Alter Ego → **Spoken replies** (the voice itself is fixed; see [One voice](#one-voice)) |
| Clear the conversation | **clear** in the chat panel header (the old conversation stays in memory on disk, it is just no longer shown) |
| Turn memory on or off | Right-click Alter Ego → **Memory** → **Remember conversations** |
| Wipe all memory | **Memory** → **Forget everything...** (asks for confirmation) |
| Hide the chat | **×** in the header, or press **Esc** |
| Move the chat | Drag it by its header. It follows Alter Ego until you move it yourself. |
| Choose AI provider / model | Right-click Alter Ego → **AI**, or tray menu → **AI** |
| Let Alter Ego go online, or not | **AI** → **Allow internet** |
| Let Alter Ego make and read files, or not | **AI** → **Let me work with files**; **AI** → **Open my files folder** shows them |
| Check the AI connection | **AI** → **Test connection** (Alter Ego answers in the chat; with Ollama this also starts the server and fetches a first model if needed) |
| Change size | Right-click Alter Ego → **Size** |
| Hide / show | Left-click the tray icon, or use either menu (with a burst of static) |
| Quit | Right-click menu or tray menu → **Quit** |

## Push to talk

Hold the talk key, say something, let go. Alter Ego opens the chat if it was hidden, shows "Listening..." while the key is down, recognises the words and sends them as if you had typed them. The character looks attentive while listening and thinks while recognising.

- **Key:** F9 by default. Change it under **Voice** → **Key** (function keys, Pause, Scroll Lock, the numpad, right Ctrl/Alt/Shift, or a mouse side button). The key is watched system-wide on Windows, so it works while you are in a game or an editor. Presses shorter than half a second are ignored; a recording stops by itself after 60 seconds.
- **Microphone:** the Windows default, or pick one under **Voice** → **Microphone**. Audio is captured with Qt, nothing is written to disk, and the microphone is open only while the key is held.
- **Engine, local (default):** [faster-whisper](https://github.com/SYSTRAN/faster-whisper), OpenAI's Whisper running on your CPU. Install it with `pip install -r requirements.txt`. The first use downloads the model into the Hugging Face cache (`%USERPROFILE%\.cache\huggingface`); use **Voice** → **Prepare speech recognition** to do that ahead of time. **Voice** → **Whisper model** picks the size: `tiny` is fastest, `base` (default) is a good balance, `small` is noticeably more accurate, `medium` and `large-v3` are slow without a GPU. The `.en` variants are English-only and a bit better at it.
- **Engine, API:** **Voice** → **Speech recognition** → **OpenAI-compatible API** sends the recording to `/audio/transcriptions` at the `base_url` from the `openai` section with that API key (OpenAI's `whisper-1`; set `openai_model` to `whisper-large-v3` for Groq). Your voice leaves the computer in that case.
- **Language:** detected automatically. Set `language` in the settings file to a code such as `en` or `es` for faster and more reliable results.
- **Review before sending:** with this on under **Voice**, the recognised text lands in the input box so you can fix it before pressing Enter. It also lands there whenever Alter Ego is still busy replying.
- If the speech package is missing, the microphone cannot be opened, or nothing could be made out, Alter Ego says so in the chat.

## Hands-free

Switch it on under **Voice** → **Hands-free (say "Hey Alter Ego")**. It is off by default because it keeps the microphone open while Alter Ego runs, including when it is hidden in the tray.

How it works, all on your computer:

1. A small loudness detector splits the microphone stream into utterances (something said between two pauses). Silence and background noise are discarded immediately; nothing is recorded to disk.
2. Each utterance is transcribed with the small, fast `tiny` Whisper model (`wake_model`), told to expect the phrase and to use your `language` (English if unset), and compared with the wake phrase. The match is forgiving: "Altar Ego", "Ultra Ego", "AlterEgo" and "um, hey Alter Ego" all count. Nothing else that is said while waiting is kept or shown.
3. On a match Alter Ego appears (with its static burst, if it was hidden), opens the chat, answers out loud with a short "Yes?" (or "I'm here!", from `wake_replies` in the personality file; with spoken replies off only the chat shows "I'm listening...") and listens. The answer is prepared when the voice loads, so it comes at once, and the listening window starts after it. What you say next is recognised with your main engine and sent. If you say nothing for `awake_seconds` (3 by default) it stops listening and waits for the wake phrase again; the countdown only runs while you are silent, so a long sentence is never cut short. "Hey Alter Ego, what time is it" in one breath works too.
4. After the reply it stops listening and waits for the wake phrase again: every new request starts with "Hey Alter Ego".
5. **Interrupt by talking** (**Voice** → **Interrupt by talking (hands-free)**, off by default): while Alter Ego answers something you asked hands-free, just start talking and it stops at once and listens; what you say is the next request. It only applies to replies to a hands-free request, not to typed or push-to-talk ones (hold the talk key to interrupt those). The microphone stays open while it talks, so use headphones: with speakers it may hear its own voice and cut itself off.

Notes:

- Hands-free needs the local Whisper package. The wake phrase is always checked locally, even when your main engine is an API; only the command after it goes to the API in that case.
- Holding the push-to-talk key pauses hands-free until you let go, so both can be on at once.
- `wake_phrase` can be anything short, for example `"computer"`. If the main Whisper model is the same as `wake_model`, only one model is loaded.
- Expect some CPU use whenever people are talking near the microphone, since every utterance is checked. If it wakes by mistake, the awake window simply times out.

If it does not respond when you say the phrase, run Alter Ego from a terminal (`python main.py`): every wake check is printed as `Hands-free heard: '...' -> no match` or `-> wake phrase`.

- **Nothing is printed when you speak:** the microphone did not pick you up as speech. Choose **Voice** → **Wake sensitivity** → **High**, check that **Voice** → **Microphone** is the right device, and raise the microphone level in Windows sound settings.
- **Something is printed but wrong** (for example `'hey, all to go'`): the small model misheard. Try `"wake_model": "base"` in the settings file (slower per check, better ears), set `"language"` to your language, or pick a wake phrase with longer, more distinct words.
- **Printed as the phrase but nothing happens:** it did wake, and the 3-second silence window closed before you spoke. Say your request straight after the phrase, or raise `awake_seconds`.
- If recognition fails (for example the package is missing), hands-free switches itself off and says why, instead of repeating the error for every sound.

## Spoken replies

Alter Ego reads its replies aloud. The voice is made on your own computer by [Kokoro](https://github.com/thewh1teagle/kokoro-onnx), a small (82 million parameter), Apache-licensed text-to-speech model that sounds natural and runs comfortably on a CPU: on a recent laptop a sentence is ready in about half the time it takes to say it, so speech starts well before the reply has finished arriving.

**First time:** right-click Alter Ego → **Spoken replies** → **Download my voice (338 MB)**. The files go into `data/voices/` (gitignored) and nothing is downloaded until you ask; before that, Alter Ego says once in the chat that its voice needs downloading. Install the package with `pip install -r requirements.txt` if you did not already.

How it works:

1. The `Speaker` watches the conversation like the chat panel does. As a reply streams in, every complete sentence is handed to a worker thread that runs the model; finished clips are played in order through the speakers (Qt Multimedia, so nothing extra to install). A reply that starts with "Oh! H-hello." is already being said while the rest is still being written.
2. The chat's typewriter follows the voice: each sentence is typed out over the time its audio takes, and the reply counts as finished (the face relaxes) only when the last clip has been played.
3. The delivery follows the expression the AI chose for the reply: `[shy]` and `[sad]` replies are spoken a little slower, `[passionate]` and `[surprised]` ones a little quicker.
4. While Alter Ego is talking the hands-free microphone is paused, so it never answers itself. Holding the push-to-talk key interrupts the speech.

### One voice

Alter Ego has exactly one voice, and it is part of the program, not a setting. There is no menu, setting or `config.json` key that picks another voice, engine, pitch or speed; old keys such as `kokoro_voice`, `rvc_model` or `pitch` left in a settings file are ignored. What you can change is whether it speaks, how loud, and through which speakers.

That voice is the character's own: Kokoro says the words, and a second model, RVC (Retrieval-based Voice Conversion), changes the timbre to that of Alter Ego's own voice model, trained for this project, so the delivery is Kokoro's and the voice is Alter Ego's. Everything runs on your CPU; nothing is sent anywhere and nothing costs anything. If the voice file is missing, the soft Kokoro blend (Heart, Bella and a little of the whispery Nicole, raised 2 semitones and with a light "inside a monitor" tone) stands in, so Alter Ego is never mute.

To give Alter Ego its voice you need:

1. The package: the two `pip install` lines shown under [Run from source](#run-from-source). It needs Python 3.10 to 3.13.
2. The two base models every RVC voice shares (the RMVPE pitch tracker and the HuBERT speech encoder, 535 MB): **Spoken replies** → **Download my voice**. They go into `data/voices/rvc/`.
3. The voice model, `assets/voice/alter_ego.pth` and `alter_ego.index` (about 87 MB). It is part of the project and stored with [Git LFS](https://git-lfs.com), so install Git LFS before cloning, or run `git lfs pull` afterwards. Without it, Git leaves a small placeholder file and Alter Ego uses the stand-in voice until you pull. No other model is used, and there is no folder to drop one into.

The character voice is played exactly as the model makes it: no pitch lift and no monitor tone. Its tuning is fixed in `src/alter_ego/voice/rvc_local.py` (`DEFAULT_PITCH` +7 semitones, which lifts the Kokoro source to the character's own speaking pitch; `DEFAULT_INDEX_RATE` 0.75; pitch tracker `rmvpe+`); the conversion uses all CPU threads but two.

The **Spoken replies** menu:

- **Speak replies out loud:** on/off (`enabled`).
- **My voice:** which voice is speaking: Alter Ego, or the stand-in if the voice file is missing.
- **Volume**, **Speakers:** loudness (`volume`, 0 to 1) and the output device (`speaker`, a device name or empty for the system default).
- **Download my voice** fetches whatever is missing; **Prepare my voice** loads the voice ahead of time; **Test my voice** says a line.

Speed: the voice is loaded in the background when Alter Ego starts (once it is downloaded), so the first reply does not wait for it. Measured for Kokoro plus the conversion together: about a quarter of the sentence's length on an NVIDIA RTX 5070, about four fifths on a desktop CPU (6 threads), more on a small laptop. With sentence-by-sentence playback the first sentence is heard one to a few seconds after the reply starts, and the chat text types along with the voice. Loaded, the voice takes about 2.7 GB of memory (3.1 GB on the GPU, with the CUDA libraries); with spoken replies off none of it is loaded.

The stammer Alter Ego writes ("I-I think", "th-thank you") is part of the character in the chat, but it is spoken as the plain word, because read aloud it sounded like a stutter of letters.

If the package is missing, the files are not downloaded, the speakers cannot be opened or the model fails, Alter Ego says so once in the chat and stays quiet until the settings change or you choose **Prepare my voice**; the text replies keep working as before.

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
| `wake_replies` | What Alter Ego says out loud right after "Hey Alter Ego" (one at random), so you know it is listening |
| `traits`, `description` | Reference for contributors |
| `system_prompt` | Instructions sent to the AI model before every conversation. Written as a list of lines for readability. It is kept short on purpose (about 150 words), because it is sent with every reply. |

The personality follows Chihiro Fujisaki, who made Alter Ego in the story: kind, soft-spoken and timid, quick to apologise, secretly determined to become stronger, flustered by compliments, and confident and precise about programming. It also tells the model to say "I don't know" rather than guess, and to report only what its tools really returned.

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
├── AI/                       # For AI assistants and contributors: rules, code style, architecture, plans
├── .claude/                  # Claude Code instructions (they point at AI/)
├── assets/
│   ├── animations/           # Expression PNGs
│   ├── personality/          # alter_ego.json
│   └── voice/                # Alter Ego's one voice: alter_ego.pth and .index (Git LFS)
├── data/                     # Created at runtime, gitignored: config.json, memory.db
├── src/
│   └── alter_ego/
│       ├── __init__.py       # Package version
│       ├── app.py            # Starts the app, wires everything together, tray icon
│       ├── ai_menu.py        # "AI" submenu: provider, model, internet and files on/off, test connection
│       ├── tool_approval.py  # Asks the user before the AI first changes a file (a Yes/No dialog)
│       ├── memory_menu.py    # "Memory" submenu: on/off, what is stored, forget everything
│       ├── voice_menu.py     # "Voice" submenu: push to talk on/off, key, microphone, engine
│       ├── speak_menu.py     # "Spoken replies" submenu: on/off, volume, speakers
│       ├── character.py      # Desktop window: drawing, effects, dragging, menus
│       ├── chat.py           # Chat panel: history, day dividers, input, talk button, typewriter (paced to the voice)
│       ├── expressions.py    # Expression list + ExpressionManager
│       ├── reactions.py      # Makes the face follow the conversation and the microphone
│       ├── core/             # No UI in here
│       │   ├── personality.py    # Loads the personality JSON
│       │   ├── conversation.py   # Message + Conversation history
│       │   ├── memory.py         # MemoryStore: saves the Conversation to SQLite, restores it
│       │   ├── tools.py          # ToolBox: web search, reading pages, files in one folder (what the AI may do)
│       │   └── assistant.py      # Assistant (worker thread, expression tags), responders
│       ├── providers/        # AI backends (all standard library, no SDKs)
│       │   ├── base.py           # Provider interface + ProviderError
│       │   ├── ollama.py         # Ollama over HTTP (chat with tool calls, model list, model download with progress)
│       │   ├── ollama_server.py  # Starts `ollama serve` when nothing answers locally, switches Ollama off on quit
│       │   ├── claude_code.py    # Claude via the `claude -p` command (your login), web tools on request
│       │   ├── tools_mcp.py      # Alter Ego's file tools for Claude Code (a tiny MCP server) + the approval bridge
│       │   └── openai_compat.py  # OpenAI-style /chat/completions (SSE streaming)
│       ├── speech/           # Voice input
│       │   ├── audio.py          # AudioClip: raw microphone PCM -> 16 kHz mono samples, WAV export
│       │   ├── recorder.py       # MicrophoneRecorder (Qt Multimedia)
│       │   ├── hotkey.py         # The global push-to-talk key (Windows key polling)
│       │   ├── controller.py     # PushToTalk: hold -> record -> recognise on a worker thread
│       │   ├── vad.py            # UtteranceDetector: cuts a live stream into utterances by loudness
│       │   ├── wake.py           # Fuzzy matching of the wake phrase in a transcript
│       │   ├── handsfree.py      # HandsFree: wait for the phrase -> awake -> command -> follow-up
│       │   ├── transcriber.py    # Transcriber interface + TranscriptionError
│       │   ├── whisper_local.py  # faster-whisper, offline
│       │   └── openai_stt.py     # /audio/transcriptions on an OpenAI-compatible API
│       ├── voice/            # Voice output
│       │   ├── synthesizer.py    # Synthesizer interface + SynthesisError, Speech clip
│       │   ├── text.py           # Cuts a streaming reply into sentences
│       │   ├── effects.py        # Pitch lift (resampling), the CRT tone, PCM conversion
│       │   ├── kokoro_local.py   # kokoro-onnx, offline; voice presets; downloads the model files
│       │   ├── rvc_local.py      # The character voice: Kokoro speech converted with the RVC model in assets/voice/
│       │   ├── device.py         # GPU or CPU for the voice, decided per computer (ALTER_EGO_DEVICE overrides)
│       │   ├── player.py         # SpeechPlayer (Qt Multimedia audio sink)
│       │   └── speaker.py        # Speaker: conversation -> sentences -> worker thread -> player, in order
│       └── settings/
│           └── config.py         # Loads/saves data/config.json
├── tests/
│   ├── test_core.py
│   ├── test_memory.py        # Memory store, context trimming, welcome-back, session file
│   ├── test_speech.py        # Audio conversion, key names, API engine, push-to-talk states
│   ├── test_handsfree.py     # Utterance detector, wake-phrase matching, hands-free states
│   ├── test_voice.py         # Sentence splitting, effects, Kokoro, the character voice, the fixed voice choice, Speaker states
│   ├── test_providers.py     # Providers against fake servers, a fake `claude` and a fake `ollama`
│   ├── test_tools.py         # Web and file tools, tool calls in Ollama and Claude, approval, stopping Ollama
│   ├── test_wake_and_speed.py  # The "Yes?" after the wake phrase, voice preload, GPU/CPU choice, unspoken stammer
│   ├── fake_claude.py        # Stand-in for the Claude Code command
│   └── fake_ollama.py        # Stand-in for `ollama serve`
├── main.py                   # Entry point: python main.py (with --tool-server: the file-tool server for Claude Code)
├── requirements.txt
├── requirements-character-voice.txt  # Optional: RVC voice conversion (PyTorch, Python 3.10 to 3.13)
├── LICENSE
└── README.md
```

How the pieces talk to each other (all through Qt signals, so modules stay independent):

1. The chat panel calls `Assistant.send(text)`.
2. The `Assistant` adds the user's message to the `Conversation`, switches to `THINKING`, and starts a worker thread that first lets the `Responder` prepare (with Ollama: start the server, download a first model, progress shown in the chat) and then asks it for a reply. Network waits happen on that thread, so the desktop stays responsive. **Test connection** and the warm-up after choosing a provider run on the same kind of worker.
3. `ProviderResponder` builds the prompt (personality system prompt + tag instruction + history) and streams text from the `Provider` (`OllamaProvider`). If the model asks for a tool (a web search, writing a file), the provider runs it from the `ToolBox` (`core/tools.py`), reports it in the chat ("Searching the web..."), and lets the model continue with the result. The offline responder plugs into the same slot.
4. As pieces arrive, the `Assistant` strips the leading expression tag, adds the reply to the `Conversation` and keeps updating its text (`message_updated`).
5. The chat panel types the growing text out; `CharacterReactions` sets the face as soon as the tag is known; when typing finishes it waits a few seconds and returns the face to Happy.
6. The `MemoryStore` listens to the same `Conversation` signals: it inserts each new message, writes a streamed reply once when it is complete, and marks the conversation as ended when the chat is cleared. At start-up it loads the last conversation into the `Conversation` before the windows are connected.
7. Voice comes in from the side: the global key (or the talk button) calls `PushToTalk.start()`/`stop()`. The controller records through the `MicrophoneRecorder`, runs the `Transcriber` on a worker thread and emits the text; the chat panel then calls `Assistant.send(text)`, exactly as if it had been typed. `CharacterReactions` listens to the same state signal for the listening face.
8. `HandsFree` uses the recorder in streaming mode, feeds the `UtteranceDetector`, checks each utterance against the wake phrase with the small model, and emits `woke` (the app shows the character and chat) and then `command(text)`, which the chat panel sends the same way. The chat's `typing_finished` tells it when a reply is over, so it can open the follow-up window.
9. The `Speaker` listens to the same `Conversation` signals as the chat panel. It cuts each reply into sentences as the text grows, queues them on a worker thread that runs the `Synthesizer`, shapes the clips (pitch, CRT tone) and plays them in order through the `SpeechPlayer`. It emits `sentence_started(message, end, seconds)`, which the chat uses to pace its typewriter, and `finished(message)` when the last clip has been played; only then does the chat emit `typing_finished`. The app pauses hands-free while the `Speaker` is speaking.

Adding another backend means writing one `Provider` subclass in `providers/` and registering it in `providers/__init__.py`. Nothing else changes.

If you work on the project with an AI coding assistant (or want the house rules yourself), start with [`AI/README.md`](AI/README.md): it holds the non-negotiable rules, the code style, an architecture map and the current plans. Tool folders such as `.claude/` only point there.

## Running the tests

```powershell
python -m unittest discover -s tests -v
```

The tests cover the non-visual parts: personality and config loading, conversation history, expression-tag parsing and reply clean-up, the assistant's streaming send/reply cycle (including failures and cancellation), the memory store (saving, restoring, clearing, forgetting), context trimming, audio conversion, the utterance detector, wake-phrase matching, the push-to-talk and hands-free state machines with a fake microphone and engines, the API speech engine against a fake server, sentence splitting, the voice effects, the character voice with a fake converter, how the one fixed voice is chosen, the Speaker state machine with a fake engine and a fake player, all three providers against fakes (a fake Ollama server, a fake OpenAI server and a fake `claude` command), and the web and file tools (fake web pages, a temporary folder, tool calls through the fake Ollama and the file-tool server, the approval question, stopping Ollama). They need neither Ollama, Claude Code, an API key, a microphone, speakers, the Whisper package nor the Kokoro files, and they write only to temporary folders. On a machine without a display, run them with `QT_QPA_PLATFORM=offscreen`.

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
- [x] v0.5.0: Voice input: push to talk and hands-free "Hey Alter Ego", with local speech recognition (Whisper) or an API
- [x] v0.6.0: Spoken replies: one fixed voice, the character's own (Kokoro converted with an RVC model, all local), sentence-by-sentence streaming, text paced to the voice
- [ ] v0.7.0: Scheduled updates and notifications
- [ ] Later: long-term recall of older conversations

## Privacy

- **Microphone:** by default opened only while the push-to-talk key or the talk button is held, and closed the moment you let go. No audio files are written to disk. With the default local engine the recording never leaves your computer; with the API engine it is uploaded to the service at `base_url`. Switch voice input off entirely under **Voice** → **Push to talk**.
  - **Hands-free** (off by default) keeps the microphone open while the app runs. Audio is analysed in memory and discarded; only after the wake phrase is heard is the next thing you say treated as a message. The wake-phrase check is always local. See [Hands-free](#hands-free).
- **Speakers:** with the default local engine, the voice is produced on your computer and nothing is sent anywhere. The one-time voice download comes from the kokoro-onnx GitHub release and happens only when you choose it in the menu. The character voice is also fully local; its two base models come from Hugging Face, again only when you choose **Download my voice**, and the voice model itself ships with the project in `assets/voice/`.
- **Network:** depends on the provider you choose, and nothing is sent anywhere else.
  - *Offline:* no network at all.
  - *Ollama:* your messages, the conversation history and the personality prompt go to the Ollama server in your settings (`http://localhost:11434` by default, your own computer). The one-time model download comes from ollama.com through the Ollama server; nothing of yours is sent with it.
  - *Internet tool* (on by default, **AI** → **Allow internet**): with Ollama, when the model decides to search, the search words go to Wikipedia (`en.wikipedia.org`) and DuckDuckGo (`api.duckduckgo.com`), or to your SearXNG server if `search_url` is set, and pages it reads are fetched from their sites. Your conversation is not sent, only the search words and addresses. With Claude, Claude Code's own web tools are used under your Anthropic account. Switch it off and nothing goes online except the provider itself.
  - *Claude via Claude Code:* the same text is sent to Anthropic by the Claude Code command under your own account, subject to Anthropic's privacy terms. Claude Code also stores the session transcript locally under its own folder (`~/.claude/`).
  - *OpenAI-compatible:* the same text is sent to the service at `base_url` with your API key, subject to that service's terms.
- **Storage:** Alter Ego writes two files, both in `data/` (gitignored) and both only on your computer:
  - `config.json`: your settings and, if you use one, your API key. Keep it private.
  - `memory.db`: your conversations, as plain SQLite. Switch saving off with **Memory** → **Remember conversations**, or delete everything with **Memory** → **Forget everything...**. With memory off, conversations are kept in RAM only and are gone when the app quits.
  - With Claude via Claude Code, `data/claude_code/session` holds the id of the Claude Code session being resumed; Claude Code itself keeps the transcript under `~/.claude/`.
  - With **Let me work with files** on, the AI reads and writes files in `Documents\Alter Ego` (or `tools.folder`), only after you said yes, and nowhere else. `data/claude_code/mcp.json` tells Claude Code how to start Alter Ego's file-tool server; it holds a one-time code that changes every run.
  - `voices/` holds the downloaded Kokoro files, and the RVC base models (`rvc/`) (no personal data). Delete the folder to free the space.
