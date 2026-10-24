# TelePilot — Premium Telegram account manager

> **1.5.0 — 200-account VPS release:** validated capacity for **200 saved accounts**, with Docker profiles for an **8-vCPU / 64-GB VPS**, persistent data, larger process/file budgets, restart-at-boot guidance and an optional unhealthy-container watchdog. Read [VPS_200.md](docs/VPS_200.md) for fresh installation versus safe upgrade/migration. Keep one app worker and the original encryption key, database, private config and volumes.


**Session-safety protections retained:** a confirmed duplicated authorization pauses managed account traffic, including SDK-internal failures. Read [SESSION_SAFETY.md](docs/SESSION_SAFETY.md) before another login after a conflict. Stop other copies and complete owner review; adding RAM, restoring ciphertext or restarting cannot revive a Telegram-invalidated key. No permanent-uptime or 200-concurrent-RTC guarantee is claimed.

## 200-account Docker quick start

**Fresh installation only:** `python3 scripts/setup.py --profile vps200`, then use the single command it prints. For bundled Mongo:

```sh
docker compose -f compose.yaml -f compose.vps200.yaml up -d --build
```

For your **existing external Mongo**, use only `compose.vps200.external.yaml`. For an **upgrade**, do not run setup or unzip over private config: preserve the original project identity/key/database/volumes and follow [the migration guide](docs/VPS_200.md). These profiles deliberately default to 200 despite an old `MAX_POOL_ACCOUNTS=100`; customer allowances do not silently expand. Base Compose examples below are generic/smaller-host instructions, not the 200-native-instance resource envelope.

**Python + Telethon + aiogram + PyTgCalls/NTgCalls + MongoDB. Docker-ready source project.**

**Retained from 1.4.0: independent unlimited Premium quotas.** `/premium USER_ID DAYS PLAN unlimited unlimited set` supports either quota independently, current/future eligible pool additions and preserved short renewals. Paid unlimited access does not bypass host ceilings, Telegram waits, feature tiers or permanent targets. See [UNLIMITED_PREMIUM.md](docs/UNLIMITED_PREMIUM.md).

**Retained from 1.3.1: direct public joins + visible, owner-controlled start photos.** Public targets use their current @username and native direct-join RPC; private targets retain approval requests. An enabled start photo is sent anew with each /start, above the editable home panel, instead of editing an old photo in history. Owner → start photo now has set/preview/on/off/default controls. Task errors and audit IDs are copyable. Read [docs/PUBLIC_JOINS_PHOTOS.md](docs/PUBLIC_JOINS_PHOTOS.md).

**Required subscriptions and fair automatic calls from 1.3.0 are retained.** Explicit `/start` now brings a fresh panel into view; it is delivered before command cleanup and cannot be swallowed by an optional image failure. Buttons still edit the existing panel. Owners manage required channels; admins view them. Customers can opt in to periodic call detection on saved channels, sharing healthy free accounts equally within paid caps, with manual-task priority. See [docs/FORCE_SUBSCRIBE.md](docs/FORCE_SUBSCRIBE.md) and [docs/AUTO_CALLS.md](docs/AUTO_CALLS.md).

**Feature plans and permanent channel limits from 1.2.0 are retained.** Assign **channels only**, **calls only** or **both**, with a chosen channel/group slot limit, account limit and duration. Users see only included automation buttons, and server checks also block old buttons/tasks. Saved channels remain locked; only an owner/admin can make an audited correction. Existing Premium access is preserved on upgrade. Read [docs/SUBSCRIPTIONS.md](docs/SUBSCRIPTIONS.md).

**Health and contact:** the staff health button now runs a bounded background check with progress/results, not a blocking generic statistics refresh. Set `ADMIN_USERNAME=YourActualUsername` in VPS `.env` or Railway Variables for the new contact admin button. See [docs/HEALTH.md](docs/HEALTH.md).

