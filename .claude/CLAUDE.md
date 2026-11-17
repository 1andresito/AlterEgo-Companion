# Alter Ego: instructions for Claude Code

All guidance for AI assistants lives in the `AI/` folder, shared by every tool. Read it before changing anything:

1. `AI/README.md`: the project in one page and the rules that are not negotiable (local-first privacy, the app always runs, the GUI never freezes, modules talk through signals).
2. `AI/CODE_STYLE.md`: how code, comments, tests and user-facing text are written here.
3. `AI/ARCHITECTURE.md`: where a new feature goes.
4. `AI/PLANS.md`: what is being worked on now and next. Update it when you start or finish something.

Claude Code specifics:

- Use the project virtual environment: `.venv/bin/python`, which is Python 3.12 (create it with `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt` if missing; 3.14 breaks the optional character voice).
- Heavy experiments (PyTorch, benchmarks) only with `nice -n 19`, at most 6 threads, one at a time, in the background.
- Tests: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`. They must pass before you report a task as done.
- To check the real app, run `.venv/bin/python -u main.py` in the background or with a `timeout`; it is a desktop window plus tray icon and keeps running until quit.
- Keep the README in step with every user-visible change, as `AI/README.md` describes.
- Do not commit or bump the version unless asked. Commit message style: `vX.Y.Z short description`.
