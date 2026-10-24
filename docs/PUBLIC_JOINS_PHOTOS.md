# Public joins, start photos and diagnostics — TelePilot 1.3.1

## Public channel/group joins

A saved public target is joined through its **current public username** using Telethon `channels.JoinChannelRequest`, not a bot-created request invite. This applies to the button wizard, direct task creation and resumed/old queued join tasks. A saved private target keeps the bot's **managed request invite**. Calls still use the separate call invite; this update does not turn channel-only plans into call plans.

The task validates the provided link against your own locked target first. It then resolves the registered numeric chat ID through Bot API to choose public/direct vs private/request mode. The signed-in account resolves the public entity and verifies the **same numeric chat ID** before joining. A renamed username is refreshed at worker execution; a username/identity mismatch or foreign invite is rejected. No arbitrary public channel gets authorized just because it is public.

**Telegram approval rules still win.** Some public targets also require approval. If Telegram returns InviteRequestSentError, the result remains `request_sent`: this is a submitted request, not a confirmed membership. UserAlreadyParticipantError means `already_member`; other failures have protected error types. The bot cannot force membership, evade a ban or claim a pending approval succeeded.

Retries retain completed outcomes and do not repeat already successful requests. Already-terminal old jobs are not silently re-run; create a new reviewed task if you deliberately want another attempt. Check **my tasks → details**, rather than interpreting `partial` as a specific RPC cause.

Original account join gap/day caps, feature/expiry/force-subscribe/ownership checks and singleton limits remain. A complete per-account membership lock now serializes day/gap/counter mutation between manual work and detector membership; state is re-read after waits so disable/cooldown/UTC-day changes cannot use a stale snapshot. Public entity lookup is bounded. Revoked sessions detach; network/timeouts mark the account offline with cooldown before later health reload.

## Why the start photo appeared only at first

In 1.3.0, /start replaced the text panel but edited/reused the **old photo message ID**. Once that image moved higher in chat history, a later /start could show a new text panel without an obvious new image. This source behavior reproduces the reported appearance problem; a production-specific image/network/FloodWait failure cannot be ruled out from the supplied audit alone.

1.3.1 sends an enabled photo **anew on each explicit /start**, then places the fresh editable text/buttons below it. The previous photo/text panel is deleted best effort **only after its replacement is acknowledged**. Normal button navigation does not resend the banner. There is no 2–5 minute expiry rule or cache suppression for a new start photo.

Photo delivery includes settings reads and is bounded to 12 seconds. A rejected stored/custom file ID can fall back once to the exact supplied PNG. Network timeouts/unknown acknowledgments are not immediately retried. If media fails, the text response is still attempted. Actual Bot API RetryAfter pauses are honored across photo/text requests, not bypassed. An ordinary failed /start is not deleted first; credentials retain immediate best-effort cleanup.

The default PNG's returned Telegram file ID is cached with the bot ID and original asset checksum to avoid re-uploading 4 MB for every start. Caching the **file ID** is not caching away the **send**. Switching bots/invalid IDs invalidates or falls back to the supplied asset. The original image and fallback URL are unchanged.

## Owner photo buttons

**Manage bot → start photo**:

- **Set start photo:** send one Telegram photo, not a document or arbitrary URL. Actor-bound 15-minute input and fresh owner checks apply.
- **Preview photo:** preview even while automatic start-photo delivery is disabled.
- **Enable / disable photo:** explicit idempotent setters; double clicks do not reverse the intended setting.
- **Restore supplied image:** remove the custom choice/cache; keep the current enable/disable preference.

Commands:

```text
/startphoto
/startphoto on
/startphoto off
/setphoto
/resetphoto
```

Only owners can mutate/preview these controls, matching the existing banner policy. Admin/user forged callbacks are denied. The saved custom choice is preserved when delivery is disabled; disabling affects **future starts**, not every old photo in Telegram history. Normal Telegram limits can prevent old-message deletion; no erasure guarantee is made.

The JSON/env `start_photo_enabled` / `START_PHOTO_ENABLED` default is true. Once an owner saves the preference, the Mongo `start_photo_enabled` setting takes precedence and survives restart. Optional blank VPS Compose env preserves an explicit JSON false. Existing external config can omit the new key and use its default.

Login QR photos are transient, separate and unaffected by disabling the start banner. Working private-chat phone/OTP/2FA/QR/session code is not replaced. Keep your original encryption key/database.

## Reading partial jobs and the supplied audit

The submitted audit shows **partial** join jobs but no per-account result exceptions for those joins. It also shows a session later marked **revoked** after AuthKeyUnregisteredError, an earlier ConnectionError and an uncertain native call cleanup. Those facts do not prove a package-version problem or identify every failed account's join cause.

New notices/details show a protected ASCII error-type summary and a **task details** button. Staff see up to eight priority per-account results and authored recovery hints. Audit action names/IDs/JSON are code-formatted, so smallcaps no longer corrupt copyable job IDs, error classes or JSON values. No raw Telegram exception message, session string, OTP or password is exposed.

- **AuthKeyUnregisteredError / SessionRevokedError:** sign that owned account in again. A software update cannot revive a revoked Telegram session.
- **ConnectionError / TimeoutError:** check host/network and account health. Failed identities are cooled down/detached, not repeatedly presented as healthy.
- **CallCleanupUncertain:** the prior guard deliberately retired an uncertain native transport before reuse. Wait for cooldown and check health; investigate real RTC/host behavior if it repeats. The protection was not disabled just to hide the alert.
- **InviteRequestSentError / request_sent:** await target-admin approval; not joined yet.
- **FloodWaitError / TelegramRetryAfter:** wait for Telegram's recorded deadline; no early bypass.
- **ChannelsTooMuchError / UserBannedInChannelError / ChannelPrivateError:** review the account's actual membership/limits/permissions; no restriction bypass.

API/import signatures and package-version reports are not proof of a successful Telegram join or RTC connection. If a new task still fails, share only its protected **error type and sanitized stack-frame/incident lines**—not credentials or screenshot secrets.

## Upgrade / acceptance

Keep the existing private .env/config.json, original SESSION_ENCRYPTION_KEY, Mongo database and volumes. Stop only the old app, replace source without overwriting private files, rebuild and run **one replica**. New fields have defaults; old paid plans, permanent target slots, forced-subscribe settings and auto opt-ins are retained. Do not reset data or use old code concurrently.

Test a real authorized public target (direct join), private request target (pending until approved), repeated /start after 5 minutes, owner set/off/on/default buttons, and an unjoined force-subscribe user's start photo/gate. Complete LIVE_ACCEPTANCE.md on your host.

The source test suite uses real disposable Mongo and controlled Telegram/Bot API/RTC responses. No live Telegram membership/photo, Docker build or VPS/Railway redeployment was performed here. No production credentials or the supplied real user/account IDs were used as test fixtures.
