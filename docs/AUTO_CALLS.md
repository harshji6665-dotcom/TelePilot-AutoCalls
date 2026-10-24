# Automatic calls and equal account sharing — TelePilot 1.3.0

This is **opt-in automation for owned/authorized pool accounts and saved channels/groups**. It detects active native Telegram group/channel voice/video chats; it never creates a call or publishes microphone/camera/media. It does not support E2E `t.me/call` conferences or one-to-one calls.

## Enable once

1. Get a **calls** or **both** plan. A channels-only plan cannot enable this feature.
2. Save each authorized channel/group in **my channels**. You and the bot must be target admins; the bot needs invite permission. Permanent channel slots still apply.
3. Open **automatic calls** (`/auto`), choose a saved channel or **enable all saved channels**, read the ownership/membership/privacy notice, and confirm.
4. Start a native voice/video chat in your channel/group through Telegram. The bot detects it on a subsequent scan and uses available healthy accounts to connect.
5. Use **refresh** to see current counts. **Turn off** a channel, **turn off all my channels**, or `/autostop` to stop your automatic participation. Stopping remains available after expiry or a force-subscribe failure.

Newly registered channels remain **off** until explicitly enabled. Turning auto mode off never deletes a locked saved channel. Owner/admin can view a global **auto overview**; users control their own opt-in settings. A physical chat can have only one enabled auto target, even if multiple authorized users saved it.

## Your 12-account example

Suppose three Premium users have respectively **2, 1 and 1 saved channels**, all four channels have active calls, all 12 accounts are healthy/free, and account caps permit the shares:

| Active authorized auto channels | Accounts per channel |
|---|---|
| 4 | 3 + 3 + 3 + 3 |
| 3 | 4 + 4 + 4 |
| 2 | 6 + 6 |
| 1 | 12 |

The allocation unit is a **channel**, not a customer. One user with two active saved channels gets two shares. Accounts leave ended/overfull calls **before** being assigned elsewhere. Each account has one exclusive pool reservation and one managed call assignment.

**Paid caps still matter.** If each plan allows only 5 accounts per task, two remaining channels receive at most **5 + 5**, not 6 + 6; the other 2 stay idle. Auto mode interprets this existing account cap **per channel/call**. For the unrestricted example, staff can choose an account cap of 12 (within configured pool maximum), e.g.:

```text
/premium 123456789 30 calls 2 12 set
/premium 234567890 30 calls 1 12 set
/premium 345678901 30 calls 1 12 set
```

A capped water-fill allocator gives equal integer shares where feasible. Uneven supply gives a difference of at most one among uncapped eligible channels; a feasible remainder holder is kept stable to avoid pointless disconnects. Low caps, unavailable/membership-pending/blocked identities, disabled accounts or network failures can reduce actual connected counts. No account or membership is fabricated to meet a number.

## Manual tasks have priority

- Running manual jobs keep their accounts.
- Due manual jobs get capacity headroom before auto shares. A pending/running manual call on a chat temporarily suppresses auto participation in that same chat, preventing double allocation.
- When manual work finishes, remaining free healthy accounts return to auto sharing.
- Auto sessions are separate from the manual job queue and its parallel-worker limit. They have their own watch/episode/concurrency limits and use the **same exclusive account pool** and Telegram rate gates.

## Detection, safety and recovery

