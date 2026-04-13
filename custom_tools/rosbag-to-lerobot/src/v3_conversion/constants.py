"""Path constants for the standalone conversion pipeline."""

import os
from pathlib import Path

_HOME = Path.home()
INPUT_PATH = Path(os.environ.get("INPUT_PATH", str(_HOME / "aic_data" / "raw")))
OUTPUT_PATH = Path(os.environ.get("OUTPUT_PATH", str(_HOME / "aic_data" / "lerobot")))
DONE_PATH = Path(os.environ.get("DONE_PATH", str(_HOME / "aic_data" / "done")))
SKIPPED_PATH = Path(os.environ.get("SKIPPED_PATH", str(_HOME / "aic_data" / "skipped")))
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
