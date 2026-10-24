from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

POOL_ACCOUNT_CEILING = 200

DEFAULT_BANNER = "https://i.ibb.co/1Nx1jMn/IMG-20261005-021725.png"


class ConfigurationError(ValueError):
    """Only deliberately authored, secret-free startup diagnostics."""


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Safety-first defaults (lower concurrency + slower pacing to reduce VPS / Telegram risk)
    max_force_sub_channels: int = Field(5, ge=1, le=20)
    max_auto_channels: int = Field(10, ge=1, le=100)
    auto_parallel_connects: int = Field(1, ge=1, le=5)
    auto_call_poll_seconds: int = Field(60, ge=15, le=300)
    auto_probe_timeout_seconds: int = Field(45, ge=5, le=120)
    auto_detection_budget_seconds: int = Field(60, ge=15, le=300)
    auto_stale_seconds: int = Field(300, ge=60, le=600)
    max_auto_sessions_per_user_day: int = Field(4, ge=1, le=100)
    max_pool_accounts: int = Field(50, ge=1, le=POOL_ACCOUNT_CEILING)  # safer default; raise only if needed
    default_plan_accounts: int = Field(3, ge=1, le=POOL_ACCOUNT_CEILING)
    default_plan_channels: int = Field(1, ge=1, le=100)
    max_channels_per_user: int = Field(20, ge=1, le=100)
    manual_health_timeout_seconds: int = Field(600, ge=15, le=1800)
    max_jobs_per_user_day: int = Field(4, ge=1, le=100)
    max_pending_jobs_per_user: int = Field(2, ge=1, le=30)
    max_parallel_jobs: int = Field(1, ge=1, le=10)
    global_rpc_gap_seconds: float = Field(4.5, ge=1, le=120)
    account_join_gap_seconds: int = Field(90, ge=15, le=3600)
    account_joins_per_day: int = Field(8, ge=1, le=100)
    max_call_minutes: int = Field(120, ge=5, le=1440)
    call_poll_seconds: int = Field(45, ge=15, le=300)
    call_start_grace_seconds: int = Field(240, ge=0, le=900)
    max_start_delay_seconds: int = Field(1200, ge=60, le=3600)
    max_rejoin_attempts: int = Field(1, ge=0, le=5)
    health_interval_seconds: int = Field(600, ge=60, le=3600)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_id: int = Field(gt=0)
    api_hash: SecretStr
    bot_token: SecretStr
    mongo_uri: SecretStr
    mongo_database: str = "telepilot"
    owner_ids: list[int] = Field(min_length=1)
    session_encryption_key: SecretStr
    public_base_url: str = ""
    login_mode: Literal["chat", "browser"] = "chat"
    ui_style: Literal["smallcaps", "plain"] = "smallcaps"
    ui_edit_panels: bool = True
    ui_clean_inputs: bool = True
    timezone: str = "Asia/Kolkata"
    logging_chat_id: int | None = None
    support_username: str = ""
    admin_username: str = ""
    default_start_image_url: str = DEFAULT_BANNER
    start_photo_enabled: bool = True
    calls_enabled: bool = True
    auto_calls_enabled: bool = True
    compatibility_check_hours: int = Field(24, ge=1, le=168)
    log_directory: str = "data/logs"
    http_port: int = Field(8080, ge=1, le=65535)
    startup_lease_timeout_seconds: int = Field(180, ge=5, le=600)
    audit_retention_days: int = Field(90, ge=7, le=365)
    limits: Limits = Field(default_factory=Limits)

    @field_validator("api_hash")
    @classmethod
    def api_hash_valid(cls, v):
        if not re.fullmatch(r"[0-9a-fA-F]{32}", v.get_secret_value()):
            raise ValueError("api_hash must be the 32-character value from my.telegram.org")
        return v

    @field_validator("bot_token")
    @classmethod
    def bot_token_valid(cls, v):
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", v.get_secret_value()):
            raise ValueError("bot_token must be your BotFather token")
        return v

    @field_validator("mongo_uri")
    @classmethod
    def mongo_valid(cls, v):
        if not v.get_secret_value().startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("mongo_uri must be a MongoDB URI")
        return v

    @field_validator("owner_ids", mode="before")
    @classmethod
    def parse_owners(cls, value):
        if isinstance(value, str):
            value = value.strip()
            try:
                value = json.loads(value) if value.startswith("[") else [int(item.strip()) for item in value.split(",") if item.strip()]
            except (ValueError, TypeError):
                raise ValueError("OWNER_IDS must be numeric Telegram user IDs, comma-separated or a JSON list") from None
        elif isinstance(value, int) and not isinstance(value, bool):
            value = [value]
        if value == [] or value is None:
            raise ValueError("Set OWNER_IDS to your numeric Telegram user ID (not the bot ID), or fill owner_ids in external config.json")
        return value

    @field_validator("owner_ids")
    @classmethod
    def owners_valid(cls, v):
        if any(i <= 0 for i in v) or len(set(v)) != len(v):
            raise ValueError("owner_ids must be unique positive Telegram user IDs")
        return v

    @field_validator("session_encryption_key")
    @classmethod
    def key_valid(cls, v):
        try:
            Fernet(v.get_secret_value().encode())
        except Exception:
            raise ValueError(
                "SESSION_ENCRYPTION_KEY must be a complete 44-character Fernet key; keep its trailing =. Use scripts/generate_key.py for a new installation only"
            ) from None
        return v

    @field_validator("public_base_url")
    @classmethod
    def https_only(cls, v):
        if not v:
            return v
        parsed = urlparse(v)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("public_base_url must be https://your-domain (no credentials/query/fragment)")
        if parsed.path not in ("", "/"):
            raise ValueError("public_base_url must not contain a path")
        return v.rstrip("/")

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, v):
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone must be a valid IANA timezone, e.g. Asia/Kolkata") from None
        return v

    @field_validator("support_username", "admin_username")
    @classmethod
    def support_valid(cls, v):
        v = v.lstrip("@")
        if v and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", v):
            raise ValueError("Contact username must be a Telegram username, not a URL")
        return v

    @model_validator(mode="after")
    def limits_valid(self):
        if self.limits.default_plan_accounts > self.limits.max_pool_accounts:
            raise ValueError("default_plan_accounts cannot exceed max_pool_accounts")
        if self.limits.default_plan_channels > self.limits.max_channels_per_user:
            raise ValueError("default_plan_channels cannot exceed max_channels_per_user")
        return self


