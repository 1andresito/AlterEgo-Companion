# Decisions

Choices that look strange, or easy to "improve", until you know why they were made. Read the entry before changing one of these. If you do change one, update or remove its entry.

## Product

**One fixed voice.** Alter Ego has exactly one voice, and it is part of the program, not a setting: Kokoro speech converted with the RVC model in `assets/voice/`. There is no menu item or config key that picks a voice, engine, pitch or speed, and none should be added. The tuning lives in constants in `voice/rvc_local.py` (`DEFAULT_PITCH` +7 semitones, `DEFAULT_INDEX_RATE` 0.75, `rmvpe+`). The +7 was measured: RVC keeps the Kokoro source pitch (about 193 Hz), and the character's speaking pitch is about 283 Hz. The model was trained on the owner's own recording, not on a voice actor's.

**The voice model ships with the project, in Git LFS.** `assets/voice/alter_ego.pth` and `.index` are tracked with LFS (`.gitattributes`). A clone without LFS gets a small pointer file instead. `rvc_local.is_lfs_pointer()` treats that as missing, so the stand-in Kokoro blend speaks instead of the app crashing. The release workflow checks out with `lfs: true`.

**Nothing big downloads without asking.** The AI model used to be pulled silently on the first reply. Since v0.7.0 the first-run setup asks, showing the size first, and `ollama.auto_pull` defaults to `false`. Keep new downloads behind the setup or a menu item.

**Updates ask first, and never touch the running program folder.** The start-up check (`updates.check`, on by default) only reads the latest version number from GitHub. The download starts after the user clicks **Update now**. The swap happens after Alter Ego quits: the Windows installer runs silently with `/RELAUNCH=1` (a `[Code]` check in `alter_ego.iss` starts the new version), and the portable zip and Linux tar.gz are copied over the old folder by a small script that waits for the old process to end (`core/updates.py`). A copy run from source never updates itself, so a developer's checkout is left to Git. Downloads that aren't the installer are unpacked with path checks (`filter="data"` for tar), because they are written over the program.

