> **Confirmed duplicated keys: safety first.** Do **not** start another call/login to fill this checklist yet. Follow [SESSION_SAFETY.md](SESSION_SAFETY.md), stop conflicting copies, then run `docker compose exec -T app python scripts/live_check.py --scope safety` in the existing running app. This mode needs no user sign-in/call, never opens a user client, and returns blocked/incomplete while review is pending. A safety-scope pass is not full Telegram/RTC acceptance. After resolving the cause and owner-reviewed `/sessionguard` resume, replace invalidated keys through authorized sign-in and only then use the full procedure below.

> **New transport log follow-up:** deploy the 1.4.3 complete source before gathering fresh proof. [TRANSPORT_RECOVERY.md](TRANSPORT_RECOVERY.md) explains the reproduced SDK-future issue and what unknown buffer codes do—and do not—prove. Saved sessions must not be deleted/reset to run this check.

# Run live checks on your existing host — TelePilot 1.5.0

You chose to run the live checks on your own host. This guide and `scripts/live_check.py` are the remaining verification path. **The assistant has not accessed your production Telegram accounts or tested your real call.** Source/container tests are recorded separately in [../TEST_REPORT.md](../TEST_REPORT.md).

## Safety first

- Keep the **original private configuration, encryption key, Mongo database and volumes**. Unpack new source in a new directory; do not copy the ZIP's public starter `config.json` over production.
- Use one normal bot runtime/replica. Do not clone sessions, start a second worker, run `python -m app` in a second shell, run `docker compose run app`, regenerate keys or use `down -v` for this check.
- The host reader never constructs/decrypts a Telegram user session, requests OTP, joins/leaves calls, acquires a runtime lease, initializes indexes or writes Mongo. It checks loopback HTTP, reads bounded aggregate metadata and calls Bot API **getMe once**.
- Fresh user-session/call evidence comes from `/health` **inside the existing bot process**, using its current managed clients. It exports one bounded, sanitized settings record; no IDs, usernames, session strings, OTPs, passwords, URIs or keys enter the returned JSON.
- The in-process call sample only observes **one already managed call**. It checks native binding presence plus Telegram's non-left self participant in the same call. It never creates/joins a test call or publishes/records media. This is presence evidence, not an audio/video quality or uptime certification.
- Temporary cooldown, incomplete checks or absent call evidence are not instructions to repeatedly sign in. Known bans/revocations are not bypassed.

## 1. Apply the complete updated source

For an **existing Docker Compose deployment**, retain your working `.env`/external JSON and data volumes. Ensure the existing Mongo service is healthy, then rebuild/recreate only the app:

```sh
docker compose build app
docker compose up -d --no-deps app
docker compose ps
```

Let the previous runtime shut down gracefully and the singleton lease hand over. Do not run old/new replicas simultaneously. Existing saved accounts reconnect according to persisted waits; no new OTP is needed if Telegram still accepts their authorizations.

For Railway, rebuild/redeploy one service replica with the existing Variables/database/volumes. Use the **running service container shell** for commands below, not a laptop command that only downloads environment variables. No secret needs to be pasted into this conversation.

## 2. Check the actual bot

1. From your authorized owner private chat, send `/start`. Confirm the original photo (when enabled) and a visible editable home panel; navigation should edit the panel.
2. Open Accounts. Keep valid saved accounts; let legitimate cooldown/recovery deadlines expire. Do not reauthenticate a good session just to run diagnostics.
3. Send `/health` or use **manage → check health**. Wait for completion; refresh its existing panel if needed.
4. A skipped busy/disabled/cooldown account is not a new self-identity verification. A newly attached identity is counted only when the current transport actually completed matching identity validation. An old database `healthy` label is not accepted by the host reader as fresh proof.

The report is bound to the current singleton runtime, bot and code version. A private per-runtime keyed configuration attestation also detects a changed original key or critical API/runtime configuration before restart; its value is not returned by the reader. A stale or mismatched report is **incomplete**, not passed. Do not repair a mismatch by generating a new key: preserve/restore the original configuration and redeploy deliberately.

## 3. Verify one real owned call

