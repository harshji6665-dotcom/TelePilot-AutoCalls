# Required subscriptions — TelePilot 1.3.0

**Owners add/remove/view required channels/groups. Admins can view only.** Owner/admin staff are exempt from the gate so they can fix a broken requirement or sign in owned pool accounts. A contact link is not a staff grant.

## Owner controls

Open **manage bot → required subscriptions**:

- **Add required channel:** send `@username` or its numeric `-100...` chat ID, review and confirm.
- **View:** see all requirements and open their join links.
- **Remove:** review and confirm. This removes the requirement, not existing Telegram members.

Commands use the same review panels:

```text
/forcesub
/forcesubadd @YourRequiredChannel
/forcesubadd -1001234567890
/forcesubremove -1001234567890
```

`/forcesub` is available to owner/admin; add/remove are owner-only at both UI and service boundaries. Destructive confirmation has a 15-minute actor-bound nonce; an old/foreign/cancelled review cannot mutate requirements.

You and the bot must be admins of the configured channel/supergroup; the bot needs invite permission. Arbitrary private invite links, basic groups and private user chats are not accepted. For a private target, give its numeric ID and the bot creates a managed membership invite. Public targets use their current username link. Default maximum: **10** requirements (`limits.max_force_sub_channels`, 1–20).

Duplicate addition does not create another invite. Private managed invites are revoked on removal where Telegram permits it. If the bot has been kicked/permission was lost and revocation is forbidden, the owner can still remove the broken requirement. An existing public username link is not owned/revoked by this bot; remove/re-add if that target's username changes.

## User experience

An unverified regular user gets the **join before continuing** panel with one join link per unmet requirement and **check membership**, **contact admin**, **help**. Once all are joined, check membership opens home. A first check after joining bypasses the ordinary negative cache; repeated check-button spam is throttled.

- Creator/admin/member count as membership.
- A restricted member counts only if Telegram reports `is_member=true`.
- Left/kicked users and **pending join requests do not count**. Wait for the channel/group admin's approval if Telegram requires it.
- Failed/timed-out membership checks pause access; they never grant it as a fallback. Error-message contents/tokens are not shown.
- Positive checks can be reused for **30 seconds**; negative/error checks normally for **10 seconds**. Explicit checks have a short repeat throttle. Changes to requirements invalidate local membership cache.
- Membership API work is globally concurrency-limited, bounded to 12 seconds for a complete gate check, and honors Bot API RetryAfter.

Help, ID, contact and **stop/cancel** operations remain available so a user can get support or stop their own work without a membership lockout. A Premium role does not bypass required membership. Owners/admins stay exempt.

## Server enforcement

The middleware gate is not the only check. Customer `Access.entitlement` also enforces membership, so direct/old callbacks, job creation/execution and automatic call joins cannot bypass it by hiding or forging buttons. Existing work stops/pauses at its next authorization check after membership becomes unverified (subject to the short positive-cache window).

Required subscriptions are global and separate from paid saved-channel slots; they do not unlock more customer slots. Auto mode is independent opt-in and is still restricted to calls/both plans, permanently registered targets, account caps, target ownership and Telegram safety rules. See AUTO_CALLS.md.

## Upgrade and live checks

Keep the original key/database, rebuild updated source and retain one replica. The new collection begins empty: no forced-subscription target is guessed from old saved channels, screenshots or staff/customer IDs. Do not publish private invite links in logs, git or support screenshots.

Before requiring a target globally, test with a separate regular-user account: unjoined gate → join/approval → check → home. Verify removing a requirement clears the gate, admins cannot forge add/remove, and staff remain able to repair it. Automated checks use real disposable Mongo and controlled Bot API responses; no live target/membership/hosting test was performed here.
