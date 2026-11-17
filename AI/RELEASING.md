# Releasing

How a version goes from the code to the Releases page. Only the owner tags and publishes. An assistant prepares everything up to the tag, and only when asked.

## Version numbers

`vMAJOR.MINOR.PATCH`. A minor version is a feature milestone from the roadmap (v0.6.0 spoken replies, v0.7.0 easy install), and a patch is fixes only. The single source of truth is `__version__` in `src/alter_ego/__init__.py`.

## Checklist

1. **Everything is in.** The tests pass, the app was run and looked at, and the plan's "Now" items for this version are done.
2. **Version.** Set `__version__` in `src/alter_ego/__init__.py`.
3. **Changelog.** Write the version's section at the top of `CHANGELOG.md`, headed exactly `## vX.Y.Z: short title`. Write it for users: what they can do now that they couldn't before. The release workflow uses this section as the release notes.
4. **README.** Update the "Current version" line and tick the roadmap item.
5. **Plans.** Update `AI/PLANS.md`: the next milestone becomes "Now".
6. **Commit** with the message `vX.Y.Z short description`.
7. **Dry run (recommended).** On GitHub, go to **Actions** → **Release** → **Run workflow** on the branch. It builds and tests everything and uploads the files as workflow artifacts, without publishing. Download them and try them on a clean machine if you can.
8. **Tag and push.** Merge to `main`, then:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

   The workflow builds on Windows and Linux, runs the tests, builds the program with PyInstaller, smoke-tests the file-tool server from the build, packages the files, and publishes the release with the changelog section. It refuses a tag that doesn't match `__version__`.

## What CI builds

| File | Made by |
|---|---|
| `AlterEgo-Setup-vX.Y.Z.exe` | PyInstaller, then Inno Setup (`packaging/windows/alter_ego.iss`) |
| `AlterEgo-vX.Y.Z-windows-portable.zip` | The same PyInstaller folder, zipped |
| `AlterEgo-vX.Y.Z-linux-x86_64.tar.gz` | PyInstaller on Ubuntu 22.04, plus `packaging/linux/` (install script, launcher, icon) |

Every build includes the character voice with CPU PyTorch. A file over 2 GB fails the build, because GitHub refuses release files that large.

## Building locally

See [`docs/FROM_SOURCE.md`](../docs/FROM_SOURCE.md#building-the-downloads-yourself). For a quick check of the packaging, `ALTER_EGO_LITE=1` leaves out PyTorch. Run a full build at low priority: it is heavy (see the machine rules in [`README.md`](README.md)).

After building, check the result by hand:

- `dist/AlterEgo/AlterEgo(.exe)` starts, with `ALTER_EGO_DATA_DIR` set to an empty folder so the first-run setup shows.
- The setup window lists what is missing. Skip, then reopen it from the AI menu.
- `alter_ego.log` appears in that folder when the app is started from Explorer or the desktop, not from a terminal.
- A chat reply, push to talk, and a spoken reply all work.

## When something in the build breaks

- **A module or data file is missing at runtime** (it shows in `alter_ego.log`): add the package to `PACKAGES` or `VOICE_PACKAGES` in `packaging/alter_ego.spec`, so PyInstaller collects all of it.
- **The download got much bigger:** check that no CUDA PyTorch slipped in (the workflow installs from the CPU index), and that the Qt modules excluded in the spec are still excluded.
