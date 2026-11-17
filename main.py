from pathlib import Path
import sys

# Make the src-layout package importable when running directly from a checkout.
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


if __name__ == "__main__":
    if "--tool-server" in sys.argv:
        # Started by Claude Code as Alter Ego's file-tool server; no window, no Qt.
        from alter_ego.providers.tools_mcp import main as serve_tools

        raise SystemExit(serve_tools())
    from alter_ego.app import run

    raise SystemExit(run())
