"""Vercel entrypoint; the Windows/local launcher keeps using servidor.py."""

import sys
from pathlib import Path


APP_DIRECTORY = Path(__file__).resolve().parent / "MarketIntel-v6.4"
sys.path.insert(0, str(APP_DIRECTORY))

from servidor import app  # noqa: E402,F401