**Clean editable panels from 1.1.0 are retained.** Buttons reuse one main text panel; `/start` reuses the supplied image in a separate banner. English menus are shorter, inputs are cleaned best effort, and commands/links/copyable examples keep their exact values. Real alerts and transient sign-in QR photos remain intentional exceptions. Read [docs/CLEAN_UI.md](docs/CLEAN_UI.md).

**Working private-chat sign-in from 1.0.2 is retained.** Staff use **manage bot → add account** or `/signin` → ownership/privacy consent → phone → OTP → optional 2FA, or the in-chat QR alternative. No browser approval/domain is needed for chat sign-in. Bot chats are **not end-to-end encrypted**; message/QR deletion is best effort and Telegram may expire posted OTPs. Read [docs/CHAT_SIGNIN.md](docs/CHAT_SIGNIN.md). A reproduced SDK DC-migration/no-follow-up `ValueError` has also been fixed.

**Railway support retained: version 1.0.1 fixed the missing `/app/config.json` crash.** For Railway, read [docs/RAILWAY.md](docs/RAILWAY.md): use service Variables (including your personal `OWNER_IDS`), not the VPS bind-mount setup. The image includes only public defaults, supports `PORT`, and checks readiness before accepting login credentials. The VPS instructions below still apply to Docker Compose.


This project includes owner/admin roles, manual Premium plans, encrypted account sessions, authorized channel requests, group voice/video-chat joins, scheduling and health checks. The original supplied `/start` image is included unchanged.

> **Verification boundary:** automated source and built-image checks use real disposable Mongo and loopback HTTP, with controlled Telegram/Bot API/RTC outcomes. See [TEST_REPORT.md](TEST_REPORT.md) for exact final evidence. No real account OTP/QR/RTC load test, user-VPS deployment, no-ban result or permanent uptime is claimed. Complete the authorized host acceptance checklist before production use.

## Supported scope

- **Owners**: explicit IDs in external `config.json` or `OWNER_IDS`; can add/remove admins, manage all accounts/plans/jobs, set/reset `/start` photo, toggle maintenance, view audit and check compatibility.
- **Admins**: grant/revoke Premium, manage **only accounts they added**, moderate jobs and view users/statistics. Cannot promote admins, change owners/banner/maintenance, view audit or export sessions.
- **Free/expired users**: help, plan/contact information and their saved channel/task history. No new channel registration or automation; old saved channels remain locked.
- **Premium users**: required membership plus only the assigned channels/calls/both features, within their locked channel/group slots and account cap. Included tasks support immediate/scheduled execution, progress and cancellation.
- One healthy/free account per concurrent job reservation; one active call per reserved account. Requested count cannot exceed the current healthy pool or plan cap. Capacity shortages queue rather than quietly giving fewer accounts.
- UTC-backed durable scheduling; display/input timezone defaults to **Asia/Kolkata**.
- Premium grants/modifications include actor ID/role, target ID, duration, expiry and account cap in owner alerts. Users receive activation/expiry/revocation notifications through a restart-safe outbox.
- Default staff-only private-chat phone → OTP → optional 2FA, ownership/full-session consent, fresh nonce, 10-minute timeout, best-effort input deletion and QR alternative. **Bot chats are not E2E; Telegram may retain contents/invalidate posted OTPs.** Application logs/Mongo/FSM do not store OTPs/passwords. Sessions are Fernet-encrypted. Legacy browser mode is explicit opt-in only.
- Panel mutations synchronize immediately; periodic account health and the new non-blocking staff report detect/review account states. Enable, disable, re-authenticate and remove controls are included. Busy/cooldown accounts are skipped by the manual probe.
- Durable editable text panels, default smallcaps messages/buttons, HTML `<blockquote>` formatting, button-driven forms, and your supplied fallback `/start` image bundled as `assets/start.png`:
  `https://i.ibb.co/1Nx1jMn/IMG-20261005-021725.png`
- Rotating sanitized JSON logs, Mongo audit, optional Telegram logging destination, HTTP health checks and singleton runtime lease.

### Deliberate limitations / safety constraints

