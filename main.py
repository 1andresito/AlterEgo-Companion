from pathlib import Path
import sys

# Make the src-layout package importable when running directly from a checkout.
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from alter_ego.app import run


if __name__ == "__main__":
    raise SystemExit(run())