- Default pause **30 seconds between scans** (`auto_call_poll_seconds`). RPC pacing, membership preparation, connection setup, partial scans, cooldowns and provider/network behavior add delay. This is periodic polling—not an instant service-event guarantee.
- A detector uses a healthy free/auto-owned signed-in account. A missing private-chat access hash is resolved only through the saved managed call invite. A manual-job account is not repurposed for membership setup. Reading Bot API messages alone does not supply native group-call IDs.
- Enabling authorizes prerequisite **group/channel membership** for pool accounts, even on a calls-only plan. It does not unlock independent channel-join tasks. Leaving a voice call does **not** automatically leave the group/channel.
- Healthy status, plan feature/expiry/account/channel caps, force-subscription, target control and opt-in are checked independently of menus. Native joins recheck permissions and the **same call ID** after pacing.
- A detected call gets a durable deadline, default **360 minutes**. Redistribution, restart and toggling do not reset it. A changed Telegram call ID is a new episode. An elapsed call stays excluded until a new call starts.
- New-call episode limit: **10 per user per UTC day**, separate from manual job creation. Repeated polling of an existing call is not a new episode.
- Busy/disabled/cooldown identities are unavailable. Telegram FloodWait is persisted; no early retry. Managed membership results are cached within the live session to avoid burning another join attempt every scan. Original join gap/day caps still apply.
- Kicked/removed/disappeared/failed connections are excluded for that call rather than automatically hammering a rejoin. Native moderation flags are also honored. Unknown probe failures are not called "ended"; previously verified authorized connections can survive a short grace, then stale ones leave.
- Detector authorization failures stop retained connections; they are not treated as harmless network timeouts. Revoked/banned detector sessions are marked and detached.
- Native connection setup is bounded to **3 concurrent operations**, and each SDK operation has a timeout. Cancellation/disable interrupts a scan and cleans pending reservations. An uncertain native join/leave retires that local transport with an offline cooldown before reusing the identity; the encrypted session is retained for later reattach.
- Maintenance pauses/leaves auto participation; manual calls remain under their original bounds. Shutdown cancels auto work before manual jobs and pool teardown. Startup clears stale ownership once, **before** either worker starts, while preserving original call IDs/deadlines and block sets.
- Do not run multiple replicas/regions. Mongo singleton leadership is required. Native side effects and uncertain acknowledgments cannot be made transactional/exactly-once.

## Configuration

Global `auto_calls_enabled` defaults true and `AUTO_CALLS_ENABLED=false` can disable the feature. This only makes the feature available; every target still starts off. VPS Compose passes the flag without a nonempty default overwriting an explicit JSON false. Relevant `limits` defaults:

```json
{
  "max_auto_channels": 30,
  "auto_parallel_connects": 3,
  "auto_call_poll_seconds": 30,
  "auto_probe_timeout_seconds": 35,
  "auto_detection_budget_seconds": 90,
  "auto_stale_seconds": 180,
  "max_auto_sessions_per_user_day": 10,
  "max_call_minutes": 360
}
```

Large or slow scans rotate their starting target so a bounded partial scan does not always skip the last channel. Healthy account eligibility constrains shares; channels with no eligible identities do not reserve fictitious capacity. An enabled setting is not a guaranteed live connection. See staff health, overview, account status, sanitized logs and the live acceptance checklist.

## Update and validate

Keep the original encryption key/database/volumes, replace source and **rebuild**, one replica only. Existing paid plans and locked channels are preserved; auto mode is off for targets without an explicit setting. Owners configure force-subscribe separately—see FORCE_SUBSCRIBE.md.

Automated tests reproduce the 12/4 distribution, redistribution, manual headroom, cap handling, expiry/feature/permission loss, duplicate-chat prevention, cancellation, revocation, cooldowns, stale checks, restart/deadline preservation, target corrections and actual aiogram update routing. Telegram/Bot API/RTC responses are controlled fakes; **no live Telegram call or Docker/Railway deployment was performed here**. A real owned-group call on your host is still required to validate RTC/NAT/UDP/CPU behavior.


## Unlimited entitlements (1.4.0)

An unlimited account quota removes the customer's per-channel commercial cap, not global free-pool, host, pacing, moderation or deadline guards. Fresh resolution on allocation/rebalance includes healthy free accounts added after the grant. A new account becomes eligible without regranting Premium; all active channels still share fairly with manual priority. Unlimited slots do not auto-enable newly saved targets: verify/control and select them normally. Existing manual tasks keep their reviewed concrete count; call deadlines never reset on redistribution. Read [UNLIMITED_PREMIUM.md](UNLIMITED_PREMIUM.md).
