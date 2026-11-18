# Contributing to Alter Ego with an AI assistant

This folder is the guide for anyone working on Alter Ego with an AI coding assistant (Claude Code, Copilot, Cursor, Codex, ...), and for people who want to know how the project is built and how it should keep being built. Tool-specific files such as `.claude/CLAUDE.md` only point here, so there is one set of rules to keep up to date.

Point your assistant at this file first. It is written so a model can follow it as instructions.

## Read in this order

1. **This file**: what the project is, the rules that are not negotiable, and how a change is made.
2. [`ARCHITECTURE.md`](ARCHITECTURE.md): how the code is laid out, how a message travels through it, and where a new feature goes.
3. [`CODE_STYLE.md`](CODE_STYLE.md): how code, comments, tests and user-facing text are written. New code should look like the old code.
4. [`DECISIONS.md`](DECISIONS.md): choices that look odd until you know why. Read it before "fixing" one of them.
5. [`PLANS.md`](PLANS.md): what is being worked on now and what comes next.
6. [`RELEASING.md`](RELEASING.md): how a version is cut and how the downloads are built.

## What Alter Ego is

A desktop companion built with Python and PySide6: the character Alter Ego from Danganronpa, modelled on Chihiro Fujisaki, living in a green CRT monitor on the desktop. It chats through a pluggable AI provider (local Ollama by default), remembers conversations, listens (local Whisper), talks back in one fixed character voice (local Kokoro plus an RVC model), and can search the web and work with files in one folder. It ships as a Windows installer, a portable zip and a Linux tarball, and on first start a setup window offers to install Ollama, a model and the voice. It is an unofficial, non-commercial fan project.

The audience is ordinary desktop users, not developers. Assume they have never opened a terminal.

## Rules that are not negotiable

- **Local first, private by default.** Nothing leaves the computer unless the user chose a service that needs it. No audio is ever written to disk. **No large download happens without the user asking for it**, in the first-run setup or a menu, with its size shown first. The one network feature on by default is the AI's internet look-up (search words to Wikipedia and DuckDuckGo, a place name to wttr.in for weather), and it is switched off with **AI** → **Allow internet**. The AI's file tools touch only one folder and ask before the first change. Every network path is listed in the README's Privacy section. A new one must be added there in the same change.
- **The app always runs.** Missing artwork, missing optional packages, no AI, no microphone, no speakers: Alter Ego starts anyway and explains, in character, what is missing and how to fix it. Heavy packages are imported lazily, inside the function that needs them.
- **The GUI never freezes.** Anything that can take more than a few milliseconds (network, models, downloads, installers, audio conversion) runs on a worker `QThread` and reports back through signals.
- **Modules talk through Qt signals, not direct calls.** The chat panel, the face, memory, voice input and voice output all observe the same `Conversation` and `Assistant`; none of them knows the others exist. `core/` and `providers/` contain no widgets.
- **Windows and Linux both work, from source and packaged.** Platform-specific code is isolated in its own module and degrades gracefully elsewhere. Anything that finds files must work both from a checkout and from a PyInstaller build (`settings/config.py` `assets_dir()`/`data_dir()`).
- **Stay in character.** Every message the user sees in the chat or the setup is said by Alter Ego: gentle, a little shy, helpful, never corporate. Errors say what happened and what to do, in that voice.
- **Easy for a newcomer.** A feature that needs a terminal, a config edit or a manual download to work is not finished. Give it a menu item, or a step in the setup.
- **No new dependencies without a reason.** PySide6 and the standard library are the baseline. `providers/` uses the standard library only. Optional engines (`faster-whisper`, `kokoro-onnx`, the RVC converter) are imported lazily and have a fallback. A new package must also be bundled: check `packaging/alter_ego.spec`.

## How to make a change

1. **Understand first.** Read the modules you will touch and the nearest similar feature. `speech/` and `voice/` mirror each other on purpose, and so do the menu modules. Copy their shape.
2. **Find the place.** Use the "Adding things" table in [`ARCHITECTURE.md`](ARCHITECTURE.md). If the change does not fit any row, the design needs a moment of thought before code. Say so instead of improvising.
3. **Keep it small.** Change what the task needs, no unrelated rewrites. Leave rules about how pieces work together in `app.py`, and keep controllers independent.
4. **Test it.** Add tests for anything non-visual, using fakes (never a real network, microphone, speaker, model or installer), then run the full suite:

   ```bash
   QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
   ```

   All tests must pass before you call the task done. For a visible change, also run the app (`python main.py`) and look at it.
5. **Document it, in the same change.**
   - User-visible behaviour: the README (features, controls table, privacy, troubleshooting) and, for a new setting, `docs/SETTINGS.md`. The defaults there must match `DEFAULTS` exactly.
   - New modules or a new flow: the tree and walk-through in `ARCHITECTURE.md`.
   - A choice someone might later undo by mistake: a short entry in `DECISIONS.md`.
   - For the next release: a line under the coming version in `CHANGELOG.md`.
6. **Update `PLANS.md`**: take finished work out of "Now", and note anything left open.

## Working on someone else's machine

- Heavy experiments (PyTorch models, benchmarks, builds with the full voice) run at low priority (`nice -n 19` on Linux, low priority on Windows), with at most 6 threads, one at a time, in the background. A full-speed run once made the owner's desktop unusable and pushed the machine into swap.
- Don't commit, tag or bump the version unless asked. When asked to commit, the message style is `vX.Y.Z short description`.
- Use the project's virtual environment (`.venv`, Python 3.12). Python 3.14 breaks the character voice.