ENV_FIELDS = {
    "api_id": ("TELEGRAM_API_ID", "API_ID"),
    "api_hash": ("TELEGRAM_API_HASH", "API_HASH"),
    "bot_token": ("BOT_TOKEN",),
    "mongo_uri": ("MONGO_URI", "MONGODB_URI"),
    "mongo_database": ("MONGO_DATABASE",),
    "owner_ids": ("OWNER_IDS", "OWNER_ID"),
    "session_encryption_key": ("SESSION_ENCRYPTION_KEY",),
    "public_base_url": ("PUBLIC_BASE_URL",),
    "login_mode": ("LOGIN_MODE",),
    "ui_style": ("UI_STYLE",),
    "ui_edit_panels": ("UI_EDIT_PANELS",),
    "ui_clean_inputs": ("UI_CLEAN_INPUTS",),
    "timezone": ("TIMEZONE",),
    "logging_chat_id": ("LOGGING_CHAT_ID",),
    "support_username": ("SUPPORT_USERNAME",),
    "admin_username": ("ADMIN_USERNAME", "CONTACT_ADMIN_USERNAME"),
    "calls_enabled": ("CALLS_ENABLED",),
    "auto_calls_enabled": ("AUTO_CALLS_ENABLED",),
    "start_photo_enabled": ("START_PHOTO_ENABLED",),
    "log_directory": ("LOG_DIRECTORY",),
    "http_port": ("PORT", "HTTP_PORT"),
    "startup_lease_timeout_seconds": ("STARTUP_LEASE_TIMEOUT_SECONDS",),
}
LIMIT_ENV_FIELDS = {"max_pool_accounts": ("MAX_POOL_ACCOUNTS",), "manual_health_timeout_seconds": ("MANUAL_HEALTH_TIMEOUT_SECONDS",)}

