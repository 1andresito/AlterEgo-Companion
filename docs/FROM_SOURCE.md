# Running from source

You only need this if you want to change the code, or if no ready-made download exists for your system. Everyone else can use the [Releases page](https://github.com/1andresito/AlterEgo-Companion/releases).

## What you need

- Windows 10 or 11, or Linux (tested on Fedora with Wayland). macOS is untested.
- **Python 3.12.** Any version from 3.10 to 3.13 works. 3.14 runs the app, but not the character voice.
- [Git LFS](https://git-lfs.com), installed **before** you clone. The voice model in `assets/voice/` is stored with it. Without it, Git leaves a small placeholder file and Alter Ego speaks with a stand-in voice. Run `git lfs pull` to fix that afterwards.

## Install and run

Windows (PowerShell, in the project folder):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

If PowerShell blocks the activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` once, then activate again.

Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

The first start shows the same setup window as the downloads. It can install Ollama, download a model and download the voice files.

## The character voice

`requirements.txt` gives you everything except the character voice. Without it, Alter Ego speaks with the plain Kokoro voice. To add it, inside the activated environment:

```bash
pip install -r requirements-character-voice.txt --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
pip install --no-deps infer-rvc-python==1.3.1
```

The second line is separate on purpose. The converter pins an old `pyworld` that has no ready-made Windows build for Python 3.12. So the requirements file installs a newer one, and the converter goes in without its pins.

**NVIDIA graphics card?** Swap in the CUDA build of PyTorch afterwards. The voice then runs about three times faster: on an RTX 5070, a sentence takes a quarter of its own length to make, instead of four fifths of it on the CPU.

```bash
pip install torch==2.11.0 torchaudio==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
```

Nothing else changes. At start, Alter Ego checks whether PyTorch can use a card, and otherwise uses the CPU. The console says which one. Set `ALTER_EGO_DEVICE=cpu` to keep the voice off a weak or busy card. If the card can't load the voice, Alter Ego falls back to the CPU by itself.

## Linux notes

- Audio goes through PipeWire or PulseAudio via Qt. There is nothing extra to install.
- The global push-to-talk key is Windows-only for now. On Linux, hold the **talk** button in the chat panel, or use hands-free mode.
- If your desktop has no system tray, Alter Ego still runs. Right-click the character for the menu.

## Tests

```bash
python -m unittest discover -s tests -v
```

On a machine without a display, set `QT_QPA_PLATFORM=offscreen` first.

The tests cover everything that isn't drawn on screen. They use fakes: a fake Ollama server, a fake OpenAI server, a fake `claude` command, a fake microphone, a fake voice and a fake installer. So they need no network, AI, microphone, speakers or model files, and they write only to temporary folders.

## Building the downloads yourself

The release downloads are built by GitHub Actions (`.github/workflows/release.yml`) when a version tag is pushed. To build the same program folder locally:

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean packaging/alter_ego.spec
```

The result is `dist/AlterEgo/`. Run `dist/AlterEgo/AlterEgo.exe` (Windows) or `dist/AlterEgo/AlterEgo` (Linux). `ALTER_EGO_LITE=1` leaves out the character voice for a much quicker test build.

To get the Windows installer as well, install [Inno Setup 6](https://jrsoftware.org/isinfo.php) and run:

```powershell
iscc /DAppVersion=0.7.0 packaging\windows\alter_ego.iss
```

More on releases: [`AI/RELEASING.md`](../AI/RELEASING.md).
