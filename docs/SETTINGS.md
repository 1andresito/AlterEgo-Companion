# The settings file

Most things can be changed from Alter Ego's right-click menu. Everything else lives in one JSON file. To open it in your editor, choose **AI** → **Edit settings file...**.

Where it is:

| How you run Alter Ego | Settings file |
|---|---|
| Installed or portable, Windows | `%APPDATA%\AlterEgo\config.json` |
| Installed, Linux | `~/.config/alter_ego/config.json` |
| From source | `data/config.json` in the project folder |

The environment variable `ALTER_EGO_DATA_DIR` moves the whole data folder (settings, memory, voice files, log) somewhere else.

The file is created the first time a setting changes. Changes made from the menu apply at once. Edits to the file apply the next time Alter Ego starts.

## All keys and their defaults

```json
{
  "provider": "ollama",
  "setup":       { "done": false },
  "updates":     { "check": true, "skipped": "" },
  "ollama":      { "base_url": "http://localhost:11434", "model": "", "command": "ollama",
                   "auto_start": true, "auto_pull": false, "default_model": "llama3.2" },
  "claude_code": { "command": "claude", "model": "", "effort": "" },
  "openai":      { "base_url": "https://api.openai.com/v1", "api_key": "", "model": "" },
  "tools":       { "internet": true, "files": true, "folder": "", "search_url": "" },
  "memory":      { "enabled": true, "context_messages": 30 },
  "speech": {
    "enabled": true,
    "push_to_talk_key": "F9",
    "microphone": "",
    "transcriber": "whisper",
    "whisper_model": "base",
    "openai_model": "whisper-1",
    "language": "",
    "review_before_sending": false,
    "hands_free": false,
    "wake_phrase": "hey alter ego",
    "wake_model": "tiny",
    "wake_sensitivity": "normal",
    "awake_seconds": 3,
    "interrupt_by_voice": false
  },
  "voice": {
    "enabled": true,
    "volume": 0.8,
    "speaker": "",
    "models_dir": ""
  }
}
```

## What they mean

### General

- `provider`: which AI answers. One of `offline`, `ollama`, `claude_code` or `openai`.
- `setup.done`: `true` once the first-run setup was finished or skipped. Set it back to `false` to see the setup at the next start. Or open it any time from **AI** → **Set up Ollama and my voice...**.
- `updates.check`: look for a new release at start-up and ask before installing it (**AI** → **Check for updates at start-up**). Nothing is downloaded without a yes. A copy run from source never updates itself: use `git pull`.
- `updates.skipped`: the version you chose to skip. It isn't offered again at start-up, only from **AI** → **Check for updates now**. Set it to `""` to be asked again.

### Ollama

- `base_url`: where Ollama listens. A server on another computer is used as it is. Alter Ego never starts or stops a remote server.
- `model`: the model to think with. Empty means the first installed one. The setup fills this in with the model you chose.
- `command`: the Ollama program, if it is not on the PATH.
- `auto_start`: start `ollama serve` when nothing answers at a local `base_url`, and switch Ollama off again on quit.
- `auto_pull`: download `default_model` before the first reply if no model is installed. Off by default, because the setup asks instead.
- `default_model`: the model `auto_pull` downloads.

### Claude via Claude Code

- `command`: the Claude Code program, if it is not on the PATH.
- `model`: `""` or `default` (whatever Claude Code uses), `opus`, `sonnet` or `haiku`.
- `effort`: `""`, `low`, `medium` or `high`. Lower is faster.

### OpenAI-compatible API

- `base_url`: for example `https://api.openai.com/v1`, `https://api.groq.com/openai/v1`, or `http://localhost:1234/v1` for LM Studio.
- `api_key`: your key. It can also come from the `OPENAI_API_KEY` environment variable. Keep this file private.
- `model`: the model name. Empty means the first one the service lists.

### What the AI may do (`tools`)

- `internet`: let the AI look things up online (**AI** → **Allow internet**).
- `files`: let the AI read and write files in one folder, asking before the first change (**AI** → **Let me work with files**).
- `folder`: that one folder. Empty means `Documents/Alter Ego`.
- `search_url`: empty means Wikipedia and DuckDuckGo instant answers. Set it to a [SearXNG](https://docs.searxng.org/) server with JSON output on to search the whole web.

### Memory

- `enabled`: save conversations and restore them on start.
- `context_messages`: how many recent messages the AI sees with each reply. `0` means all of them. Raise it if your model has a large context window.

### Voice input (`speech`)

- `enabled`: push to talk on or off.
- `push_to_talk_key`: the key to hold. See **Voice** → **Key** for the names.
- `microphone`: empty means the system default. Otherwise use a device name from **Voice** → **Microphone**.
- `transcriber`: `whisper` (local, offline) or `openai` (the API from the `openai` section).
- `whisper_model`: `tiny`, `base`, `small`, `medium`, `large-v3`, or an English-only `.en` variant. Bigger is more accurate and slower.
- `openai_model`: the API's speech model (`whisper-1`; on Groq, `whisper-large-v3`).
- `language`: empty means detect it. A code such as `en` or `es` is faster and more reliable.
- `review_before_sending`: put the recognised text in the input box instead of sending it at once.
- `hands_free`: keep the microphone open and wake up on the wake phrase.
- `wake_phrase`: anything short, for example `"computer"`.
- `wake_model`: the small Whisper model that listens for the wake phrase.
- `wake_sensitivity`: `low`, `normal` or `high`. This is how quiet speech may be and still be noticed.
- `awake_seconds`: seconds of silence after the wake phrase before Alter Ego stops listening.
- `interrupt_by_voice`: talking over a reply to a hands-free request stops it. Use headphones.

### Spoken replies (`voice`)

Alter Ego has one voice, fixed in the program. These keys only say whether it speaks, how loud and where.

- `enabled`: speak replies out loud.
- `volume`: from `0.0` to `1.0`.
- `speaker`: empty means the system default output. Otherwise use a device name from **Spoken replies** → **Speakers**.
- `models_dir`: where the downloaded voice files are kept. Empty means the `voices` folder in the data folder.

Old keys such as `kokoro_voice`, `rvc_model` or `pitch` from earlier versions are ignored.
