# Alter Ego: instructions for Claude Code

All guidance for AI assistants lives in the `AI/` folder, shared by every tool. Read it before changing anything:

1. `AI/README.md`: the project in one page, the rules that are not negotiable (local-first privacy, the app always runs, the GUI never freezes, modules talk through signals, easy for a newcomer), and how a change is made.
2. `AI/ARCHITECTURE.md`: the code layout and where a new feature goes.
3. `AI/CODE_STYLE.md`: how code, comments, tests and docs are written here.
4. `AI/DECISIONS.md`: why some things are the way they are. Read it before "fixing" one.
5. `AI/PLANS.md`: what is being worked on now and next. Update it when you start or finish something.
6. `AI/RELEASING.md`: versions, the changelog and the release builds.

Claude Code specifics:

- Use the project virtual environment, Python 3.12: `.venv\Scripts\python` on Windows, `.venv/bin/python` on Linux. If it is missing, create it with `python3.12 -m venv .venv` (on Windows `py -3.12 -m venv .venv`) and install `requirements.txt`. Python 3.14 breaks the character voice.
- Heavy experiments (PyTorch, benchmarks, full PyInstaller builds) run at low priority with at most 6 threads, one at a time, in the background.
- Tests: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m unittest discover -s tests -v` (`.venv/bin/python` on Linux). They must pass before you report a task as done.
- To check the real app, run `python -u main.py` from the venv in the background or with a timeout; it is a desktop window plus a tray icon and keeps running until quit. Set `ALTER_EGO_DATA_DIR` to an empty scratch folder to see the first-run setup without touching the owner's settings.
- Keep the docs in step with every user-visible change, as `AI/CODE_STYLE.md` describes (README for users, `docs/` for reference, `CHANGELOG.md` per version).
- Do not commit, tag or bump the version unless asked. Commit message style: `vX.Y.Z short description`.
