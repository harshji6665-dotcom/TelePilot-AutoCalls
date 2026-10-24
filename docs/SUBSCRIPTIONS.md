# Feature plans, unlimited quotas and locked channels — TelePilot 1.4.0

See [UNLIMITED_PREMIUM.md](UNLIMITED_PREMIUM.md) for independent unlimited quotas, future pool additions, schema 3 and upgrade/rollback precautions.

## The three plans

| Plan value | User automation buttons | Server permission |
|---|---|---|
| `channels` | join channels only | Authorized channel/group joins and join requests |
| `calls` | join a call only | Authorized group/channel voice-video call tasks |
| `both` | both buttons | Both kinds of tasks |

Utility buttons remain: my tasks, my plan, my channels, help and contact admin. Free/expired users have no automation buttons and cannot add new channels. A host with calls disabled does not display a call button.

This is **not just hidden buttons**. The server checks the feature on task creation, confirmation, execution, pacing checks and call loops. Old buttons/forms and previously queued tasks cannot bypass a changed plan. Changing features or reducing the account cap requests cancellation of tasks no longer included; active call tasks leave at the next safe check. A calls-only task may join its registered group as a necessary membership step before joining the actual call; it does not unlock independent channel-request tasks.

Owners/admins retain separate config-limited staff test access. Their staff role takes precedence over a paid plan assigned to the same ID.

## Three separate limits

- **Duration:** 1–365 days per grant/extension.
- **Channel/group slots:** how many distinct registered Telegram targets the user may save. New finite-plan default is 1; staff can instead choose unlimited. The separate operational per-user host ceiling defaults to 100, supported range 1–100.
- **Accounts per task:** number of authorized signed-in pool accounts a task can use. This is not a channel count. Staff can choose unlimited to include current/future eligible pool accounts. Pool capacity and existing safety quotas still apply; a manual task keeps its reviewed concrete count.

The slot limit is **shared across both features**. The same registered group used for channel joins and calls consumes one slot, not two. Changing its title/username does not create a new slot; the stable Telegram chat ID identifies it.

## Permanent user lock

A saved channel/group remains stored and locked. Users cannot delete it, replace it or remove it to reuse a slot—not through an old callback either. The lock remains after plan expiry, revocation, restart, renewal or switching the feature plan. Re-registering the same chat ID does not use another slot.

Saving requires an active plan, user and bot target-admin control, and bot invite permission. Review the chosen channel before adding it. An upgrade increases available slots; a downgrade below the number already saved is rejected. Staff must deliberately correct/remove the excess channels first. No saved data is silently deleted to make a lower-priced plan fit.

Channel lists and task target selection are paginated, so plans with more than ten saved targets can actually select them.

## Give Premium with buttons

`/start` → **manage bot** → **give premium**:

1. Enter the customer's numeric Telegram user ID. They can use `/id` to find it.
2. Choose **channels only**, **calls only** or **both**.
3. Choose/send duration in days.
4. Choose/send a finite channel/group slot limit or **unlimited channels**.
5. Choose/send a finite account limit per task or **unlimited accounts**.
6. Choose **start today** or **extend current plan**.
7. Review all values and confirm.

The wizard edits the existing panel, expires after 15 minutes and uses an actor-bound request key so a retry does not extend the plan twice. Customers must start/unblock the bot to receive notifications. Owner/user notices include selected features, slot limit, account limit and expiry. There is no payment gateway or automatic payment verification.

## Command format and examples

```text
/premium USER_ID DAYS PLAN CHANNELS [ACCOUNTS] [set|extend]
```

`PLAN` is exactly `channels`, `calls` or `both`. Values are plain ASCII, not decorative smallcaps. Copyable examples in the bot stay inside code formatting.

### Unlimited combinations

```text
/premium 123456789 30 both unlimited unlimited set
/premium 123456789 30 calls 2 unlimited set
/premium 123456789 30 channels unlimited 5 set
```

These are paid quota modes, not infinite host capacity. Automatic calls consider later eligible pool additions; existing manual tasks do not silently expand.

### Calls only: 1 group/channel, 5 accounts per task, 30 days

```text
/premium 123456789 30 calls 1 5 set
```

### Channel joins only: 2 channels, 3 accounts per task, 30 days

```text
/premium 123456789 30 channels 2 3 set
```

### Both: 3 channels/groups, 5 accounts per task, 30 days

```text
/premium 123456789 30 both 3 5 set
```

### Extend both by 15 days, keeping the specified 3-slot/5-account limits

```text
/premium 123456789 15 both 3 5 extend
```

- `set`: expiry = today + days; it replaces remaining duration.
- `extend`: expiry = later of today/current expiry + days.
- Omitting the account argument keeps the existing finite/unlimited account limit; for a first assignment, it uses the configured default (5 by default).
- `/revoke USER_ID` removes Premium access/cancels tasks, but **does not erase/unlock saved channels**.
- `/premiumhelp` and **premium examples** in manage bot show these examples.

