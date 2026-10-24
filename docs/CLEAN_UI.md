# Clean, editable bot panels — retained in TelePilot 1.3.1

## What changes

- Private navigation uses **one main text panel per user**. Buttons edit that panel rather than send another menu. Lists, forms, account controls, plan controls, task review and help use the same panel.
- `/start` also shows the exact supplied image in a **separate reused banner**. Buttons live on the text panel, so Telegram's photo-caption limit does not constrain the menus.
- Reopening an identical screen skips the edit request. An explicit `/start` probes the banner and panel and repairs deleted messages when Telegram reports them missing.
- Panel and banner message IDs survive a restart through MongoDB. Deleted/inaccessible messages are recreated when an edit fails; formatting errors do not create replacement-message spam.
- Default labels and prose use **smallcaps**, without an initial Latin capital. Commands, URLs, usernames, email addresses, HTML attributes and `<code>` / `<pre>` examples retain their exact functional values. Button callback data and URL destinations are never changed.
- Help is shorter and split into **quick guide** and **limits & safety**. The interface is English. Account/channel names come from Telegram and may naturally contain their owners' chosen language.
- Commands and active form inputs are deleted best effort to keep private chats tidy. Ordinary off-form conversation is not silently erased.

Example heading: **✦ ᴛᴇʟᴇᴘɪʟᴏᴛ**. Example button: **💎 ᴍʏ ᴘʟᴀɴ**. Copyable values such as `/signin`, `@MyChannel` and `30 5 extend` stay ASCII/original where appropriate.

## Intentional exceptions

**Real notifications remain separate messages:** Premium activation/expiry/revocation, task outcomes, account health and operational alerts. Otherwise a notification could disappear when someone opens another menu.

**A QR sign-in photo is transient and separate**, not the banner or main panel. The main panel changes to the QR step; approval/cancel controls update it. LoginManager removes the QR photo best effort after checking approval, cancellation or expiry. A genuine browser-approval message exists only in the explicitly enabled legacy browser mode.

**URL buttons open their destination**, as Telegram requires. They do not call the bot's navigation handler. Short error alerts/toasts may accompany a button failure without posting another chat message.

The update does not bulk-delete old bot messages from earlier versions. It starts reusing a new durable panel on first use, then keeps subsequent navigation clean.

## Settings

Defaults in `config.json` / `config.example.json` and the Config class:

```json
"ui_style": "smallcaps",
"ui_edit_panels": true,
"ui_clean_inputs": true
```

Corresponding direct-service/Railway environment variables:

```dotenv
UI_STYLE=smallcaps
UI_EDIT_PANELS=true
UI_CLEAN_INPUTS=true
```

For VPS Docker Compose, edit the external `config.json` UI keys. The stock Compose file passes only its explicitly listed environment keys; adding other names to `.env` alone does not pass them to the app. If you prefer environment overrides, add those UI names to the Compose app environment mapping too.

- `UI_STYLE=plain`: ordinary English lettering for accessibility, search/copy convenience or troubleshooting.
- `UI_EDIT_PANELS=false`: legacy send-a-new-message navigation, useful only when deliberately requested.
- `UI_CLEAN_INPUTS=false`: retain non-login commands/form inputs. Credential deletion remains best effort regardless of this cosmetic setting.

Unicode smallcaps are decorative text, not a special Telegram font. Rendering/screen-reader support varies. Functional tokens intentionally do not match the decorative style.

## Recovery and pacing

Telegram panel/banner FloodWaits pause further UI updates for the affected user. The previous panel stays in place. A callback error uses a short alert instead of recursively attempting another edit during the same pause. Do not repeatedly tap or try to bypass the pause.

Per-user action and panel locks serialize callbacks/text inputs and panel creation. Identical renders are deduplicated. The in-memory metadata cache is limited to 512 users; idle locks are weakly held. Mongo stores message IDs, banner identity, a render hash and timestamps, not panel text, entered credentials or QR tokens. Metadata expires after 90 days without a saved update. A transient metadata-write failure retains the already-sent panel in RAM and retries persistence on later rendering; a crash before recovery can still lose that last metadata update.

This is single-runtime navigation, not an exactly-once Telegram delivery guarantee. A network failure after Telegram accepted a request may leave an uncertain result. External authorization and account/plan checks remain fresh database checks; the UI cache does not grant access.

## Safe update

1. Back up your configuration and database. Keep the **same original SESSION_ENCRYPTION_KEY**, Mongo database and authorized owner IDs.
2. Replace the source/build files with this release. Do not upload real `.env`, session files or credential screenshots.
3. Keep `LOGIN_MODE=chat`; rebuild the Docker image or redeploy Railway from the updated source. A restart of an old image is not an update.
4. Run one replica. Confirm `/health/ready` after boot.
5. Open `/start`, click through the menus and follow the UI section of [LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md).

No new login method is forced. The working phone → OTP → optional 2FA flow and QR alternative remain available. No database reset or encryption-key rotation is required for this UI update.

## Subscription/health additions (1.2.0)

Feature plan selection, channel/account limits, review and staff corrections use the same editable panel. Unavailable automation buttons are hidden and server-enforced. Channel lists/selection are paginated. Contact admin opens the configured Telegram username. Health runs in the background; a non-secret view tag prevents late progress from overwriting another menu. See SUBSCRIPTIONS.md and HEALTH.md.

## Explicit /start recovery (1.3.0)

/start is not a button navigation action: it creates a fresh visible text panel, then best-effort deletes the old text panel only after the replacement is acknowledged. The reused banner is optional; failure/timeout does not swallow the essential panel. Ordinary command cleanup happens after a successful response, not first. Credential inputs remain immediately cleaned. Button pages, subscription reviews, auto settings and progress continue editing that current text panel. Unsupported/old Telegram message deletion can leave the old panel in history; no erasure guarantee is made.

## Photo visibility correction (1.3.1)

Each explicit /start now sends a fresh photo first (when enabled), followed by fresh text/buttons. The old banner/text pair is deleted only after replacements are acknowledged. This replaces the earlier old-banner reuse on start; normal button navigation remains editable. Media/settings reads are bounded, invalid cached/custom IDs can fall back, network uncertainty is not blindly retried and Telegram rate pauses are respected. Owner start photo controls persist visibility without touching QR/login secrets. Audit machine data uses code/pre, not decorative smallcaps. See PUBLIC_JOINS_PHOTOS.md.

## Visible account/callback failures (1.3.2)

An early callback ACK is only a spinner acknowledgement. UserError now edits the panel or uses a safe independent text fallback; a second after-ACK popup is not the sole error channel. Known RetryAfter pauses are respected, not recursively bypassed. Full enrollment opens an actionable staff capacity screen with protected MAX_POOL_ACCOUNTS. FSM lookup/ACK failures are within recovery handling; staff-only controls remain role-gated.
