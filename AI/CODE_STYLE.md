# Code style

These are the conventions the existing code follows. New code should be indistinguishable from old code. When in doubt, open the nearest similar module (`speech/` and `voice/` mirror each other on purpose) and copy its shape.

## Files and modules

- Python 3.10+, `from __future__ import annotations` at the top of every module, full type hints on signatures.
- Every module starts with a docstring that says what it is for and, where there is one, draws the state machine in ASCII:

  ```
      IDLE --start()--> LISTENING --stop()--> TRANSCRIBING --(worker done)--> IDLE
  ```

- Module layout: docstring, imports (stdlib, then PySide6, then `.` relative), constants in `UPPER_CASE` with a comment each, then classes. Sections inside a class are separated with `# ----- Section name -----` comments.
- One concern per module, named for the thing it holds: `recorder.py` has `MicrophoneRecorder`, `player.py` has `SpeechPlayer`. Packages mirror each other: `providers/`, `speech/`, `voice/` each have an abstract interface (`base.py`, `transcriber.py`, `synthesizer.py`), concrete engines, and a `build_*()` factory in `__init__.py` that reads the `Config`.
- Lines up to about 120 characters. Imports used only for typing still count as used.
- Layers: `settings/` and `core/` know nothing about Qt widgets (they may use `QObject` and signals). `providers/` is standard library only, no SDKs. UI modules (`chat.py`, `character.py`, `*_menu.py`) never do slow work.

## Naming

- `snake_case` functions and variables, `CamelCase` classes, `_leading_underscore` for anything not meant to be used from outside the module or class.
- Engines expose `id` (short, stored in `config.json`) and `label` (shown in menus) as `ClassVar[str]`.
- Config keys are lower-case words with underscores, grouped in a section per feature (`speech`, `voice`, `memory`). Every key has a default in `settings/config.py` `DEFAULTS` with a trailing comment saying what the values mean.

## Comments and docstrings

- Comments explain *why*, not what. A good comment is the sentence a reviewer would otherwise have to ask for: `# name=name freezes the loop value; a plain lambda would see only the last name.`
- Docstrings are plain English sentences. Public methods that run on a worker thread say so. Methods that raise say which exception.
- No emojis anywhere. No decorative comment banners beyond the `# ----- ... -----` section markers.

## Qt patterns

- Decoupling is done with signals. A controller (`Assistant`, `PushToTalk`, `HandsFree`, `Speaker`) is a `QObject` with a `state_changed = Signal(object)` carrying an `Enum`, plus small purpose-named signals (`status`, `failed`, `transcribed`, ...). Observers connect; the controller never calls the UI.
- Slow work: a `QThread` subclass with signals for results (`piece`, `done`, `failed`), created per job or long-lived with a `queue.Queue` of jobs. The GUI thread owns all state; the worker only emits. Workers are `deleteLater()`ed in a `finished` handler. On quit, `app.aboutToQuit` connects to each controller's `cancel()`/`stop()`/`shutdown()` so threads end before the process does.
- Snapshot data before handing it to a worker (`tuple(history)`), never share live objects.
- Enums that Qt renamed across versions (`QAudio` to `QtAudio`) are imported with a `try/except ImportError` and a comment.
- Menus are rebuilt each time they open. Menu modules are functions `add_<name>_menu(parent, ..., config, apply_settings)`; every action saves to `config` and calls `apply_settings()` at once. Radio choices use `QActionGroup`. Device lists are filled in `aboutToShow`, so newly plugged-in devices appear.

## Optional dependencies and failures

- Import heavy packages inside the method that first needs them, catch `ImportError`, and raise the module's error type with an install hint constant (`INSTALL_HINT = "Install it with:  pip install ..."`).
- Each layer has one exception class whose message is for the user: `ProviderError`, `MicrophoneError`, `TranscriptionError`, `SynthesisError`, `PlaybackError`. Catch broad `Exception` only at the boundary where a library's unknown failure modes meet the app, mark it `# noqa: BLE001` with a reason, and turn it into the user-facing type.
- A controller that would fail on every event (a broken engine) reports once and goes quiet until the settings change, instead of nagging.

## User-facing text

- Alter Ego speaks all of it, in the first person: "I can't hear anything at all. Is the microphone muted?" Say what happened, then what to do, in one or two short sentences. Name the exact menu path when there is one (`Spoken replies -> Download my voice`).
- Terminal output (`print`) is for diagnostics and starts with `Alter Ego:` or `Warning:`; it is plain, not in character.

## Tests

- `unittest`, one file per feature area in `tests/`, each with the header comment and the `sys.path.insert` + `QCoreApplication` boilerplate copied from an existing test file.
- Fakes, not mocks: a `FakeRecorder`, `FakeTranscriber`, `FakePlayer` class with the same methods as the real one, plus fake HTTP servers (`HTTPServer` on port 0) for API engines and a fake `claude` script for Claude Code.
- Async flows are driven with `process_events_until(condition, timeout)`. Tests must pass with no network, microphone, speakers, model files or display, and write only to temporary folders.
- Test names say the behaviour: `test_short_press_is_ignored`, `test_download_is_asked_for_not_done`.

## Documentation

- The README is updated in the same change as the code. Settings defaults in the README match `DEFAULTS` exactly. The code layout tree lists every module with a one-line purpose.
- Keep the README's voice: plain, concrete, second person for instructions, no marketing.