### Old short commands still work

```text
/premium 123456789 30 5 set
/premium 123456789 15 extend
```

They preserve an existing plan's features and channel limit, including unlimited slots. Omitting accounts also preserves unlimited accounts; an explicit finite count switches that mode off. They do not silently upgrade a calls-only customer to both. For a genuinely new user with no previous plan, a short grant defaults to both + 1 channel. Prefer the new explicit command or wizard for priced plans.

## Audited owner/admin correction

The user selected **owner or admin override**. A customer cannot invoke it.

`manage bot` → **channel corrections** → enter customer ID → select channel → **remove for correction** → enter reason (5–200 characters) → confirm.

- Finish/cancel and wait for all queued/running tasks using that channel to reach a terminal state first.
- The staff role is rechecked. A confirmation is nonce-bound and expires after 15 minutes.
- An acknowledged audit event containing staff ID, customer ID, stable channel ID and reason is required before removal. Do not put credentials in the reason.
- Managed invites are revoked, the registered target is deleted and the slot becomes available for an intentional replacement under an active plan.
- A customer/owner notification is queued. No free-text reason or private invite is sent in that notice.
- Cancellation leaves the channel locked; it does not leave a destructive input form active.

This is a correction, not a customer-controlled recycling feature. Staff are trusted to price and approve changes appropriately.

## Existing Premium data on upgrade

Chosen policy: **preserve existing access**.

After singleton lease acquisition, an idempotent migration fills missing legacy feature fields with `both` and missing slot limits with the old allowance of **10** (or the existing saved count if greater). Existing sessions, expiry/account caps, plans, jobs, channels and the encryption key are retained. Regular users' existing targets become locked. New-schema plans and staff-owned test targets are not overwritten.

A later explicit staff plan assignment applies the newly chosen limit/features. Setting 1 slot for a user who already has 2 saved channels is rejected until staff correct the excess target. Missing legacy fields are grandfathered; an invalid explicit feature value fails closed and needs an explicit staff reassignment.

**Back up before deployment.** Preserve the original database and SESSION_ENCRYPTION_KEY; never delete volumes to apply this update. The old source did not enforce permanent target locks. Do not run/roll back to it on the same upgraded database while promising the new restrictions.

## Contact admin from .env

VPS Compose `.env` (or Railway app Variables):

```dotenv
ADMIN_USERNAME=YourActualAdminUsername
```

An optional leading `@` is accepted. Use a Telegram username, **not a URL or user ID**. The stock Compose file now passes it to the app, so adding it to `.env` works after recreating the container. `CONTACT_ADMIN_USERNAME` is also accepted by direct environment loading; existing `SUPPORT_USERNAME` / JSON support contact remains a fallback.

The contact button opens `https://t.me/<username>`. It does not grant staff permissions or verify that this username belongs to an owner. Owners/admins are still authorized by configured numeric IDs and Mongo roles. Do not point it at an untrusted third party.

For direct/file deployments, the equivalent JSON key is `admin_username`. An unset contact gives a clear notice instead of a broken URL. `.env` is a Compose input; plain `python -m app` does not automatically read it—export variables or use JSON references as documented.

## Automatic calls and required membership (1.3.0)

Calls/both plans also permit explicit opt-in automatic call watching of saved targets; account caps apply per channel/call and free accounts are shared fairly after manual-job demand. Channels-only cannot enable it. Required subscriptions apply to regular Premium users as well as free users. Staff are exempt, but only owners manage requirements. Disabling auto never frees a paid channel slot. Staff channel corrections require disabling auto and waiting for any reservations/connections to leave. See AUTO_CALLS.md and FORCE_SUBSCRIBE.md.

1.3.1 public direct joins do not change purchased features/slot permanence. Private targets retain approval requests and call prerequisites remain separate. Owner-controlled start photo visibility is unrelated to subscriptions. See PUBLIC_JOINS_PHOTOS.md.

The 1.3.2 increase of the **saved account pool** does not edit any stored customer's purchased max_accounts, feature tier, expiry or locked target allowance. Paid access and per-task caps still apply. Operator/staff access remains separately config-limited.


## Schema 3 and retained installations (1.4.0)

Explicit independent `accounts_unlimited` / `channels_unlimited` booleans pair with nullable `max_accounts` / `channel_limit`. Backend entitlement resolves fresh effective deployment ceilings before numeric worker checks. There is no current-pool snapshot or huge sentinel. Legacy finite plans remain finite, migration leaves unlimited records intact, and malformed quota combinations fail closed. Expiry/revoke preserves quota preferences/locked targets but stops access. Notices and audit records include both quota modes.

Do not roll old integer-only code back over new unlimited documents without a compatible, reviewed quota conversion/backup plan. Preserve the original key/database/volumes and read the unlimited guide.