REQUIRED_ENV = {
    "api_id": "TELEGRAM_API_ID",
    "api_hash": "TELEGRAM_API_HASH",
    "bot_token": "BOT_TOKEN",
    "mongo_uri": "MONGO_URI",
    "owner_ids": "OWNER_IDS",
    "session_encryption_key": "SESSION_ENCRYPTION_KEY",
}


def load_config(path: str | Path | None = None) -> Config:
    # Explicit external config paths stay strict. The default can bootstrap from
    # a public template + service variables when a PaaS has no bind mounts.
    configured_path = path or os.getenv("CONFIG_PATH")
    explicit = configured_path is not None
    source = Path(configured_path) if explicit else Path("config.json")
    if explicit and not source.is_file():
        raise ConfigurationError(
            "CONFIG_PATH file is missing. Mount the external config file, or remove CONFIG_PATH to use environment-only deployment."
        )
    if not source.is_file():
        source = Path(__file__).resolve().parent.parent / "config.example.json"
    if source.is_file():
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise ConfigurationError("Configuration JSON is invalid. Fix JSON syntax; no credentials were printed.") from None
        except OSError:
            raise ConfigurationError("Configuration cannot be read. Check file permissions for the non-root container user.") from None
        if not isinstance(raw, dict):
            raise ConfigurationError("Configuration JSON must be an object.")
    else:
        raw = {}

    # Explicit service variables override file values; file-only configuration
    # remains supported for existing Docker Compose deployments.
    for field, names in ENV_FIELDS.items():
        for name in names:
            if name in os.environ:
                if field in {"auto_calls_enabled", "start_photo_enabled"} and not os.environ[name]:
                    continue  # Optional Compose passthrough preserves explicit JSON false.
                if field == "admin_username" and not os.environ[name] and raw.get(field):
                    continue  # Compose's optional empty default must not erase JSON contact.
                if field in {"owner_ids", "mongo_database", "public_base_url"} and not os.environ[name].strip() and raw.get(field):
                    continue  # Optional VPS passthrough must not erase private JSON values.
                raw[field] = os.environ[name]
                break
    if not raw.get("public_base_url"):
        domain = os.getenv("PUBLIC_DOMAIN") or os.getenv("RAILWAY_PUBLIC_DOMAIN")
        if domain:
            raw["public_base_url"] = domain if domain.startswith("https://") else "https://" + domain
    if raw.get("logging_chat_id") == "":
        raw["logging_chat_id"] = None

    def expand(value):
        if isinstance(value, str):

            def replace(match):
                name = match.group(1)
                if name not in os.environ or not os.environ[name]:
                    raise ConfigurationError(
                        f"Required environment variable missing: {name}. Set it in service Variables or supply it in external config.json."
                    )
                return os.environ[name]

            return re.sub(r"\$\{([A-Z][A-Z0-9_]*)\}", replace, value)
        if isinstance(value, list):
            return [expand(x) for x in value]
        if isinstance(value, dict):
            return {k: expand(v) for k, v in value.items()}
        return value

    raw = expand(raw)
    # Nested limit override for upgrades: keep private JSON, change only this
    # non-secret service variable. Blank Compose passthrough preserves the file.
    for field, names in LIMIT_ENV_FIELDS.items():
        for name in names:
            if os.getenv(name, "").strip():
                limits = raw.get("limits", {})
                if not isinstance(limits, dict):
                    raise ConfigurationError("limits must be a JSON object.")
                raw["limits"] = {**limits, field: os.environ[name]}
                break
    missing = [
        name for field, name in REQUIRED_ENV.items() if field not in raw or raw[field] is None or raw[field] == "" or raw[field] == []
    ]
    if missing:
        raise ConfigurationError(
            "Required settings missing: " + ", ".join(missing) + ". Set these service variables or use external config.json."
        )
    return Config.model_validate(raw)
