# Working on Alter Ego as an AI assistant

This folder is for AI coding assistants (Claude Code, Copilot, Cursor, Codex, anything else) and for humans who want to know how the project is meant to be worked on. Tool-specific folders such as `.claude/` only point here, so there is one place to keep up to date.

Read in this order:

1. **This file**: what the project is and the rules that matter most.
2. [`CODE_STYLE.md`](CODE_STYLE.md): how code is written here. Match it; do not import another style.
3. [`ARCHITECTURE.md`](ARCHITECTURE.md): how the pieces fit and where a new feature goes.
4. [`PLANS.md`](PLANS.md): what is being worked on now and what comes next. Update it when you finish or start something.
5. The main [`README.md`](../README.md): the user-facing description, kept exact. Every feature is documented there.

## What Alter Ego is

A desktop companion built with Python and PySide6: the character Alter Ego from Danganronpa, inspired by Chihiro Fujisaki, living in a green CRT monitor on the desktop. It chats through a pluggable AI provider, remembers conversations, listens (local Whisper) and talks back (local Kokoro). It is an unofficial, non-commercial fan project.

## Rules that are not negotiable

- **Local first, private by default.** Nothing leaves the computer unless the user explicitly chose an API. No audio is ever written to disk. No large download happens without the user asking for it in the menu, with one deliberate exception the owner chose: with Ollama as provider, the first reply downloads a default model if none is installed, with progress shown in the chat. Every network path is spelled out in the README's Privacy section.
- **The app always runs.** Missing artwork, missing optional packages, no AI configured, no microphone, no speakers: Alter Ego starts anyway and explains, in character, what is missing and how to fix it. Heavy packages are imported lazily, inside the function that needs them.
- **The GUI never freezes.** Anything that can take more than a few milliseconds (network, models, file downloads, audio conversion) runs on a worker `QThread` and reports back through signals.
- **Modules talk through Qt signals, not direct calls.** The chat panel, the character's face, memory, voice input and voice output all observe the same `Conversation` and `Assistant`; none of them knows the others exist. `core/` and `providers/` contain no UI.
- **Windows and Linux both work.** Platform-specific code is isolated in one module (today only `speech/hotkey.py`) and degrades gracefully elsewhere.
- **Stay in character.** Every message the user sees in the chat is said by Alter Ego: gentle, a little shy, helpful, never corporate. Error messages say what happened and what to do, in that voice.
- **No new dependencies without a reason.** PySide6 plus the standard library is the baseline. `faster-whisper` and `kokoro-onnx` are optional. NumPy may be used only behind a lazy import with a fallback.

## Before you finish a task

- Run the tests: `python -m unittest discover -s tests -v` (on a machine without a display: `QT_QPA_PLATFORM=offscreen`). Add tests for anything non-visual you added, using fakes, never a real network, microphone, speaker or model.
- Heavy experiments (PyTorch models, benchmarks) run with `nice -n 19` and at most 6 threads, in the background, one at a time. A full-speed run once made the user's desktop unusable and pushed the machine into swap.
- Update the README for any user-visible change: the features list, the relevant section, the controls table, the settings defaults, the code layout tree, the roadmap and the privacy section. The README is the manual; it must stay exact.
- Update `PLANS.md`: move what you did to "Done", note anything you left open.
- Bump `src/alter_ego/__init__.py` only for a release, and only if asked. Do not commit unless asked; when you do, the message style is `vX.Y.Z short description`.
