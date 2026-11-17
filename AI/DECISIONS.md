# Decisions

Choices that look strange, or easy to "improve", until you know why they were made. Read the entry before changing one of these. If you do change one, update or remove its entry.

## Product

**One fixed voice.** Alter Ego has exactly one voice, and it is part of the program, not a setting: Kokoro speech converted with the RVC model in `assets/voice/`. There is no menu item or config key that picks a voice, engine, pitch or speed, and none should be added. The tuning lives in constants in `voice/rvc_local.py` (`DEFAULT_PITCH` +7 semitones, `DEFAULT_INDEX_RATE` 0.75, `rmvpe+`). The +7 was measured: RVC keeps the Kokoro source pitch (about 193 Hz), and the character's speaking pitch is about 283 Hz. The model was trained on the owner's own recording, not on a voice actor's.

**The voice model ships with the project, in Git LFS.** `assets/voice/alter_ego.pth` and `.index` are tracked with LFS (`.gitattributes`). A clone without LFS gets a small pointer file instead. `rvc_local.is_lfs_pointer()` treats that as missing, so the stand-in Kokoro blend speaks instead of the app crashing. The release workflow checks out with `lfs: true`.

**Nothing big downloads without asking.** The AI model used to be pulled silently on the first reply. Since v0.7.0 the first-run setup asks, showing the size first, and `ollama.auto_pull` defaults to `false`. Keep new downloads behind the setup or a menu item.

**Updates ask first, and never touch the running program folder.** The start-up check (`updates.check`, on by default) only reads the latest version number from GitHub. The download starts after the user clicks **Update now**. The swap happens after Alter Ego quits: the Windows installer runs silently with `/RELAUNCH=1` (a `[Code]` check in `alter_ego.iss` starts the new version), and the portable zip and Linux tar.gz are copied over the old folder by a small script that waits for the old process to end (`core/updates.py`). A copy run from source never updates itself, so a developer's checkout is left to Git. Downloads that aren't the installer are unpacked with path checks (`filter="data"` for tar), because they are written over the program.

**Ollama runs only while Alter Ego uses it.** Choosing Ollama starts `ollama serve` if nothing answers locally. Quitting, or switching providers, switches Ollama off: on Windows that includes the tray app and model runners, even if the user started them (`stop_all`, the owner's choice). The server Alter Ego starts sits in a Windows Job Object, so a crash cannot leave it running. It is started with `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_NUM_PARALLEL=1` to keep memory low. On Linux only a server Alter Ego started is stopped, because a system service needs root.

**Hands-free waits for the wake phrase every time.** After a reply, Alter Ego does not keep listening for a follow-up. Every request starts with "Hey Alter Ego". Talking over a reply is a separate opt-in (`interrupt_by_voice`), and only for replies to hands-free requests, because with speakers Alter Ego can hear itself.

**The stammer is written, not spoken.** "I-I think" appears in the chat but is spoken as "I think" (`voice/text.speakable`). Read aloud, it sounded like a stutter of letters.

**The internet tool is keyless.** With Ollama, search uses Wikipedia and DuckDuckGo's instant answers. DuckDuckGo's HTML search was tried and dropped, because it answers programs with a bot challenge. For whole-web results, the user can point `search_url` at a SearXNG server.

## Technical

**127.0.0.1, not localhost.** On Windows, `localhost` resolves to IPv6 first and Ollama listens on IPv4 only, so every request waited about 2 s for the IPv6 attempt to fail. That was most of the delay before each reply. `ollama_server.direct_url()` rewrites local URLs, also for the OpenAI-compatible provider.

**The model is loaded ahead of time and kept for 30 minutes.** `Provider.load_model` runs in the warm-up, and `KEEP_ALIVE` is `30m`. Reloading the model was what made replies slow. With llama3.2 on an RTX 5070, the first word comes about 0.1 s after Enter.

**`infer-rvc-python` is installed with `--no-deps`.** It pins `pyworld==0.3.4`, which has no Windows wheel for Python 3.12 and would need a C++ compiler. `requirements-character-voice.txt` installs `pyworld>=0.3.5` instead, which works the same. The older `rvc-python` package was rejected because it needs fairseq (Python 3.10 only).

**Python 3.12 for the project venv.** The RVC converter supports 3.10 to 3.13. 3.14 runs the app but not the character voice.

**GPU or CPU is decided per machine, never by a setting.** `voice/device.py` uses CUDA when PyTorch sees a card, else the CPU. Releases bundle CPU PyTorch: the CUDA build is about 3 GB, too big for a download most users would accept.

**Engines use half the cores, at low priority.** Kokoro, PyTorch (RVC) and Whisper are limited to half the CPU threads, and worker threads run at low priority, so Alter Ego never makes the desktop sluggish. On 6 threads the voice still runs ahead of real time (RTF about 0.8).

**Engines are rebuilt only when their own settings change.** `EngineCache` in `app.py` exists because every menu click used to reload the voice: 43 s, with briefly two copies in memory.

**Heavy experiments run niced, on at most 6 threads, one at a time.** A 14-thread PyTorch benchmark once made the owner's desktop unusable and pushed it into swap.

**Rejected voice engines.** Chatterbox needs 18 to 40 times real time on a laptop CPU. NeuTTS weights are gated behind a Hugging Face account and token per user. Paid or online voice cloning was rejected, because everything must stay free and local.

## Packaging

**A PyInstaller folder build, not one file.** A one-file exe unpacks hundreds of MB to a temp folder at every start, which makes start-up slow and trips antivirus programs. The folder build starts at once. UPX is off for the same antivirus reason.

**The installer is per user.** `PrivilegesRequired=lowest` installs to `%LOCALAPPDATA%\Programs\Alter Ego` without an administrator prompt, the same way Ollama's own installer does. That is also why Alter Ego can run Ollama's installer silently.

**The packaged app logs to a file.** A windowed build has no console, so `main.py` sends `print` output to `alter_ego.log` in the data folder. The hands-free troubleshooting depends on it.

**The file-tool server uses file descriptors 0 and 1.** In the windowed build `sys.stdin` and `sys.stdout` are `None`, but the pipes Claude Code passes are still there. `tools_mcp.main()` opens fds 0 and 1 directly. The release workflow checks this with a smoke test.

**Releases are built in CI, from a tag.** Windows and Linux builds need their own operating system, and the voice model needs LFS. GitHub Actions does both from one workflow, and refuses a tag that doesn't match `__version__`.
