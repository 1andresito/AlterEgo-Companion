# Changelog

What changed in each version, newest first. The release page on GitHub shows the section for that version.

## v0.7.1: Updates and a TV switch-on

- **Updates.** When a new version is out, Alter Ego asks at start-up and, if you say yes, downloads it, installs it and starts again by itself. Your settings and memories stay. Turn the check off, or check by hand, from the **AI** menu.
- **Like an old TV.** Alter Ego switches on like a CRT when it starts (a dot, a line, then the picture) and switches off the same way when you quit.
- **Fix:** downloads (the voice, Ollama, the voice model's helpers) no longer fail with `CERTIFICATE_VERIFY_FAILED` in the packaged app or on Windows: every download and API call now checks certificates with the computer's own certificate store.

## v0.7.0: Easy to install

- **Download and run.** Alter Ego now comes ready-made on the [Releases page](https://github.com/1andresito/AlterEgo-Companion/releases): a Windows installer, a portable Windows zip and a Linux download. You don't need Python, Git or a terminal.
- **First-run setup.** On first start, Alter Ego asks for what it needs: it can install Ollama (the free, local AI) for you, lets you pick an AI model to download (or none), and offers to download its voice. Nothing is downloaded unless you tick it. You can open the setup again from **AI** → **Set up Ollama and my voice...**.
- The character voice is part of the download: no extra install steps.
- The AI model is no longer downloaded silently on the first reply. The setup asks first.
- The packaged app writes its diagnostics to `alter_ego.log` in its data folder, because it has no terminal window.
- The README is rewritten for newcomers. Detailed reference moved to [`docs/`](docs/), and the [`AI/`](AI/) folder is now a guide for contributors.

## v0.6.0: Alter Ego talks back

- Spoken replies with a local, offline voice (Kokoro), sentence by sentence while the reply is still arriving, with the chat text typing along to the voice.
- One fixed voice, the character's own: Kokoro speech converted with an RVC voice model trained for this project. It runs on an NVIDIA graphics card when there is one, and on the CPU otherwise.
- The delivery follows the mood: shy replies are softer and slower, passionate ones quicker.
- Hands-free: after "Hey Alter Ego" it answers "Yes?" out loud. Optionally you can interrupt a hands-free reply just by talking.
- Internet and files: Alter Ego can search the web, read pages, and make and read files in one folder (it asks before the first change).
- Ollama looks after itself: it is started when needed and switched off when Alter Ego quits.
- Faster replies: about 0.1 s to the first word with a local model that is already loaded.

## v0.5.0: Voice input

- Push to talk: hold F9 anywhere (or the talk button) and speak.
- Hands-free: say "Hey Alter Ego".
- Speech is recognised on your computer with Whisper, or with an API if you choose one.

## v0.4.0: Memory

- Conversations are saved locally and restored after a restart, with day dividers and a "welcome back" after a long pause.
- **Memory** menu: switch saving off, or forget everything.

## v0.3.1: More AI choices

- Claude through your existing Claude Code login (no API key).
- Any OpenAI-compatible API (ChatGPT, Groq, LM Studio, ...).

## v0.3.0: AI chat

- Provider framework with Ollama, streaming replies, and the face following the mood the AI picks.

## v0.2.0: Chat panel

- Chat panel, character reactions, personality file.

## v0.1.x: The companion

- CRT desktop companion, draggable window, system tray, expressions with crossfades, CRT sweep, size presets.
