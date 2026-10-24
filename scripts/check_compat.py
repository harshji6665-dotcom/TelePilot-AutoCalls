#!/usr/bin/env python3
import importlib.metadata
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.compat import PACKAGES, local_compatibility

print(local_compatibility())
for package in PACKAGES:
    print(package, importlib.metadata.version(package))
