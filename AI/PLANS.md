# Plans

Keep this file current. Dates are absolute. "Now" is what is actually being worked on; "Next" is agreed and ordered; "Ideas" are not commitments and may be dropped.

## Done

- v0.1.0 to v0.5.0: CRT companion, expressions, chat, providers (Ollama, Claude via Claude Code, OpenAI-compatible), memory, push to talk, hands-free. See the README roadmap.
- v0.6.0 (built 2026-11-16, not yet committed): spoken replies with local Kokoro, the "Alter Ego" blended voice (soft, youthful, inspired by Chihiro Fujisaki), pitch lift, expression-driven tempo, CRT tone, sentence-by-sentence streaming with the chat typewriter paced to the audio, hands-free muted while speaking, OpenAI-compatible speech API as an alternative, 26 new tests (146 total). Linux (Fedora, Wayland) verified and documented.

## Now

- Listen to the v0.6.0 voice and tune the defaults: the blend weights (`PRESETS` in `voice/kokoro_local.py`), pitch (+2 semitones), the CRT effect strength, the expression tempos (`EXPRESSION_SPEED` in `voice/speaker.py`). The goal is a soft, gentle, slightly shy voice in the spirit of Chihiro, not an imitation of a specific actor.
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
