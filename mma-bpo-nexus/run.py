#!/usr/bin/env python3
"""Run MMA BPO NEXUS with secure conversation, voice, and LiveKit integrations."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import uvicorn

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.main import create_app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="MMA BPO NEXUS")
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 for a sandbox/LAN preview")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
