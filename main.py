from pathlib import Path
import os
import sys

# Make the src-layout package importable when running directly from a checkout.
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

LOG_FILENAME = "alter_ego.log"


def log_to_file_without_console() -> None:
    """A packaged build has no console, so diagnostics (the hands-free checks, warnings) go to a log file.

    Started fresh each run, in the data folder next to the settings. The tool
    server is left alone: Claude Code talks to it over stdin/stdout.
    """
    # Windows gives a windowed build no stdout at all; a Linux desktop launcher gives it /dev/null.
    # Either way nobody would see the output. A terminal (or a pipe) keeps it.
    if not getattr(sys, "frozen", False):
        return
    if sys.stdout is not None and sys.stderr is not None and _output_is_kept():
        return
    from alter_ego.settings.config import data_dir

    try:
        folder = data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        log = open(folder / LOG_FILENAME, "w", encoding="utf-8", buffering=1)
    except OSError:
        return
    sys.stdout = log
    sys.stderr = log


def _output_is_kept() -> bool:
    """False when stdout goes nowhere (missing or /dev/null)."""
    try:
        return sys.stdout.isatty() or os.path.realpath(f"/proc/self/fd/{sys.stdout.fileno()}") != os.devnull
    except (AttributeError, OSError, ValueError):
        return False


if __name__ == "__main__":
    if "--tool-server" in sys.argv:
        # Started by Claude Code as Alter Ego's file-tool server; no window, no Qt.
        from alter_ego.providers.tools_mcp import main as serve_tools

        raise SystemExit(serve_tools())
    if "--check-voice" in sys.argv:
        # Used by the release workflow: can this build load the character voice converter?
        from alter_ego.voice.rvc_local import check_converter_import

        raise SystemExit(check_converter_import())
    log_to_file_without_console()
    from alter_ego.app import run

    raise SystemExit(run())
