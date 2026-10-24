> **1.3.2:** new installs default to 100 saved accounts. Existing installs retaining a JSON cap of 20 must set MAX_POOL_ACCOUNTS=100 and rebuild. Full-pool errors are now visible, saved-session health attachment is background/tracked, and initial account loading does not block bot polling. Phone/OTP/exact-2FA/QR protections remain. Read [ACCOUNT_CAPACITY.md](ACCOUNT_CAPACITY.md).

# Private-chat account sign-in — retained in 1.3.0

## Update existing Railway deployment

1. Replace the updated source/build files, especially `app/`, `config.example.json`, `requirements.txt`, `requirements.in`, Dockerfile/ignore and scripts. A full source replacement is safest if you have no custom changes; back up custom non-secret limits first.
2. Keep the existing real private API/bot/Mongo credentials, owner IDs, **original SESSION_ENCRYPTION_KEY** and database. Do not run setup again over saved sessions or delete data volumes.
3. Add **`LOGIN_MODE=chat`** to the app service Variables. Chat is also the default in the new Config/templates. Existing public domain/PORT variables can remain for health checks.
4. Perform a new **rebuild/redeploy**, not just a restart of the old image. New QR renderer dependencies are pinned. Use one replica, target port matching PORT, deploy health `/health/live`; verify `/health/ready` after startup.
5. Open `/start` → **manage bot** → **add account**, or `/signin` (`/login` alias).

VPS Compose: set LOGIN_MODE=chat in your private .env and rebuild. No HTTPS login domain is required for this mode. Optional public health monitoring should still be behind a trusted HTTPS proxy.

## Phone → OTP → optional 2FA

- Read the explicit account-ownership/full-session-access/privacy warning. Only currently authorized staff can proceed, in their own private bot chat. Tap **I own it · Phone → OTP**.
- Send your owned account's international phone number, e.g. +919876543210. Sharing your own contact is also accepted; other people's forwarded contacts/codes are not.
- Wait for the code prompt. Enter only the latest numeric login code delivered by Telegram for that request. No auto-approval, recovery-token guessing or verification bypass is implemented.
- If Telegram requires 2FA, send the exact password as a separate text message. Leading/trailing spaces and a leading `/` are preserved. Active-password input is not dispatched as an admin command. Exact `/cancel` is reserved for cancellation; if your password literally equals that command, use an explicitly enabled trusted alternative flow instead.
- On success, the actual account ID is checked and the StringSession is encrypted before storing in Mongo. View Accounts for health. A successful save does not claim every later connection is healthy.

Bot attempts to delete every credential input immediately before processing. **Bot chats are not end-to-end encrypted; Telegram/the trusted operator may access or retain copies.** Deletion is best effort, not guaranteed erasure. No OTP/password is placed in application logs, audit, Mongo or FSM. Python cannot guarantee RAM erasure. Do not post any credential in this support conversation, a group or an untrusted bot.

Telegram can invalidate a login code when it is sent to a chat. If that happens, do not split/encode/disguise codes to evade the protection. Use the QR alternative or your own trusted official/local/HTTPS flow. No request-sent/login/no-ban guarantee is possible without live testing your own authorized account.

## QR alternative (same bot chat)

1. Tap **I own it · QR alternative** after the warning.
2. The service exports a short-lived MTProto login token and posts a locally rendered PNG in your private staff chat. Its SDK listener starts before display.
3. Use your official Telegram app **Settings → Devices → Link Desktop Device** to scan it, or the **Approve in Telegram** link if your client supports it. On a single phone, client gallery import/link support varies; another trusted display/device may be needed.
4. Confirm only a login you initiated to this self-hosted service. QR/link is credential-like: never share/forward it.
5. Tap **Check approval**. It does not silently save just because another device scanned: staff actor/nonce/role are checked again. Optional 2FA can follow in the same dialog.
6. QR expires quickly (Telegram controls expiry). Cancel/start a fresh sign-in if expired; no token reuse/verification bypass. Photo/token are removed best effort after check/cancel/expiry.

A scan that authorized the temporary client but was never checked/saved is logged out best effort on dialog expiry/cancel. QR does not make a bot chat E2E or protect against a compromised service/device.

## Controls

