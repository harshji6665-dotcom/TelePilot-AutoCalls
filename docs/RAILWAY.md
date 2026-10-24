> **1.5.0 / selected 200-account VPS deployment:** use [VPS_200.md](VPS_200.md) for the 8-vCPU / 64-GB Docker resource profiles, one-worker boot/restart/optional-watchdog instructions, and original-data-preserving migration. Source capacity is 200; actual 200-native-instance load is not certified.

> **1.4.4 incident procedure:** the latest export confirms duplicated/invalidated authorization keys. Read [SESSION_SAFETY.md](SESSION_SAFETY.md) before signing in again. Stop all old/copy deployments; retain ORIGINAL config/key/database/volumes. Deploy one guarded runtime, inspect `/sessionguard`, run `scripts/live_check.py --scope safety`, and resume only after owner review. A static IP or one visible replica does not prove no parallel main sessions exist.

> **1.4.3 transport fix:** rebuild the complete source with the ORIGINAL private config/encryption key/database/volumes and one replica. See [TRANSPORT_RECOVERY.md](TRANSPORT_RECOVERY.md) for the supplied-log findings, future ownership, offline cleanup and safe recovery. A 404 buffer is not automatically a ban; do not repeatedly sign in or reset data. Follow [HOST_VERIFICATION.md](HOST_VERIFICATION.md) for actual authorized host checks.

> **1.4.2 host verification:** rebuild this complete source with your original external configuration/key/database/volumes and one replica. Follow [HOST_VERIFICATION.md](HOST_VERIFICATION.md) in the **existing running app container**. Do not launch a second runtime or clone sessions for testing. Automated source/image tests are separate from your pending real Telegram/RTC acceptance.

> **1.4.1 saved-session recovery:** rebuild the updated source while retaining the **original private config/env, encryption key, Mongo database and volumes**. Do not copy the public starter config over production, rerun setup/key generation or run multiple replicas. Read [SESSION_RECOVERY.md](SESSION_RECOVERY.md) for automatic reconnect/backoff, safe reauthentication and genuine revocation/ban limits. Never use `down -v` as an upgrade step.

> **1.4.0:** independent unlimited Premium quotas, current/future eligible pool access, and runtime callback/disconnect/notification hardening. Read [UNLIMITED_PREMIUM.md](UNLIMITED_PREMIUM.md) and [RUNTIME_LOG_AUDIT.md](RUNTIME_LOG_AUDIT.md) before upgrading. Schema 3 nullable unlimited plans are not compatible with simply rolling old integer-only code back. Preserve private config/key/database/volumes; rebuild/redeploy one replica. Unlimited paid quotas do not raise operational host ceilings.

> **Current / existing 20-account installs:** set **MAX_POOL_ACCOUNTS=200** in the existing .env/service Variables and rebuild/redeploy updated source/compose.yaml. Do not replace private files or regenerate keys. A retained JSON cap of 20 without this override still means 20. New pool-capacity view, visible callback errors and background roster loading are documented in [ACCOUNT_CAPACITY.md](ACCOUNT_CAPACITY.md). One replica; all real Telegram/RTC acceptance still belongs on your own authorized host.

> **1.3.1:** preserve original .env/config.json/key/database/volumes, replace source and rebuild. Public joins now use direct usernames and owner start-photo settings persist in Mongo. START_PHOTO_ENABLED supplies the initial default; owner choice takes precedence. See PUBLIC_JOINS_PHOTOS.md. New source cannot revive revoked Telegram sessions.

> **1.3.0 update:** preserve private .env/config.json, original key/database/volumes, replace source and rebuild one replica. Required subscriptions are initially empty; auto mode is off for old targets until opted in. AUTO_CALLS_ENABLED controls global availability, not per-user consent. See FORCE_SUBSCRIBE.md and AUTO_CALLS.md; never test with production credentials.

