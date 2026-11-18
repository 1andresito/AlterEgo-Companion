# Plans

What is being worked on now and what comes next. Keep it current: when you start something, put it under "Now". When you finish it, remove it here and describe it in `CHANGELOG.md` under the coming version. Lasting reasons go in `DECISIONS.md`. "Next" is agreed and in order. "Ideas" are not commitments.

## Now

- **v0.7.0 / v0.7.1 release check.** The downloads, first-run setup and docs are built. Still to do by hand:
  - The first GitHub Actions run (a dry run with **Run workflow**). Check the Linux build and the full Windows build with CPU PyTorch: size, start-up, and the character voice running on the CPU.
  - A real install of Ollama through the setup, on a machine without Ollama. Its installer's silent flags (`/VERYSILENT /NORESTART /SUPPRESSMSGBOXES /SP-`) are standard for Inno Setup, but they have not been run against the real `OllamaSetup.exe` yet.
  - The Linux `pkexec` route, on a desktop with a polkit agent.
  - The self-update, once two releases exist: installed Windows (silent installer, then `/RELAUNCH=1` starts the new version), the portable zip, and Linux.
- **v0.7.2 release.** The published v0.7.1 download has no working character voice ("the voice-conversion package is missing"). The spec fix is checked with a local CPU-PyTorch build and `--check-voice`. Still to do: push the `v0.7.2` tag; its release workflow must pass the voice smoke test on Windows and Linux.
- **v0.9.1: the uninstaller asks what to remove.** Built; the Linux script is tested. The Inno Setup code compiles only in the release workflow (Inno Setup isn't installed locally), so check its first build and try a real uninstall on Windows before the tag.
- **v0.9.0 release: memory, one copy, loading window, GPU pack.** Built and tested; in `CHANGELOG.md`. Still to do: a local PyInstaller build to check the voice helper and the GPU pack from the packaged exe (a real 2.8 GB download on the owner's RTX 5070), then the `v0.9.0` tag.
- **v0.8.1 release: a quicker first reply, story knowledge, no tool JSON.** Built and tested; in `CHANGELOG.md`. Still to do: the owner reads `assets/personality/knowledge.json` for accuracy, tries it in the real app, then pushes the `v0.8.1` tag.
- **v0.8.0 release: files anywhere, with a question each time.** Built and tested, in `CHANGELOG.md`: the on-top approval dialog, edits anywhere asked about one by one, reads outside the folder asked once per folder, and the auto-edit switch (off by default). Still to do: try it by hand in the real app with Ollama and with Claude, then push the `v0.8.0` tag.
- **Kokoro int8 model.** `data/voices/kokoro-v1.0.int8.onnx` saves about 220 MB of RAM and is a little faster (RTF 0.20 against 0.23). Switch `build_synthesizer` to `model="small"` once the owner confirms it sounds the same through the RVC conversion.

## Next

- **v0.10.0: reminders and notifications.** Alter Ego speaks up on its own: reminders the user sets in chat, a greeting at a chosen time, a short check-in after the user has been away.
  - A small scheduler in `core/`, saved in the data folder.
  - A way for the AI to propose a reminder from the conversation (a tool, like the file tools).
  - The character pops up with the message, spoken if the voice is on.
  - Quiet hours, and everything stays local.
- **The GPU pack on Linux.** The CUDA wheels there need the separate `nvidia-*` packages (cuBLAS, cuDNN, ...); download and place them like the Windows pack.
- **Linux global push-to-talk key.** `speech/hotkey.py` is Windows-only. Preferred route: a tiny local socket or command, so a compositor keybind (for example Hyprland's `bind`) can start and stop listening. It needs no privileges, unlike `evdev`, and helps scripting too.
- **Long-term recall.** Older conversations are already kept in `memory.db`. Add a summary per conversation and let the AI see summaries of past ones, keeping it local and keeping the context bounded.

## Ideas

- Code-sign the Windows build, so the "unknown publisher" warning goes away.
- An AppImage or Flatpak alongside the Linux tarball. macOS is untested.
- A mouth-movement feel while speaking, if closed-mouth artwork is added.
- Speak the greeting when the chat opens only if the character is visible, and a "Mute" tray action.
