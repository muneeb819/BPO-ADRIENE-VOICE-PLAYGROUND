"""Application paths and runtime defaults."""

from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = Path(os.environ.get("NEXUS_DB_PATH", str(DATA_DIR / "nexus.db")))
FRONTEND_DIR = PROJECT_ROOT / "frontend"

APP_NAME = "MMA BPO NEXUS"
APP_VERSION = "0.4.1"
STAGE = 4
MAX_REQUEST_BYTES = 64_000
MAX_AUDIO_BYTES = 8_000_000