> **1.2.0 subscriptions update:** set `ADMIN_USERNAME` for contact admin, rebuild updated source, and retain the original encryption key/database. Existing Premium plans keep both features and their prior allowance. New feature/quota settings are assigned in manage bot. See [SUBSCRIPTIONS.md](SUBSCRIPTIONS.md) and [HEALTH.md](HEALTH.md). Migration runs only after leadership; never reset volumes or run the old bot alongside this one.

> **1.1.0 update:** default smallcaps and editable panels; keep `LOGIN_MODE=chat`, the original encryption key and database, then rebuild/redeploy. Optional Variables: `UI_STYLE=smallcaps`, `UI_EDIT_PANELS=true`, `UI_CLEAN_INPUTS=true`. See [CLEAN_UI.md](CLEAN_UI.md) and [AUDIT.md](AUDIT.md).

> **1.0.2:** keep these Railway/config/PORT fixes, add LOGIN_MODE=chat and rebuild (new QR deps). Staff → Sign in account → consent → Phone/OTP/2FA or QR; **no browser approval is needed**. Public domain stays useful for health, not chat login. Old portal returns 410. Keep original encryption key/database. See [CHAT_SIGNIN.md](CHAT_SIGNIN.md).

# Railway deployment — TelePilot 1.3.1 (retains the 1.0.1 bootstrap fix)

## Why the reported FileNotFoundError happened

The original VPS Docker Compose deployment mounts `./config.json` into `/app/config.json`. Its Dockerfile intentionally does **not** bake your private JSON/secrets into the image. A Railway Dockerfile deployment does not automatically provide that Compose bind mount. The old image required `/app/config.json`, so it exited before listening; restarting could not fix the missing file.

Version **1.0.1** supports Railway/environment-only startup:

- `config.example.json`, a public secret-free template, is copied into the image.
- With no mounted default `config.json`, the loader uses the public defaults plus service Variables.
- Existing external `config.json` deployments still work; explicit `CONFIG_PATH` stays strict.
- Service Variables override matching JSON fields.
- `PUBLIC_BASE_URL`, existing `PUBLIC_DOMAIN`, or Railway's `RAILWAY_PUBLIC_DOMAIN` can provide the HTTPS login origin.
- Web server listens on `0.0.0.0:$PORT`, defaulting to 8080. Docker healthchecks also respect the port variable.
- `healthcheck.railway.app` is an allowed host. Unknown hosts remain blocked.
- HTTP liveness starts before slow account loading/singleton handover. No Telegram user session/polling starts without the Mongo singleton lease; login APIs return 503 until the service is fully ready.
- Missing settings, malformed JSON, invalid Fernet keys, Mongo startup and bot-auth failures get authored, secret-free diagnostic messages instead of an unexplained filename error.

## Update your existing repository

1. Extract the updated ZIP and replace the project files in your repository. **At minimum update `Dockerfile`, `.dockerignore`, `config.example.json` and the `app/` and `scripts/` folders.** Replacing the whole source project is safest if you have no custom code changes.
2. Do **not** upload real `.env`, OTPs, passwords, sessions, screenshots of secrets, or a `config.json` containing literal credentials. Keep existing custom non-secret configuration/limits separately before replacing files. Existing Mongo data is not deleted by this code update.
3. The Railway service's Root Directory must be the directory containing `Dockerfile`, `app/`, `assets/`, `scripts/` and `config.example.json`. If you committed the outer ZIP folder, set it to `/telepilot`; if those files are at the repository root, leave the default root.
4. Use the Dockerfile builder/detection. Start command: **`python -m app`** (the Dockerfile already provides it).
5. Keep **one replica and one region** for this bot/database. Do not start a second service against the same bot/session database.
6. Apply Variables below, then trigger a **new rebuild/deployment**, not only a restart of the old image. A rebuild is required for changed Dockerfile/COPY sources.

## Required application Variables

Values below are placeholders. Enter your own privately in Railway; never paste actual secrets into a support chat.