1. Use only a group/channel you own or are explicitly authorized to manage, already saved through normal target validation, with the bot's required admin permissions.
2. Start its real Telegram voice/video chat from an authorized official client. The bot must not create a call automatically.
3. Through the existing bot's **manual call** workflow, select that target, **1 account**, an allowed safety duration and **now**. A typed **5** minutes is the minimum; use a longer allowed duration for a large slow roster, then cancel after verification. Keep mic/camera off. Do not opt every channel/account into automation merely to test one call.
4. Wait for the account to become active and independently confirm its participant presence in your official Telegram client.
5. While that managed call is still active, run `/health` again. A completed recent health run is reused for at least 30 seconds to avoid API spam; wait for that pause before rerunning if necessary. The component **existing call sample** should report native + Telegram self-participant verification, not merely "adapter installed".
6. Leave the test call active briefly while running the host reader below. After collecting the report, cancel/end your test job through the normal controls and verify the saved account remains available without a new sign-in.

Full identity probes still skip busy accounts. The separate bounded existing-call sample can prove an active saved authorization even when your only account is busy. It respects current target authority, moderator state, cooldown, call ID and deadline. A check racing a normal call end can be incomplete; that is not fabricated success or necessarily a bot error.

For a large roster, a health scan may legitimately be **partial** at its configured budget. The existing external setting `limits.manual_health_timeout_seconds` can be reviewed within its supported 15–1800 seconds range (ordinary default 600; VPS profile 1800 via `MANUAL_HEALTH_TIMEOUT_SECONDS`); do not reduce pacing or bypass waits to make a test finish. Do not promise hardware/account-count capacity based on this one-account smoke test.

## 4. Run the read-only host reader

Run in the **existing running app container**:

```sh
umask 077
docker compose exec -T app python scripts/live_check.py > telepilot-live-check.json
```

The output redirection writes the report on your host, not inside the read-only image. Choose a dedicated report filename; do not redirect over private config/backups. Preserve the command's exit code if using automation.

In a Railway running-service shell or an already activated native installation with the original environment/config:

```sh
python scripts/live_check.py
```

For an explicitly mounted external file, if not already configured by `CONFIG_PATH`:

```sh
python scripts/live_check.py --config /path/to/your/existing/config.json
```

The optional `--max-report-age` is 30–3600 seconds, default **300**. It bounds evidence age; it does not bypass a Telegram wait or turn an old/wrong-runtime report into valid proof. Do not pass passwords, tokens, keys or full Mongo URIs as CLI arguments. The old `scripts/smoke_test.py` entry point now invokes the same safe reader instead of mutating indexes or printing bot identifiers.

### Exit codes and truthful scope

| Exit | Meaning |
|---|---|
| `0` | Automated host checks passed for the declared scope, including fresh saved-authorization evidence and an existing-call observation when calls are enabled. **Manual acceptance is still separate.** |
| `1` | Configuration, local HTTP/readiness, Mongo, singleton lease, Bot API identity or owner configuration failed/unavailable. Inspect authored reason codes; do not paste secrets. |
| `2` | Core checks may be reachable, but required fresh in-process identity/call proof is missing, stale, partial or unobserved. Run `/health` in the existing runtime during the authorized managed call; do not start another runtime. |

With no managed call running, calls-enabled deployments normally report `2`, not a false RTC pass. A calls-disabled installation says that call testing was **not checked**. The JSON always leaves `complete_live_acceptance=false`: a machine cannot honestly certify your manual phone/2FA/QR, UI or recovery observations by reading a database.

The script does not expose account/session records. It uses count-only account queries and a strict projection of the sanitized evidence. It does not retry a failed Bot API identity request automatically. It reads only loopback health URLs; no public portal/token URL is needed.

## 5. Return only the sanitized evidence

Upload `telepilot-live-check.json` (or copy its JSON) and these short manual outcomes, without identifiers, private links or credentials:

```text
/start + original photo + editable navigation: pass / fail / not tested
private phone → OTP → exact 2FA: pass / fail / not tested
QR flow, if used: pass / fail / not tested
saved account restart/reconnect without new OTP: pass / fail / not tested
owned call visibly attended, then stopped without losing saved login: pass / fail / not tested
roles / feature plans / target restrictions: pass / fail / not tested
```

Do not spend another OTP login on a valid production session merely to fill a box. If the sign-in flow itself must be freshly exercised, use one disposable **account you own** through the existing consented UI. No code/password/QR token should be included in reports. Skip destructive ban/revocation/FloodWait experiments; do not provoke Telegram restrictions to test them.

If a step fails, include the action and safe reason/error **type**, not raw request/exception text. The report determines what was actually checked; any remaining issue can then be fixed against real host evidence instead of guessing or calling mocked tests "live".

See [SESSION_RECOVERY.md](SESSION_RECOVERY.md), [LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md), [DEPLOYMENT.md](DEPLOYMENT.md) and [RAILWAY.md](RAILWAY.md).
