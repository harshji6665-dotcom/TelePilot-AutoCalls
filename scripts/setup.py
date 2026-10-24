#!/usr/bin/env python3
"""Standard-library-only setup; credentials never appear in process arguments/logs."""

import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import re
import secrets

ROOT = Path(__file__).resolve().parent.parent


def ask(prompt, check=lambda value: bool(value), secret=False, default=""):
    while True:
        value = (getpass.getpass(prompt) if secret else input(prompt)).strip() or default
        if check(value):
            return value
        print("Invalid value; please try again.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create a NEW installation only; never overwrite an existing encryption key.")
    parser.add_argument("--profile", choices=("standard", "vps200"), default="standard")
    args = parser.parse_args([] if argv is None and __name__ != "__main__" else argv)
    os.umask(0o077)
    print(
        "TelePilot setup — use your own accounts, API credentials and bot.\nSecrets remain on this host. Nothing is sent by this setup script."
    )
    if (ROOT / ".env").exists():
        print(".env already exists. Refusing to overwrite keys; losing the original encryption key makes sessions unreadable.")
        return 1
    api_id = ask("Telegram API ID (my.telegram.org): ", lambda v: v.isdigit() and int(v) > 0)
    api_hash = ask("Telegram API Hash (hidden): ", lambda v: bool(re.fullmatch(r"[0-9a-fA-F]{32}", v)), secret=True)
    bot_token = ask("BotFather token (hidden): ", lambda v: bool(re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", v)), secret=True)
    ids = ask("Owner user ID(s), comma separated: ", lambda v: all(x.strip().isdigit() and int(x.strip()) > 0 for x in v.split(",")))
    owners = list(dict.fromkeys(int(x.strip()) for x in ids.split(",")))
    domain = ask(
        "Public HTTPS domain (optional for private-chat sign-in), blank to skip: ",
        lambda v: not v or bool(re.fullmatch(r"[a-zA-Z0-9.-]+\.[A-Za-z]{2,}", v)),
    )
    email = (
        ask("TLS certificate email: ", lambda v: bool(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", v))) if domain else ""
    )
    support = ask("Support @username (optional): ", lambda v: not v or bool(re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{4,31}", v))).lstrip("@")
    external = ask(
        "External MongoDB URI (hidden), blank for bundled Mongo: ",
        lambda v: not v or v.startswith(("mongodb://", "mongodb+srv://")),
        secret=True,
    )
    if external and any(c in external for c in ("\n", "\r", "'")):
        print("Unsupported quote/newline in URI. URL-encode MongoDB credentials and run again.")
        return 1
    root_password, app_password = secrets.token_hex(24), secrets.token_hex(24)
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    uri = external or f"mongodb://telepilot:{app_password}@mongo:27017/telepilot?authSource=telepilot"
    config = json.loads((ROOT / "config.example.json").read_text())
    config.update(owner_ids=owners, public_base_url=("https://" + domain if domain else ""), support_username=support)
    (ROOT / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    # The JSON contains env references, not secrets, so the non-root container can read it.
    (ROOT / "config.json").chmod(0o644)
    env = {
        "TELEGRAM_API_ID": api_id,
        "TELEGRAM_API_HASH": api_hash,
        "BOT_TOKEN": bot_token,
        "SESSION_ENCRYPTION_KEY": key,
        "MONGO_ROOT_PASSWORD": root_password,
        "MONGO_APP_PASSWORD": app_password,
        "MONGO_URI": uri,
        "PUBLIC_DOMAIN": domain,
        "TLS_EMAIL": email,
        "LOGIN_MODE": "chat",
        "MAX_POOL_ACCOUNTS": "200",
        "OWNER_IDS": ",".join(map(str, owners)),
        "ADMIN_USERNAME": support,
    }
    if args.profile == "vps200":
        env.update(VPS_MAX_POOL_ACCOUNTS="200", MANUAL_HEALTH_TIMEOUT_SECONDS="1800")
    (ROOT / ".env").write_text("\n".join(f"{k}='{v}'" for k, v in env.items()) + "\n")
    (ROOT / ".env").chmod(0o600)
    print("\nCreated .env (private secrets) and config.json (external configuration). Back up .env securely.")
    if domain:
        print("Set your domain's DNS A record to this VPS and allow inbound TCP 80/443.")
    if args.profile == "vps200":
        command = "docker compose -f compose.vps200.external.yaml" if external else "docker compose -f compose.yaml -f compose.vps200.yaml"
    else:
        command = "docker compose -f compose.vps200.external.yaml" if external else "docker compose -f compose.yaml"
    if domain:
        command += " -f compose.https.yaml"
    print("Start: " + command + " up -d --build")
    print("Private-chat sign-in works without an HTTPS login page; use /signin as staff.")
    if external:
        print("External Mongo: no bundled database is started. Keep its original database name and encryption key on upgrades.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
