# Contributing

Thanks for wanting to help Alter Ego grow! Bug reports, ideas and code are all welcome.

## Reporting a problem

[Open an issue](https://github.com/1andresito/AlterEgo-Companion/issues). Say what you did, what you expected and what happened. Attach `alter_ego.log` from Alter Ego's data folder (`%APPDATA%\AlterEgo` on Windows, `~/.config/alter_ego` on Linux) if you can. Check it first: it shouldn't contain anything private, but it's yours to share.

## Changing the code

1. Set up the project from source: [docs/FROM_SOURCE.md](docs/FROM_SOURCE.md).
2. Read the guide in [`AI/`](AI/README.md). It's written for AI coding assistants, but it's the same guide for people: the rules that are not negotiable, how the code is laid out, the code style, and why some things are the way they are.
3. Keep the change focused, add tests for anything that isn't drawn on screen, and run the suite:

   ```bash
   QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
   ```

4. Update the docs in the same change (the README for anything a user would notice) and open a pull request.

Using an AI assistant? Point it at [`AI/README.md`](AI/README.md) before it writes anything.