- Private staff access only; Premium customers cannot sign in accounts.
- Fresh nonce for buttons, 10-minute dialog lifetime, bounded credential attempts, concurrent step rejection and only one pending re-auth claim per account.
- `/cancel` stops a pending dialog. Navigating away cancels it. Dialogs do not survive restart; request a new one. Cancellation does not undo a session already committed to Mongo.
- Re-authentication keeps the original Telegram ID and admin ownership. Busy accounts must first stop their job. The old saved account remains enabled/connected during consent/OTP/QR. Only a successful authorized replacement commits a swap; cancel/failure before commit leaves its saved authorization unchanged. Busy state and staff changes are checked again at commit.
- Removing staff role or expiry closes transient clients. Unambiguously unsaved authorizations are logged out best effort. A possibly committed write is never remotely revoked merely because storage confirmation failed; check Accounts/Mongo before another OTP.
- Login FloodWait is stored in Mongo and enforced on fresh dialogs/restarts; no retry before its deadline. Wrong/expired/banned/unsupported email/device verification receives clear messages without credential dumps.

## The reported ValueError

A relevant bug was reproduced in the real installed Telethon request implementation using controlled fake transport futures: the old `request_retries=0` allowed one attempt, handled a PhoneMigrateError by switching DC, but had no follow-up attempt. It then raised generic **ValueError: Request was unsuccessful 1 time(s)**. Many accounts must use a different DC than a new session's initial DC.

1.0.2 uses **3 bounded retries** (initial attempt + up to 3 follow-ups), `raise_last_call_error=True`, and still `flood_sleep_threshold=0`. A positive FloodWait surfaces immediately; it is not slept through/hidden. The migration regression test verifies a second request after switching DC, and a separate test verifies no hidden FloodWait retry. This explains a plausible failure path matching the screenshot's generic phone-step ValueError; the screenshot alone does not prove the user's exact exception text/cause. Phase/type/stack-frame diagnostics now help distinguish other failures without printing inputs.

## Optional legacy browser mode

Default `/login` and `/api/login/*` return **410 disabled**, not a fresh browser approval. HTTP health remains enabled. If you deliberately prefer your own trusted HTTPS flow later, set LOGIN_MODE=browser, configure the exact public HTTPS origin and rebuild/restart appropriately. It retains browser-code approval, CSP/cookies/CSRF and remains separate from chat dialogs. Never impersonate Telegram or collect customers' credentials.

## Verification boundaries

Automated tests cover the complete bot wizard, mock OTP/2FA/QR outcomes, real Fernet/Mongo storage, no credential FSM persistence, cancellation/role loss/expiry/wrong re-auth ID, best-effort deletion failure, leading-/password handling, SDK migration/FloodWait internals and disabled browser endpoints. Real Telegram OTP delivery/expiry, QR scanning, Telegram deletion retention and provider networking were not live-verified here. Complete LIVE_ACCEPTANCE.md with your own account before production use.

## Clean UI compatibility (1.1.0)

Sign-in prompts now edit the durable text panel, including phone/code/2FA. Because Telegram cannot attach ForceReply to edited text, the password screen has an inline cancel button; exact spaces and leading `/` still work. QR remains a separately cleaned transient photo, never the durable start banner. The main panel changes to the QR step and returns to account controls on completion/cancel. Production-default phone/2FA and QR/cleanup tests are included alongside the original regressions. See [CLEAN_UI.md](CLEAN_UI.md).

The 1.2.0 subscription/health update does not replace this login flow or the encryption key. Paid feature plans are for customer automation; only owner/admin roles can add account sessions.

A stale/non-password sign-in form can now return home with /start. During the exact 2FA-password stage, leading-slash password parsing is still preserved; use the cancel button or /cancel to cancel rather than treating a literal password as a staff command.


## Saved-session recovery (1.4.1)

Temporary disconnects are not a reason to repeat phone sign-in. Accounts shows saved-session recovery/deadlines. Reauthentication dialogs retain the old saved account until a validated commit, and cannot undo a later staff disable/removal or overwrite a newer authorization. A confirmed replacement can leave the old Telegram device authorization visible; review Settings → Devices deliberately. See [SESSION_RECOVERY.md](SESSION_RECOVERY.md).
