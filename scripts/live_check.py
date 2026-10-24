#!/usr/bin/env python3
"""Run safe read-only checks in the existing deployment; no duplicate runtime."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.host_check import main

if __name__ == "__main__":
    raise SystemExit(main())
