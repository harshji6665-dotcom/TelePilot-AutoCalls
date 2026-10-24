"""Never serialize exception messages, request bodies, secrets or Telethon updates."""

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import traceback


class SafeFormatter(logging.Formatter):
    def __init__(self, secrets=()):
        super().__init__()
        self.secrets = tuple(s for s in secrets if s)

    def format(self, record):
        message = record.getMessage()
        # asyncio's default lifecycle messages embed task/future reprs, whose
        # exception/coroutine args can contain credentials even without exc_info.
        # Retain severity, event identity, exception type and traceback frames;
        # never forward those raw reprs to console/file/owner alerts.
        if record.name == "asyncio":
            if "exception was never retrieved" in message:
                message = "Async background exception was not retrieved; inspect error_type/frames"
            elif "Task was destroyed" in message or "coroutine ignored GeneratorExit" in message:
                message = "Async task lifecycle cleanup failed; inspect error_type/frames"
            else:
                message = "Async event-loop diagnostic; inspect error_type/frames"
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        message = re.sub(r"\b\d{5,}:[A-Za-z0-9_-]{20,}\b", "[BOT_TOKEN]", message)
        message = re.sub(r"mongodb(?:\+srv)?://\S+", "[MONGO_URI]", message)
        data = {"time": self.formatTime(record), "level": record.levelname, "logger": record.name, "message": message}
        if record.exc_info and record.exc_info[0]:
            data["error_type"] = record.exc_info[0].__name__
            data["frames"] = [f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in traceback.extract_tb(record.exc_info[2])]
        return json.dumps(data, ensure_ascii=False)


def configure_logging(config):
    formatter = SafeFormatter(
        [
            config.api_hash.get_secret_value(),
            config.bot_token.get_secret_value(),
            config.mongo_uri.get_secret_value(),
            config.session_encryption_key.get_secret_value(),
        ]
    )
    stream = logging.StreamHandler()
    handlers, file_error = [stream], None
    if config.log_directory:
        try:
            directory = Path(config.log_directory)
            directory.mkdir(parents=True, exist_ok=True)
            handlers.append(RotatingFileHandler(directory / "events.jsonl", maxBytes=5_000_000, backupCount=3, encoding="utf-8"))
        except OSError as exc:
            file_error = type(exc).__name__
    for handler in handlers:
        handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(logging.INFO)
    if file_error:
        root.warning("File logging unavailable; using sanitized console logs only; error=%s", file_error)
    # Third-party messages may contain phone numbers or raw Telegram updates.
    for name in ("telethon", "pytgcalls", "aiogram", "httpx", "httpcore", "pymongo", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
