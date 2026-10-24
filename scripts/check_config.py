#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pydantic import ValidationError
from app.config import load_config, ConfigurationError

try:
    config = load_config()
    print(
        "Config valid. Owners:",
        len(config.owner_ids),
        "Calls:",
        config.calls_enabled,
        "Login mode:",
        config.login_mode,
        "HTTPS configured:",
        bool(config.public_base_url),
        "HTTP port:",
        config.http_port,
    )
except ConfigurationError as exc:
    print("Config error:", str(exc))
    raise SystemExit(2)
except ValidationError as exc:
    for error in exc.errors(include_input=False, include_url=False):
        print("Invalid field:", ".".join(map(str, error["loc"])), error["msg"])
    raise SystemExit(2)
except Exception as exc:
    print("Configuration unavailable:", type(exc).__name__, "(check required environment variables).")
    raise SystemExit(2)
