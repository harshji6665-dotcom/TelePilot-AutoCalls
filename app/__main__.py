import asyncio
import sys

from pydantic import ValidationError

from .config import ConfigurationError
from .runtime import main, ServiceStartupError

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (ConfigurationError, ServiceStartupError) as exc:
        print("Startup error:", str(exc), file=sys.stderr)  # Only curated, secret-free exception types.
        sys.exit(2)
    except (ValidationError, ValueError, FileNotFoundError) as exc:
        # Pydantic's normal str(exc) includes original values: never print it for secret fields.
        if isinstance(exc, ValidationError):
            for item in exc.errors(include_input=False, include_url=False):
                print("Config error:", ".".join(map(str, item["loc"])), item["msg"], file=sys.stderr)
        else:
            print(
                f"Configuration/startup failed ({type(exc).__name__}). Check config.json and required environment variables.",
                file=sys.stderr,
            )
        sys.exit(2)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(
            f"TelePilot startup/runtime failed ({type(exc).__name__}). Check sanitized logs and credentials/connectivity.", file=sys.stderr
        )
        sys.exit(1)
