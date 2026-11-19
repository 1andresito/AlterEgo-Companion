# Alter Ego

**A desktop companion who lives in a little green CRT monitor on your screen.** Click it to chat, hold a key to talk, and it answers out loud. Everything can run on your own computer: free, private, no account needed.

<p align="center"><img src="assets/animations/AlterEgo_Happy.png" alt="Alter Ego on its CRT monitor" width="420"></p>

Inspired by the digital character Alter Ego from Danganronpa. Built with Python and PySide6, for Windows and Linux.

> This is an unofficial, non-commercial fan project. It is not affiliated with or endorsed by Spike Chunsoft or the Danganronpa franchise.

**Current version: v0.9.3** ([what's new](CHANGELOG.md))

---

## Download and install

Go to the **[Releases page](https://github.com/1andresito/AlterEgo-Companion/releases/latest)** and pick the file for your computer.

### Windows 10 / 11

- **`AlterEgo-Setup-vX.Y.Z.exe`** (recommended): run it and click through. It doesn't ask for administrator rights, and it adds Alter Ego to the Start menu (and, if you like, the desktop or Windows start-up).
- **`AlterEgo-vX.Y.Z-windows-portable.zip`**: unzip anywhere and run `AlterEgo.exe`. Nothing is installed.

Windows may warn that the app is from an "unknown publisher", because it isn't code-signed. Click **More info** → **Run anyway**.

### Linux

Download **`AlterEgo-vX.Y.Z-linux-x86_64.tar.gz`**, then:

```bash
tar -xzf AlterEgo-v*-linux-x86_64.tar.gz
cd AlterEgo-v*-linux-x86_64
./install.sh
```

Alter Ego then appears in your applications menu (and as the `alter-ego` command). `./uninstall.sh` removes it again, and asks what else should go. Or skip installing and just run `AlterEgo/AlterEgo`.

### The first start

Alter Ego appears in the top-right corner of your screen and asks what it should set up. Each item is a choice, and nothing is downloaded unless you tick it:

| Item | What it is | Size |
|---|---|---|
| **Install Ollama** | The free program that runs the AI on your computer | about 1.1 GB (Windows) |
| **AI model** | The "brain" Ollama runs. Pick one, or "Not now" | 1.3 to 4.7 GB |
| **Download my voice** | So Alter Ego can talk out loud | about 870 MB |

Which model? **Llama 3.2** suits most computers. **Llama 3.2 1B** is lighter, for small laptops. **Qwen 2.5 7B** is smarter, and needs 8 GB of free memory.

You can open the setup again any time from the right-click menu: **AI** → **Set up Ollama and my voice...**.

### Updates

When a new version is out, Alter Ego asks you at start-up: **Update now**, **Not now** or **Skip this version**. If you say yes, it downloads the new version, closes for a moment and starts again by itself. Your settings and memories stay. Check by hand from **AI** → **Check for updates now**, or switch the start-up check off with **AI** → **Check for updates at start-up**.

> Would you rather use ChatGPT or Claude instead of a local AI? Skip the Ollama items and see [Choosing an AI](#choosing-an-ai).

---

## What Alter Ego can do

- **Chat.** Click the character to open a CRT-styled chat panel. Replies appear word by word, and its face follows the mood of what it says.
- **Listen.** Hold **F9** anywhere in Windows and speak, or turn on hands-free and say **"Hey Alter Ego"**, even while it is hidden in the tray. Your speech is recognised on your computer.
- **Talk back.** Every reply is read out loud in Alter Ego's own voice, made on your computer, sentence by sentence while the reply is still arriving.
- **Remember.** Conversations are saved on your computer, so Alter Ego picks up where you left off.
- **Look things up.** For news, weather and questions about the world, Alter Ego searches the web first and reads a page, then answers in its own words. Switch this off with **AI** → **Allow internet**.
- **Work with files.** Ask it to make, change, read or list text files, anywhere on your computer. It asks before every change and shows you the full path. A bare file name goes in `Documents\Alter Ego`; reading somewhere else asks first, once per folder. **AI** → **Edit files without asking (risky)** skips the question for changes. It's off unless you switch it on, it warns you first, and it still asks for system folders and Alter Ego's own folders.
- **Be honest.** When it doesn't know something and can't check, it says "I don't know" instead of guessing.
- **Always start.** No AI, no microphone, no speakers? Alter Ego still runs and tells you, in character, what's missing.

---

## Using Alter Ego

Right-click Alter Ego (or the tray icon) for the menu.

| To... | Do this |
|---|---|
| Open or close the chat | Left-click Alter Ego |
| Move Alter Ego | Drag it with the left mouse button |
| Write a longer message | The chat box grows as you type. **Enter** sends, **Shift+Enter** starts a new line |
| Talk instead of typing | Hold **F9** (in any window), speak, let go. Or hold the **talk** button in the chat |
| Talk without touching anything | **Voice** → **Hands-free**, then say "Hey Alter Ego" and your request |
| Interrupt Alter Ego | Click **stop** in the chat (the **send** button while it thinks, types or speaks), or hold the talk key or the **talk** button |
| Change the talk key or microphone | **Voice** |
| Change volume or speakers, or mute | **Spoken replies** |
| Pick another AI or model | **AI** → **Provider** / **Model** |
| Check the AI works | **AI** → **Test connection** |
| Clear the chat | **clear** in the chat header (it stays in memory on disk) |
| Turn memory off, or forget everything | **Memory** |
| Change the size | **Size** |
| Hide to the tray | Left-click the tray icon. Click it again to bring Alter Ego back |
| Quit | **Quit** in either menu |

---

## Choosing an AI

Pick one under **AI** → **Provider**. Changes apply at once.

**Ollama (local, free, the default).** The AI runs on your computer and nothing leaves it. The first-run setup installs Ollama and a model for you. Alter Ego starts Ollama when it needs it and switches it off when you quit, so the model doesn't keep using memory.

**Claude, through Claude Code (no API key).** If you have a Claude subscription and [Claude Code](https://claude.com/claude-code), install it, run `claude` once and sign in with `/login`. Then choose **Claude (via Claude Code login)**. Expect a few seconds before the first word. Claude Code's coding tools stay disabled: Claude can only search the web and use Alter Ego's own file tools, which ask you first, if you allow those.

> Whether a Claude subscription may be used by a third-party app like this one is governed by Anthropic's usage policies, which can change. Check them before relying on it.

**ChatGPT and other OpenAI-compatible APIs.** This works with OpenAI, Groq, OpenRouter, Mistral, LM Studio and others. Open **AI** → **Edit settings file...**, fill in the `openai` section (`base_url`, `api_key`, `model`), restart, and choose **OpenAI-compatible API**. You pay for usage with your own key.

**Offline.** With no AI at all, Alter Ego answers with a few friendly lines of its own.

Every setting is explained in [docs/SETTINGS.md](docs/SETTINGS.md).

---

## Privacy

Alter Ego is local-first. Here is everything that can leave your computer, and when:

- **The AI.**
  - With *Ollama*, your messages stay on your computer.
  - With *Claude* or an *OpenAI-compatible API*, your messages, the recent conversation and the personality prompt go to that service under your account, subject to its terms.
  - Claude Code also keeps its own transcript under `~/.claude/`.
- **Internet look-ups** (on by default, **AI** → **Allow internet**).
  - With Ollama, only the search words go to Wikipedia and DuckDuckGo (or your own SearXNG server), plus the addresses of pages it reads. News comes from Wikipedia's *Current events* pages. For weather, the place name goes to wttr.in (with no place, wttr.in guesses it from your internet address). Your conversation is not sent.
  - With Claude, Claude Code's own web tools are used.
- **Your microphone.** It is open only while you hold the talk key, unless you turn on hands-free. With hands-free, the wake phrase is checked on your computer, and audio that isn't for Alter Ego is thrown away. No audio is ever saved to disk. Speech goes to an API only if you chose the API speech engine.
- **Downloads.** Ollama, the AI model and the voice files are downloaded only when you choose them in the setup or the menu. Ollama comes from ollama.com, the model through Ollama, and the voice files from GitHub (Kokoro) and Hugging Face (two voice base models). Nothing of yours is sent with them. The Whisper speech model is downloaded from Hugging Face the first time you talk.
- **Update check** (on by default, **AI** → **Check for updates at start-up**). At start-up Alter Ego asks GitHub for the latest version number. Nothing of yours is sent, and the new version is downloaded from GitHub only after you say yes.
- **Files on your computer.** Alter Ego keeps its data in one folder: `%APPDATA%\AlterEgo` on Windows, `~/.config/alter_ego` on Linux, or `data/` when run from source.
  - `config.json`: your settings and, if you use one, your API key. Keep it private.
  - `memory.db`: your conversations. Switch saving off, or delete everything, from the **Memory** menu.
  - `voices/`: the downloaded voice files.
  - `alter_ego.log`: diagnostics from the last run.
  - `claude_code/`: what Claude Code needs to resume its session.
- **Your documents.** With **Let me work with files** on, the AI changes a file only after you said yes to that change (unless you switched on **Edit files without asking**). It reads `Documents\Alter Ego` freely, and anywhere else only after you said yes. With Claude or an online AI, what it reads is sent to that service.

**Uninstalling.** Updates keep this folder, so your memories survive them. When you uninstall, Alter Ego asks what else should go, with nothing ticked:
- your memories and settings
- the voice files and the GPU pack
- the speech-recognition models
- the files it saved for you in `Documents\Alter Ego`
- Ollama's AI models (they are shared by every program that uses Ollama)
- the Ollama program itself (Windows; on Linux the uninstaller says how)
- **Everything above**

Anything you don't tick stays, so you can reinstall later and carry on. On Linux, run `./uninstall.sh` in a terminal to be asked.

---

## Troubleshooting

**"Ollama isn't installed" or "I don't have an AI model".** Open **AI** → **Set up Ollama and my voice...**. If installing fails on Linux, run `curl -fsSL https://ollama.com/install.sh | sh` in a terminal.

**Alter Ego doesn't answer "Hey Alter Ego".** Open the log file (see [Privacy](#privacy) for the folder). Every check is written there as `Hands-free heard: '...'`.
- **Nothing is logged when you speak:** the microphone didn't pick you up. Try **Voice** → **Wake sensitivity** → **High**, and check **Voice** → **Microphone**.
- **Logged, but misheard:** set your `language` in the settings, or set `"wake_model": "base"`.
- **Heard correctly, but nothing happens:** say your request straight after the phrase, or raise `awake_seconds`.

**No voice.** Check **Spoken replies** → **Speak replies out loud** and the volume. If the voice files are missing, choose **Spoken replies** → **Download my voice**. **Test my voice** plays a line.

**Wrong or "I don't know" answers to news and questions.** Small models are weak at using what they look up. **Llama 3.2 1B** handles news and weather, but often misses an answer in a longer result ("who won..."). **Llama 3.2** (2 GB) or **Qwen 2.5 7B** do much better: **AI** → **Model**.

**Slow replies.** Pick a smaller model (**Llama 3.2 1B**), or check **AI** → **Model**. With Claude, set `"effort": "low"` in the settings. On a computer with an NVIDIA graphics card, **Spoken replies** → **Use my NVIDIA GPU for my voice** makes the voice about 3 times faster (a one-time download of about 2.8 GB, Windows only).

**Memory use.** Alter Ego itself uses about 200–300 MB. Its voice runs in a separate helper process that needs another 2–3 GB while it is loaded. On computers with 16 GB of memory or more the voice stays loaded, so replies are quick. With less, it is closed after 10 quiet minutes and loads again (a few seconds) when it next speaks. Task Manager shows the two together under Alter Ego.

**Something else.** The log file usually says what went wrong. [Open an issue](https://github.com/1andresito/AlterEgo-Companion/issues) and attach it.

---

## Roadmap

- [x] v0.1 to v0.3: the companion, expressions, chat, AI providers
- [x] v0.4.0: memory
- [x] v0.5.0: voice input (push to talk, "Hey Alter Ego")
- [x] v0.6.0: spoken replies in the character's own voice
- [x] v0.7.0: easy install: downloads on the Releases page and a first-run setup
- [x] v0.7.1: updates from inside the app, and a CRT switch-on and switch-off
- [x] v0.8.0: files anywhere on your computer, with a question before every change
- [x] v0.9.0: lighter on memory, one copy at a time, a loading window, and an optional NVIDIA GPU pack for the voice
- [ ] v0.10.0: reminders and notifications: Alter Ego speaks up on its own
- [ ] Later: long-term recall of older conversations

---

## More

- [Run from source, build the downloads, run the tests](docs/FROM_SOURCE.md)
- [Every setting explained](docs/SETTINGS.md)
- [Change the personality, artwork or icon](docs/CUSTOMIZING.md)
- [Contribute](CONTRIBUTING.md). Working with an AI coding assistant? Start in [`AI/`](AI/README.md).
- [Changelog](CHANGELOG.md)

Licensed under the terms in [LICENSE](LICENSE).
