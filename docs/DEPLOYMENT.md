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

> **1.1.0:** editable smallcaps panels are the default. On a VPS, set UI keys in external `config.json`; on Railway, use UI_* service Variables. Rebuild updated source and keep the original encryption key/data volumes. See [CLEAN_UI.md](CLEAN_UI.md).

> **1.0.2:** default private-chat LOGIN_MODE=chat supports phone/OTP/2FA + QR without a login website. Run docker compose up -d --build without HTTPS override if bot-only. The HTTPS/portal instructions below apply to optional monitoring or browser mode. See [CHAT_SIGNIN.md](CHAT_SIGNIN.md).

# Deployment, backup and troubleshooting

**Railway:** use [RAILWAY.md](RAILWAY.md) for the 1.0.1 environment-only deployment fix. The Compose bind mounts, local Mongo bootstrap and Caddy setup on this page are for VPS deployments, not the Railway app-only container.

## Recommended topology

```text
Telegram customer / owner
  ├─ Bot API long polling ──────────────┐
  └─ HTTPS sign-in domain → Caddy ──────┤ TelePilot single Python process
                                       ├─ MongoDB (authenticated, private)
                                       ├─ Telethon account sessions (RAM)
                                       └─ NTgCalls → Telegram RTC endpoints
```

The same event loop owns Bot API handlers, login challenges, account clients, scheduling and health checks. Never run a separate worker/second Uvicorn worker against these same sessions. The runtime takes a 90-second Mongo lease renewed every 20 seconds and stops on lost leadership. A new process can expose locked HTTP liveness and wait for controlled lease handover before starting any Telegram session clients. After an abrupt failure, wait for the previous lease to expire; do not manually delete a lease unless you have verified the old process is dead.

### VPS installation example (Ubuntu/Debian)

Install Docker Engine/Compose using your distribution's official Docker instructions. Install `python3` and `unzip`, extract this project, and run its standard-library-only setup script. This project intentionally does not execute a root-level remote install script.

DNS must resolve the sign-in domain to this VPS. If port 80/443 is already occupied, use your existing proxy rather than starting a competing Caddy service. Allow outbound Telegram connectivity and negotiated RTC traffic. No fixed inbound WebRTC port mapping is claimed; test your provider's NAT/firewall. At least a small VPS with a few accounts should be validated first; video-chat traffic, participant count and native RTC memory can substantially affect resources.

Use the combined deployment command from README. HTTPS origin must match exactly; `https://www...` and `https://...` are distinct origins. Avoid a path prefix such as `/telepilot`: the portal uses root-relative `/api/login` routes.

### Existing HTTPS proxy

Use `docker compose up -d --build`. Proxy HTTPS to host `127.0.0.1:8080`. Preserve Host and Origin; forward X-Forwarded-Proto/For through a proxy you trust. Backend trusts forwarded headers because it is not publicly published. Do not bind its host port to `0.0.0.0` without adding an appropriate trusted-proxy configuration and network isolation.

### External MongoDB / Atlas

Set `MONGO_URI` in `.env` to your encoded URI. Prefer an application-scoped `readWrite` user in database `telepilot` with TLS and a narrow network/IP allowlist. Configure `mongo_database` consistently. For Mongo SRV records, DNS must work.

Default Compose still starts the local Mongo service even with an external URI. For a cloud-only deployment, build/run the app directly:

```bash
docker build -t telepilot:1.0 .
docker volume create telepilot_app_data
docker run -d --name telepilot --restart unless-stopped --init \
  --env-file .env --read-only --tmpfs /tmp:rw,size=64m,mode=1777 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  -v "$PWD/config.json:/app/config.json:ro" \
  -v telepilot_app_data:/app/data \
  -p 127.0.0.1:8080:8080 telepilot:1.0
```

Attach an existing HTTPS proxy. This convenience command passes every `.env` variable to the app container; a dedicated env file containing only required application secrets is preferable for least privilege. With direct Docker, use `docker exec telepilot python scripts/live_check.py` and `docker logs telepilot` rather than Compose commands.

### Configuration and permissions

Setup writes JSON with environment references, readable by UID 10001. `.env` contains actual secrets and is owner-readable only. Docker Compose supplies just application secrets to the app (not the Mongo root password). If you manually embed secrets in JSON, mode/UID must permit non-root container reads without exposing secrets to unrelated host users.