**Ollama runs only while Alter Ego uses it.** Choosing Ollama starts `ollama serve` if nothing answers locally. Quitting, or switching providers, switches Ollama off: on Windows that includes the tray app and model runners, even if the user started them (`stop_all`, the owner's choice). The server Alter Ego starts sits in a Windows Job Object, so a crash cannot leave it running. It is started with `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_NUM_PARALLEL=1` to keep memory low. On Linux only a server Alter Ego started is stopped, because a system service needs root.

**The AI asks before every file change.** File tools can reach any path, so each change (new file, replaced file, new folder) is its own question with the full path; a yes is never stretched to cover later changes. Reading the Alter Ego folder is free, but reading elsewhere asks once per folder, because with Claude or an online AI what is read leaves the computer. **Edit files without asking** (`tools.auto_edit`) is the owner's opt-in: off by default, a warning before it turns on, and even then system folders and Alter Ego's own program and data folders still ask, and reads still ask. The question is a parentless, stay-on-top message box (`tool_approval.on_top_box`): the character and chat are frameless stay-on-top `Tool` windows, and a dialog parented to them could open underneath them, where it can't be clicked. Set the modality before the stay-on-top flag, because `setWindowModality` clears the window flags.

**Story knowledge is picked per message, not sent whole.** `knowledge.json` has a short core that always goes with the prompt and topics chosen by keyword (`core/knowledge.py`, at most three). llama3.2 3B answered worse, and blurted spoilers, with everything in the prompt. The core leaves out secrets and deaths so Alter Ego doesn't bring them up unasked, and says plainly that Alter Ego is not Chihiro (the model kept saying "he killed me"). The facts were written from Wikipedia's game and character pages, in our own words.

**Tools are offered only when the message is about them.** With the file and web tools always on offer, the small model looked up `Mondo_Owada.txt` and fetched Wikipedia to answer "hello", then said "I don't know" when that failed. `mentions_files` and `wants_web` decide per message; a missed search costs less than every answer waiting on a tool.

**Ollama gets `num_ctx` 8192, in loading and in chatting alike.** The default 4096 cut off the start of a prompt that now carries the story knowledge. The model load at start (`load_model`) must ask for the same size as the replies, or the first reply reloads the model.

**The voice loads at start-up, before anything else, and warms up.** It is the slowest part of starting (about 15 s on a GPU, 25 s on a CPU, mostly importing PyTorch and its libraries), and the chat waits for each sentence's audio. `preload()` runs first, shows "Waking up... loading my voice", and renders one line after loading, because the first conversion is seconds slower than the rest. A long first sentence is spoken in two parts, cut at a comma (`voice/text.py`), so the first sound comes sooner (on the CPU 2.7 s instead of 4.3 s).

**Only one Alter Ego at a time.** Two copies fought over the microphone, the push-to-talk key, Ollama and `memory.db`. A `QLockFile` in the data folder decides (safe when two start at once, and after a crash), and a local socket tells the running copy to show itself. The log is only opened after the lock is taken, so a second start cannot wipe the running copy's log. Helper processes (`--tool-server`, `--voice-server`, `--check-voice`) skip it.

**The voice runs in its own process.** Measured: the app went from about 2.3 GB at start to 3.7 GB after speaking (6.5 GB committed), and almost all of it was the voice: Kokoro about 400 MB, PyTorch about 450 MB, the RVC models about 440 MB, and about 1.4 GB of work buffers kept after the first converted sentence. It was not a leak, and turning oneDNN off didn't help. Running the converter on the GPU didn't lower system memory either, because CUDA's libraries live in RAM. A process rarely gives freed memory back, so the voice lives in a helper process (`voice/remote.py`, `voice/server.py`) that can really be closed. The app's own process went from about 2.3 GB to about 215 MB.

**The voice stays loaded on 16 GB computers, and is closed when quiet on smaller ones.** With 16 GB or more, the 2-3 GB matter less than a reload of 10-20 s, so it stays (`core/machine.keep_voice_loaded`). With less, it is closed after 10 quiet minutes. Everywhere, it is restarted when it grows past 3.5 GB. This is the owner's choice: under 1 GB in total is only possible while the voice is unloaded.

**The GPU pack is an extra, Windows only, and only on request.** The CUDA build of PyTorch is about 3 GB, so releases still bundle the CPU build. On a computer with an NVIDIA driver, the setup and the Spoken replies menu offer to download CUDA torch, torchaudio and torchvision of the bundled versions from download.pytorch.org (checked against the sha256 on the index page) into `data/gpu/`. Only the voice helper uses it (`prefer_pack` puts a finder first on `sys.meta_path`). A probe run must see a CUDA card, or the pack is removed again. On Linux the CUDA wheels need about ten separate NVIDIA packages, so Linux stays on the CPU for now. Measured on an RTX 5070, the voice is about 3 times faster on the GPU. A card with less than 3 GB of video memory keeps the voice on the CPU.

**Speech recognition stays on the CPU, even with the GPU pack.** Whisper runs in the app's own process; using CUDA there would add hundreds of MB to the process that is meant to stay small, and Whisper base on the CPU (int8) already takes about a second.

**A loading window at start-up.** The character appears once the AI model and the voice are ready (or after 90 s at most), so the first message doesn't wait unseen. It shows the steps and adds no memory.

**The uninstaller asks what else should go, with nothing ticked.** Updates install over the old version and never run the uninstaller, so the question only appears on a real uninstall. Memories, downloads (the voice files, the GPU pack), Alter Ego's own speech models (only `models--Systran--faster-whisper-*`, never the rest of the shared Hugging Face cache), the files in `Documents\Alter Ego`, Ollama's models and Ollama itself are separate choices, plus "Everything above". Deleting memories, saved files or Ollama's models asks once more, because it can't be undone. A silent uninstall (`/VERYSILENT`) removes only the program. Ollama is removed with its own uninstaller; on Linux it needs root, so the script only says how.

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
