#!/usr/bin/env python3
"""Compatibility entry point for the safe, sanitized host verifier.

Unlike the older smoke check, this does not initialize indexes, print bot/owner
identifiers, acquire a lease or start Telegram user clients.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.host_check import main

if __name__ == "__main__":
    raise SystemExit(main())