| Variable | Set to |
|---|---|
| `TELEGRAM_API_ID` | Your numeric API ID from my.telegram.org |
| `TELEGRAM_API_HASH` | Your 32-character API hash |
| `BOT_TOKEN` | Current valid BotFather bot token |
| `MONGO_URI` | Your working external Mongo/Atlas URI, with encoded credentials |
| `OWNER_IDS` | **Your personal Telegram numeric user ID**, e.g. `111111111`; multiple owners: comma-separated or `[111111111,222222222]` |
| `SESSION_ENCRYPTION_KEY` | Your full original valid Fernet key, or a securely generated key for an empty/new installation |

`OWNER_ID` is also accepted for a single owner. `API_ID`/`API_HASH` aliases are supported. **API ID, bot ID and GitHub username are not your owner user ID.** If your old external config already has real `owner_ids`, use those same IDs in this service variable. A default owner is never invented.

Optional/recommended:

```dotenv
PORT=8080
LOGIN_MODE=chat
ADMIN_USERNAME=YourActualAdminUsername
UI_STYLE=smallcaps
UI_EDIT_PANELS=true
UI_CLEAN_INPUTS=true
PUBLIC_BASE_URL=https://YOUR_GENERATED_RAILWAY_DOMAIN
MONGO_DATABASE=telepilot
# Existing PUBLIC_DOMAIN also works; you do not need both public URL variables.
# PUBLIC_DOMAIN=YOUR_GENERATED_RAILWAY_DOMAIN
# CALLS_ENABLED=false   # channel-only mode if native calls are not supported by your host
# LOG_DIRECTORY=        # empty disables optional file logs; sanitized stdout/Mongo audit remain
```

If explicitly setting `PORT=8080`, set the public domain's **Target Port to 8080** in Networking. Otherwise leave Railway's injected PORT in use and ensure any explicit target port matches it. The HTTPS origin must be the app service's real generated domain, not a separate database service domain. For URLs include `https://` and no path/query/fragment; `PUBLIC_DOMAIN` can be a bare hostname.

Remove `CONFIG_PATH` from Railway unless you deliberately provide a file at that exact path. An explicitly configured missing path is still an error by design. `MONGO_ROOT_PASSWORD`, `MONGO_APP_PASSWORD`, `TLS_EMAIL` and Caddy are not needed by the app-only external-Mongo Railway setup. They belong to the bundled local VPS Compose stack. Railway handles the generated-domain HTTPS edge; do not run the VPS Caddy Compose service inside this app container.

Do not run interactive `scripts/setup.py` as your Railway Start Command; it is for local/VPS preparation, not unattended container boot.

## Fernet key and screenshot security

The supplied screenshot exposed a bot token, database password and session-encryption key. Precaution:

- Revoke/regenerate the bot token using **@BotFather** and update `BOT_TOKEN`.
- Rotate the MongoDB user password and update the full `MONGO_URI`. Database URI credentials must be URL-encoded where necessary.
- If accounts were stored, assume access to Mongo plus its decryption key could expose their Telegram sessions. Revoke affected devices in Telegram **Settings → Devices**, and explicitly re-authenticate authorized accounts as needed.
- **Do not blindly replace an encryption key on an existing database.** Old sessions need the original key or a proper migration/re-authentication plan. Merely rotating encryption does not invalidate a session already copied by an attacker.

A Fernet key generated from 32 random bytes is **44 URL-safe Base64 characters and ends in `=`**. Do not crop that final character, use a 43-character random password instead, or paste placeholder text. The loader rejects invalid keys and does not silently generate/replace one at boot.

For a new/empty installation, generate privately on your machine:

```bash
python3 scripts/generate_key.py
# Standard-library-only equivalent:
python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Copy the complete output into the private service variable, save a private backup, and do not post it in chat. These commands do not access Telegram or Mongo.

## Healthchecks and rollout settings

Use service Settings → Deploy:

- **Healthcheck Path:** `/health/live`
- **Healthcheck Timeout:** 300 seconds
- **Restart policy:** On Failure (for example max 10 retries)
- **Replicas:** 1, one region

Why liveness here? Railway keeps the previous deployment active until the new endpoint passes. A new process cannot start the same Telegram sessions while the old singleton holds the lease. The new liveness endpoint becomes available while it waits, permitting the platform to retire the old process; after old shutdown/lease expiry, the new process obtains leadership and becomes operational. The APIs stay locked during that handover. This deliberately allows a short bot/startup interruption; it does **not** claim continuous RTC calls or zero-downtime bot polling.

**`/health/live` only means the process's HTTP server is alive.** After deployment, open **`https://YOUR_DOMAIN/health/ready`** and verify `{"status":"ready"}`. Readiness checks Mongo and critical tasks. Use readiness for your operational alerts, not liveness alone. If another instance is still alive, startup waits up to the configured lease timeout and then exits with an explicit error instead of sharing sessions.

Railway currently uses deploy-time, not continuous, platform healthchecks. For provider behavior and Host/PORT requirements, see the official [healthcheck documentation](https://docs.railway.com/deployments/healthchecks). This project does not ship a new `railway.json`/`railway.toml` dependency: current Railway documentation deprecates the old Config-as-Code format, so configure these service settings in the dashboard or your supported Infrastructure-as-Code workflow.

## Database/network/logs

- Atlas URI is external; no Compose `mongo` hostname is available in this app-only deployment.
- Give the DB user the required read/write/index permissions in the configured database. Ensure DNS, TLS and the Atlas network allowlist permit this service. Avoid a blanket public database allowlist when stable egress/private networking is available; otherwise evaluate the exposure and secure credentials appropriately.
- Accounts/plans/jobs remain in Mongo. No session files need a Railway filesystem volume. Optional file logs are ephemeral without a volume; stdout and Mongo audit/outbox remain available. File logging errors now degrade to sanitized console logs rather than crashing startup. A mounted log volume must be writable by the container UID 10001.
- Use a persistent long-running service, not a cron/sleeping service. Cold starts interrupt calls and polling. The new ZIP does not guarantee Railway's outbound WebRTC/UDP compatibility; validate a real owned test call before enabling/selling call automation.
- Avoid multiple services/replicas sharing the same bot/session database. A separate bot needs a deliberate separate database/credentials; do not casually change the database name of an existing bot and then mistake missing old data for deletion.

## Expected logs after the fix

No credentials are printed. Typical sequence:

```text
HTTP listener ready; port=8080 (automation remains locked until startup completes)
[optional] Waiting for previous runtime to release singleton lease; no Telegram account clients have started
TelePilot started; bot_id=...
```

Useful next errors (if configuration/access still needs attention):

| Message | Action |
|---|---|
| `Required settings missing: OWNER_IDS` | Add your personal numeric user ID |
| `Required environment variable missing: ...` | Fill that named service variable |
| `CONFIG_PATH file is missing` | Remove stale CONFIG_PATH or actually mount/provide the file |
| `SESSION_ENCRYPTION_KEY ... 44-character Fernet key` | Restore the complete original key, or generate a new one only for an empty/new installation |
| `MongoDB initialization failed (...)` | Check URI/password/user rights/DNS/TLS/allowlist |
| `Telegram bot startup failed (...)` | Check rotated/current token and Telegram network access |
| `Another runtime still holds ... lease` | Stop duplicate/old instance; allow up to 90 seconds after abrupt termination |
| URL 502 despite running process | Check correct generated app domain and target port equals PORT |
| URL 400 | Check public-domain setting/Host; use the exact HTTPS origin |
| Login API 503 during boot | Wait for `/health/ready`; request a fresh bot login link if old challenge expired/restarted |

No real user secrets or account sessions are in the updated archive. Code fixes were tested locally, including a Docker-COPY filesystem mirror with no `config.json` and an actual HTTP listener; your Railway project was **not** accessed/redeployed here.