Mongo init scripts run **only on a new volume**. Changing `.env` passwords afterward is not a database password rotation. Use Mongo user-management commands and rotate both URI/secret together. Do not delete a production volume just to fix an authentication mistake.

## Backup

```bash
./scripts/backup.sh
```

Creates a private gzip archive under `backups/`. It contains user metadata, jobs, managed links and **encrypted** sessions. A database backup without the original `SESSION_ENCRYPTION_KEY` cannot restore those sessions. Store `.env`/that key in a separate encrypted password manager or offline backup, not next to publicly accessible database dumps. Backups may still reveal personal IDs/plan history and must be access-controlled.

Restore into a new or deliberately prepared `telepilot` database:

```bash
# Choose the actual archive; restoring can overwrite data. Stop app workers first.
docker compose stop app
cat backups/telepilot-YYYYMMDDTHHMMSSZ.archive.gz | \
  docker compose exec -T mongo sh -c \
  'mongorestore --quiet --username root --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --archive --gzip --nsInclude "telepilot.*"'
docker compose start app
```

This is a merge restore, not an unconditional destructive `--drop` restore. Validate in staging and restore the matching original encryption key. Restored obsolete active jobs can be resumed; use maintenance mode before restoring if you do not want that, then review/cancel them.

## Updating

Owner `/updates` and the daily checker compare installed/stable package versions and validate known adapter signatures. They do not hot-upgrade binaries. Review changelogs/API changes, update `requirements.in` and the full pinned `requirements.txt` together, run tests, build/test a staging image and then recreate the one production app service. Do not overwrite a known-working lock file with an untested blanket `pip install -U` inside the live container.

A restart disconnects RTC transport. Persisted call jobs may reconnect only if their original call ID is still active and their original end/plan deadline permits. Channel jobs skip recorded successful join/request results. External RPCs are not transactionally atomic with Mongo: an interruption after Telegram accepts an action but before its result is saved can result in a retry (usually an already-member/request-sent result). Do not claim exactly-once external delivery.

## Troubleshooting

| Symptom | Checks |
|---|---|
| Config error/startup exits | Run setup, check owner IDs/env names and real API credentials. Error output is sanitized. |
| Mongo auth failure | URI app password/database/authSource; existing-volume passwords are not re-initialized. |
| Another runtime lease | Stop duplicate processes; wait up to 90 seconds after abrupt termination. |
| HTTPS page unavailable | DNS, ports 80/443, Caddy logs, existing proxy/port conflicts. |
| Wrong Origin/Host / cookies missing | Exact HTTPS domain; no HTTP fallback, iframe embedding or path prefix. Open the page as a top-level browser tab. |
| Sign-in ticket expired/used | Generate a fresh link, approve matching code, complete within 10 minutes; do not share the link. |
| OTP not sent / unsupported verification | Telegram may require app delivery, SMS/email/payment or other flows not supported by this adapter. Use supported own accounts; don't retry through a FloodWait. |
| Account revoked/banned | View Accounts, re-authenticate eligible accounts or remove. A ban cannot be fixed by a reconnect loop. |
| Session cannot decrypt | Restore the original encryption key; otherwise re-authenticate. No reset can decrypt old ciphertext. |
| Invite not approved | Request was sent, not accepted. Target's admins must approve it. |
| Target permission error | Requester and bot need target admin status; bot must have Invite Users. |
| Private invite rejected | Use this bot's target-managed private link or an authorized public link. |
| No active voice chat | Start the actual group/channel call before the schedule/grace window; bot never starts one. |
| WebRTC connection fails | Supported native wheel/ABI, Telegram RTC endpoints, VPS UDP/NAT, Telegram permissions, live adapter compatibility. |
| Jobs remain queued | Maintenance, healthy account count, busy/cooldown accounts, plan cap, pending limits/start deadline. |
| Notifications fail | User must start/unblock bot; log-channel bot needs posting rights; inspect `/stats` and audit/outbox. |

The application exposes `/health/live` and `/health/ready` with minimal non-secret JSON. Ready checks Mongo and critical service-task liveness, not a guarantee that every external Telegram account/call is reachable.