1. **Calls are group/channel voice-video chats and livestream-style group calls**, using public group links or bot-managed private invites, with optional `?videochat=...`, legacy `?voicechat=...`, or `?livestream=...` speaker tokens. A bot-managed group invite can also identify the group's currently active call.
2. **`https://t.me/call/<slug>` E2E conference links and one-to-one calls are not implemented.** They are rejected explicitly, not reported as successful. Link-format reference: [1](https://core.telegram.org/api/links). “Video chat” participation here means joining its group call; no camera stream, microphone publishing, simulated speaking or recording.
3. Calls stop when the original call ends/changes, Premium expires/is revoked, control is lost, the job is cancelled or the selected safety duration is reached. Default maximum: **360 minutes**, configurable up to 1440. Jobs do not create/start calls.
4. Bounded rejoin applies to network-only disconnections in the **same** call. Explicit remote removal/self-left updates are treated conservatively as stop signals. A retry also requires that Telegram still lists the account in that same call; no kick/ban bypass.
5. The requester **and the bot must be admins** in every target, and the bot needs **Invite Users** permission. For private targets, only bot-managed private links are accepted because arbitrary private invite ownership cannot be proved before joining. A managed channel-request link asks target admins for approval; a public open-channel link may join immediately. **Requests are not approvals.** Accounts with pending requests cannot join that group's call until approved.
6. Telegram `FloodWait` is persisted and honored. Pacing, per-account daily join caps and per-user quotas are safety controls, **not anti-detection/ban-evasion methods**. No phone farms, proxies for evasion or identity camouflage are provided.
7. Payments are **manual**. No payment gateway or automatic payment verification is included.
8. Compatibility checks automatically validate adapter signatures and check PyPI versions. They **alert**, not install untested code or magically fix Telegram API changes.
9. Run **one replica** per bot/database. Multiple replicas sharing sessions can revoke an auth key. This is not a horizontally distributed RTC platform.

## 1. Requirements

- A Linux VPS with Docker Engine + Docker Compose v2 and **Python 3** for the setup generator.
- Linux x86_64 is the preparation/test platform. Other native-wheel/CPU combinations need a separate build test.
- A Telegram bot token from **@BotFather**; API ID/hash from `https://my.telegram.org` → API development tools.
- Your **numeric Telegram user ID** (not a username). All owner IDs must be positive user IDs.
- **No domain is needed for private-chat sign-in.** HTTPS is needed only for optional legacy browser mode/public HTTPS monitoring. Bundled Caddy can supply TLS; ports **80/443 TCP** must then be reachable.
- MongoDB: bundled authenticated Mongo 8.0, or an external MongoDB URI/Atlas connection.
- Outbound network access to Telegram, DNS/PyPI and Telegram's negotiated WebRTC UDP/TCP endpoints. HTTP-only/serverless hosting may not support real calls. Do not promise a capacity figure without testing your actual VPS/call traffic.

## 2. Generate configuration

Unzip and enter the project directory:

```bash
cd telepilot
python3 scripts/setup.py
```

The generator asks for credentials **locally** (hidden inputs for secrets), owner IDs, domain, TLS email and optional support username/external Mongo URI. It creates:

- `config.json` — external app configuration; secret fields reference `${ENV_VARIABLE}`.
- `.env` — private credentials + unique encryption/Mongo passwords, mode `0600`.

**Never share/commit `.env`, post OTP/2FA in a support chat/untrusted bot, or replace a production encryption key without a migration/backup.** Only an explicitly consented current private staff dialog in your trusted self-hosted bot accepts credentials; it remains less private than local/trusted HTTPS entry. The supplied `config.json` has an empty owner list and unset environment references intentionally: it fails closed until configured. The real secrets are **not** in this ZIP.

Required config keys: `api_id`, `api_hash`, `bot_token`, `mongo_uri`, `owner_ids`, `session_encryption_key`. Cloud/environment-only deployment can supply their corresponding validated service Variables; explicit environment values override file fields. With no default JSON file the loader uses public template/class defaults, but never invents credentials/owners. An explicitly configured `CONFIG_PATH` must exist. Direct JSON values also work; if you use them, protect the file and ensure the container's non-root UID can read it. The generated environment-reference approach avoids world-readable actual credentials in a bind-mounted JSON.

Useful optional keys:

| Key | Meaning |
|---|---|
| `login_mode` | `chat` default or explicit legacy `browser`; LOGIN_MODE env overrides |
| `ui_style` | `smallcaps` default or `plain` for accessibility; UI_STYLE env overrides |
| `ui_edit_panels` | `true` default: edit the reusable panel; UI_EDIT_PANELS env overrides |
| `ui_clean_inputs` | `true` default: best-effort command/form cleanup; login input deletion remains regardless |
| `public_base_url` | Exact HTTPS origin; needed only for browser mode, also controls public HTTP Host |
| `logging_chat_id` | Log channel/group ID; add the bot with posting access |
| `admin_username` | Contact admin username; ADMIN_USERNAME env override, passed by VPS Compose |
| `support_username` | Legacy contact fallback; no `@` needed |
| `timezone` | IANA timezone; default `Asia/Kolkata` |
| `calls_enabled` | Set `false` for channel-only hosts |
| `limits` | Pool, quotas, pacing, call duration, rejoin and health limits |
| `audit_retention_days` | Audit retention; default 90 days |

Do not change `mongo_database` from `telepilot` with the bundled bootstrap unless you also adjust the Mongo user/database initialization. Changing initialization credentials does not change an already initialized Mongo volume.

## 3. Deploy (chat mode needs no login website)

Without a public website, use:

```bash
docker compose up -d --build
```

Set `LOGIN_MODE=chat` in .env/Railway. Keep the existing SESSION_ENCRYPTION_KEY and database on update. Optional public HTTPS monitoring or legacy browser mode can use the following Caddy deployment.

### Optional automatic HTTPS

Create the domain's DNS A/AAAA record first. Then:

```bash
docker compose -f compose.yaml -f compose.https.yaml up -d --build
docker compose ps
docker compose logs --tail=100 app caddy
```

The app listens on `0.0.0.0:8080` **inside** Docker by default (or the supplied `PORT`); its host port is bound to **127.0.0.1** only. Caddy proxies the public HTTPS domain. Mongo has **no published port**. API secrets are excluded from the build context, and the app runs non-root with a read-only root filesystem.

If you have an existing trusted HTTPS reverse proxy, use `docker compose up -d --build`, proxy to `http://127.0.0.1:8080` and set the exact public HTTPS origin in `config.json`. Do **not** expose the backend directly: forwarded proxy headers are trusted in this topology.

```bash
# Read-only host check inside the EXISTING container (run /health first):
docker compose exec -T app python scripts/live_check.py

# Local readiness (after startup / account loading):
curl -f http://127.0.0.1:8080/health/ready
```

After a duplicated-key incident, first run `python scripts/live_check.py --scope safety` in the existing container and follow [SESSION_SAFETY.md](docs/SESSION_SAFETY.md). Do not start a call or mass-reauthenticate merely to obtain a green report.

The reader can return exit **2 (incomplete)** on a fresh installation, with no current health proof or no managed call running. That is not a claimed RTC pass and does not require repeated login. See [HOST_VERIFICATION.md](docs/HOST_VERIFICATION.md) for the owned-call procedure and exact exit-code meaning.

Startup may take longer when many saved accounts must reconnect. `docker compose down` retains data volumes. **Do not use `down -v`** unless you intend to delete the database/certificates/log volume.

More deployment, Atlas, backup and troubleshooting instructions: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## 4. Initial bot setup

1. Start your bot as an owner with `/start` → **manage bot**.
2. Add admins with the button or `/addadmin USER_ID`. Admins must start the bot themselves.
3. **add account** or `/signin` → read/accept ownership/privacy warning → **Phone → OTP** → own international phone → latest code → optional exact 2FA. Or **QR alternative**, approve using your official Telegram app, then **Check approval**. /cancel stops a pending dialog. If Telegram expires a posted OTP, do not disguise it; use QR/trusted official flow.
4. View **Accounts**. Only `healthy`/enabled/free/non-cooldown accounts are assignable.
5. Add the bot as admin in a test supergroup/channel with **Invite Users** permission. Send `/chatid` there to get its ID if private. Register it from **my channels**.
6. A customer starts the bot. After your manual payment confirmation, use **give premium** in manage bot, or:

```text
/premium 123456789 30 calls 1 5 set
/premium 123456789 30 channels 2 3 set
/premium 123456789 15 both 3 5 extend
/revoke 123456789
```

`channels` = channel tasks only, `calls` = call tasks only, `both` = both. The number after it is channel/group slots; the next number is accounts per task. Saved channels stay locked, even after expiry; use staff **channel corrections** for a deliberate audited replacement. `set` replaces expiry with now + days; `extend` adds days to the later of now/current expiry. Duration: 1–365 days. Owner/user notices are durably queued. The target must have started/unblocked the bot; blocked-user DMs can fail and are recorded in audit/outbox.

7. Customer selects channel requests or voice/video chat → verified target → managed link or matching public link → account count → call duration if applicable → now/schedule → confirms authorized use.
8. Check **my tasks** for results/cancellation. Staff can moderate from **all tasks**.

## 5. Commands

| Audience | Commands |
|---|---|
| Everyone (private chat) | `/start`, `/panel`, `/plan`, `/targets`, `/jobs`, `/id`, `/help`, `/cancel` |
| Target group/channel | `/chatid` only; no sensitive admin panel in groups |
| Owner/admin | `/signin`, `/login`, `/premium ID DAYS channels\|calls\|both CHANNELS [ACCOUNTS] [set\|extend]`, `/premiumhelp`, `/revoke ID`, `/users`, `/accounts`, `/stats`, `/health` |
| Owner only | `/addadmin ID`, `/deladmin ID`, `/setphoto`, `/resetphoto`, `/maintenance on\|off`, `/audit`, `/updates` |

`CHANNELS` and `ACCOUNTS` each accept a positive supported number or `unlimited`; omitted renewal quotas preserve their finite/unlimited mode. See the unlimited guide for current/future account behavior and operational ceilings.

`/setphoto` asks for an actual Telegram **photo**, stores its Telegram file ID and never downloads arbitrary user URLs. `/resetphoto` restores the provided bundled fallback. Owner IDs are changed only in private `config.json` or explicit `OWNER_IDS`, followed by container recreation/redeployment.

## 6. Tests and release checks

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/check_compat.py
ruff check app scripts tests
pytest -q  # pure unit tests run; Mongo integration tests skip without TEST_MONGO_URI

# Use a disposable Mongo instance, never a production database:
TEST_MONGO_URI=mongodb://127.0.0.1:27018 pytest -q
```

Tests create unique temporary databases and delete only those databases. Telegram clients/Bot API/RTC outcomes are mocked; they are not live account/call tests. See [TEST_REPORT.md](TEST_REPORT.md) for the tested scope and [docs/LIVE_ACCEPTANCE.md](docs/LIVE_ACCEPTANCE.md) before production use. A CI workflow also tests against Mongo and builds the Docker image when run on a Docker-enabled runner.

Security/threat model: [docs/SECURITY.md](docs/SECURITY.md). Architecture/state transitions: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Current hardening findings and limits: [docs/AUDIT.md](docs/AUDIT.md).

**1.5.0 verification:** the full source suite passed **706 tests**, retaining all prior 641 and adding **65 capacity/VPS/watchdog regressions**. Built-image and separate restricted non-root HTTP/Mongo/host-reader results are recorded in [TEST_REPORT.md](TEST_REPORT.md), with their exact scope and limits. Original signup, unlimited quotas, role/target protections, session safety, UI and image are retained.

For your selected host-run verification, use the existing app container: `docker compose exec -T app python scripts/live_check.py`. First run `/health` in the bot during one owned managed call. Return only the sanitized JSON and manual outcomes from [HOST_VERIFICATION.md](docs/HOST_VERIFICATION.md); never send OTPs, passwords, keys or session strings.

## Operational defaults

200 maximum saved pool accounts by default (old private JSON can still say 20 unless overridden), 5 accounts/default finite Premium plan, 10 jobs/user/UTC day, 5 pending jobs/user, 2 parallel jobs, 2-second global MTProto gap, 45-second/account join gap, 20 join attempts/account/UTC day, 360-minute call cap, 3 rejoin attempts, 30-second call probes, 5-minute full account checks, wakeable recovery ticks up to about every 15 seconds with persisted 60–900-second backoff, daily compatibility checks. These defaults are conservative **application limits**, not promises about Telegram's limits.

Telegram may restrict an account even when these limits are honored. Use only authorized accounts/targets, do not spam or artificially misrepresent participants, and comply with Telegram's terms.

## License

Project source: MIT. See `CHANGELOG.md` for public joins/photo/diagnostics 1.3.1, start/subscriptions/auto-sharing 1.3.0, subscriptions/health 1.2.0, clean UI/hardening 1.1.0, Railway 1.0.1 and private-chat/SDK 1.0.2 fixes. Dependencies keep their own licenses, including LGPL-family licensing for call libraries. See `THIRD_PARTY.md`.

## New panels (1.3.0)

- **Manage bot → required subscriptions:** owners add/remove/view; admins view only. Both staff roles are exempt. /forcesub, /forcesubadd @Channel and /forcesubremove CHAT_ID use reviewed forms.
- **Automatic calls:** calls/both customers enable one/all saved channels. /auto shows status; /autostop disables their opt-in, including after expiry or membership loss. New saved channels remain off until enabled.
- **Auto overview:** staff view enabled targets, connected counts and worker diagnostics. In the 12 healthy/free accounts + 4 active auto channels example, each gets 3. When a call ends, remaining shares rebalance; a plan account cap may leave unpurchased capacity idle.

Default new limits: 10 required subscriptions, 30 auto targets globally, 3 concurrent auto connection setups, 30s scan pause, 35s per probe, 90s detection budget, 180s stale grace, 10 new auto episodes/user/UTC day. These are independent of manual job limits but share the account pool, RPC/join safety controls and permanent customer slots. No live-call/approval/no-ban guarantee.

Existing installations: keep the original private .env/config.json, key/database/volumes, replace source without overwriting them, and rebuild the app. New config fields have defaults when absent. Auto is opt-in/off for old targets; the force-subscribe collection starts empty. Never run old bot code alongside this singleton or roll back to code lacking the chosen feature/lock/membership enforcement.

## Public joins / photo controls (1.3.1)

Public saved targets use direct join; private targets use managed request invites. Telegram approval/bans/FloodWait are still honored—request_sent never means joined. Older queued join jobs resolve the current saved target on execution. Look in task details for protected error types, not only the word partial.

Owner **manage bot → start photo**: set, preview, enable/disable, restore default. /startphoto, /startphoto on, /startphoto off, /setphoto and /resetphoto are equivalent commands. The stored Mongo visibility preference survives restart; start_photo_enabled / START_PHOTO_ENABLED is the initial default. Disabling does not erase the selected photo or login QR functionality. Every enabled /start sends a new visible photo; old pair cleanup is best effort after acknowledgement.

AuthKeyUnregisteredError means the stored Telegram session needs sign-in again; a release cannot resurrect it. Connection/timeouts are cooled down/offline instead of silently reused as healthy. Audit details are code-formatted so IDs/error classes are not changed by smallcaps. See PUBLIC_JOINS_PHOTOS.md and TEST_REPORT.md for source findings and honest live-testing limits.

## Upgrade existing 20/100-account capacity

For the selected VPS use [VPS_200.md](docs/VPS_200.md) and its 200-account profile, preserving the original project identity, private files/key/database/volumes. For ordinary direct Docker/service env, `MAX_POOL_ACCOUNTS=200` overrides a retained old JSON cap; a blank override preserves it. This raises saved-account capacity, not existing finite paid quotas or Telegram rate limits, and is not a 200-live-call benchmark. See [ACCOUNT_CAPACITY.md](docs/ACCOUNT_CAPACITY.md).
