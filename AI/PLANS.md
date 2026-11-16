# Plans

Keep this file current. Dates are absolute. "Now" is what is actually being worked on; "Next" is agreed and ordered; "Ideas" are not commitments and may be dropped.

## Done

- 2026-11-16, Ollama looks after itself: choosing Ollama (or starting with it chosen) runs `ollama serve` if nothing answers locally and stops it on quit if Alter Ego started it (`providers/ollama_server.py`); the first reply with no model installed pulls `default_model` with progress in the chat. `Provider.warm_up()`/`prepare()` hooks run on the reply worker; `Assistant.warm_up()`/`test_connection()` use a worker too, so "Test connection" no longer blocks the GUI.

- v0.1.0 to v0.5.0: CRT companion, expressions, chat, providers (Ollama, Claude via Claude Code, OpenAI-compatible), memory, push to talk, hands-free. See the README roadmap.
- v0.6.0 (built 2026-11-16, not yet committed): spoken replies with local Kokoro, the "Alter Ego" blended voice (soft, youthful, inspired by Chihiro Fujisaki), pitch lift, expression-driven tempo, CRT tone, sentence-by-sentence streaming with the chat typewriter paced to the audio, hands-free muted while speaking, OpenAI-compatible speech API as an alternative, 26 new tests (146 total). Linux (Fedora, Wayland) verified and documented.

## Now

- **An accurate Chihiro voice, free and local** (decided 2026-11-16). The user wants Alter Ego to sound like Chihiro Fujisaki, not merely in that spirit, with no paid service and everything on the computer. Paid or online cloning (Fish Audio and similar) was tried as a design and rejected; the engine was removed. The approach being evaluated is a local zero-shot voice-cloning engine that takes a short reference clip the user supplies (the project ships no clip and no model of the actor): candidates are Chatterbox Nano/Turbo (MIT, PyTorch CPU) and NeuTTS Air/Nano (GGUF via llama.cpp, needs Python < 3.14). Both are being benchmarked on the user's 14-thread CPU for real-time factor; the winner becomes a `Synthesizer` next to Kokoro, with Kokoro staying the light default and the clone opt-in. Engines that already produce a specific voice set `shape_pitch = False` so the Kokoro pitch lift does not touch them.
- RVC (Kokoro speech converted to a community-trained character model) was considered: strongest identity match, but the Python package does not install on Python 3.12+ and needs a separate interpreter; keep it as a fallback idea.
- Commit v0.6.0 once the voice is accepted (`v0.6.0 spoken replies`).

## Next

- **v0.7.0: scheduled updates and notifications** (from the README roadmap). Alter Ego speaks up on its own: reminders the user sets in chat, a greeting at a chosen time, and short check-ins when the user has been away. Needs a small scheduler in `core/` (persisted in `data/`), a way for the AI to propose a reminder from a conversation (a tag or tool-like convention similar to the expression tag), and the tray/character popping up with the message, spoken if the voice is on. Respect quiet hours; everything local.
- **Linux global push-to-talk key.** `speech/hotkey.py` is Windows-only. Options: `evdev` (needs the `input` group), or a tiny command/socket so the compositor keybind (Hyprland `bind`) can trigger start/stop. The socket route needs no privileges and also helps scripting.
- **Long-term recall of older conversations** (README "Later"). Older conversations are already kept in `memory.db`; add a summary per conversation and let the AI see summaries of past ones. Keep it local and keep the context size bounded.

## Ideas

- A mouth-movement feel while speaking, by alternating the reply expression with its closed-mouth counterpart if such artwork is added (there is none today; the images are complete frames).
- An optional reference-clip voice-cloning engine (for example Chatterbox or F5-TTS) as another `Synthesizer`, off by default, heavy, and only with a voice the user has the right to use.
- Packaging for Linux (AppImage or Flatpak) alongside the PyInstaller Windows build; macOS is untested.
- Speak the greeting when the chat opens only if the character is visible, and a "Mute" tray action for quick silence.
