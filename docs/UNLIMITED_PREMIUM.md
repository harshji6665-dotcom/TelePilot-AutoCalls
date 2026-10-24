# Unlimited Premium quotas — TelePilot 1.4.0

Unlimited is an explicit **paid entitlement mode**, independently available for accounts and channel/group slots. It is not a snapshot of the current pool size, an expiry bypass, a giant integer, or a promise of infinite host/Telegram capacity.

## Commands

Owner/admin only, in private chat:

```text
/premium USER_ID DAYS PLAN CHANNELS ACCOUNTS set|extend
```

| Example | Meaning |
|---|---|
| `/premium 123456789 30 both unlimited unlimited set` | Both features, unlimited plan slots and eligible accounts |
| `/premium 123456789 30 calls 2 unlimited set` | Calls only, two saved targets, unlimited eligible accounts |
| `/premium 123456789 30 channels unlimited 5 set` | Channel joins only, unlimited plan slots, five accounts per task |
| `/premium 123456789 15 extend` | Add 15 days; preserve existing features and both quota modes |
| `/premium 123456789 15 calls unlimited extend` | Calls/unlimited slots; omitted account allowance is preserved |
| `/premium 123456789 15 3 extend` | Legacy short form: explicitly change accounts to three, preserve features/slots |
| `/premium 123456789 15 unlimited extend` | Legacy short form: explicitly make accounts unlimited, preserve features/slots |

IDs are synthetic examples: replace the example user ID. The keyword is plain ASCII `unlimited` (case-insensitive). `0`, `-1`, `all`, infinity symbols and huge sentinel numbers are **not** unlimited modes. Duration remains 1–365 days per grant/extension.

- `set`: replace expiry with today + days.
- `extend`: add days after the later of today/current expiry.
- Omitting a quota preserves its existing finite **or unlimited** state. First assignments still default to both/one target/five accounts unless explicitly set.
- An explicit finite value replaces the unlimited mode. Staff cannot reduce slots below targets already saved; correct those targets through the audited staff flow first.
- Grant confirmations have the existing actor-bound expiring form/request key; retrying the same confirmation does not extend twice.

## Buttons and notices

Manage bot → give premium → feature tier → days → channel slots → accounts → expiry mode → review → confirm.

Both quota steps now offer their own **unlimited** button and typed input. Review, saved confirmation, My Plan, saved-channel listing, automatic-call panels, staff/customer notices and audit metadata distinguish unlimited from a finite count. These are the same editable panels and English/smallcaps presentation, not a second chat-spamming UI.

The server independently checks active entitlement, feature tier, staff role, target ownership/control and operational caps. Old or forged callbacks do not grant access.

## Current and future accounts

With unlimited accounts, every otherwise eligible signed-in pool identity can be selected, including identities added **after** the Premium grant. No renewal or quota edit is required for later pool additions.

Eligibility still means enabled, healthy, attached, free/reservable, properly authorized and outside applicable cooldowns. Accounts reserved for another task are not duplicated across calls. Sign-in consent, staff account-management scope, Telegram waits and removal restrictions remain.

- **Manual tasks** retain the concrete count reviewed/confirmed by the user. A one-account task does not silently become a 50-account task when the pool grows. A later task may choose the newly available capacity.
- **Automatic calls** rebalance free eligible accounts across active enabled channels on subsequent scans, within each channel's allowance and manual-task priority. Later pool additions become eligible without editing the purchased plan. Existing call deadlines do not reset during redistribution.
- Unlimited slots let a subscriber save additional verified targets within host limits. They do not auto-register arbitrary targets or auto-enable newly saved targets for call watching. Explicit target control and automatic-call selection remain required.

## Operational ceilings still apply

| Guard | Shipped behavior |
|---|---|
| Saved pool ceiling | New-install default 200; `MAX_POOL_ACCOUNTS`, supported range 1–200 |
| Saved targets per user on this host | `limits.max_channels_per_user`, default 100, supported range 1–100 |
| Automatic-call watching | Deployment-wide `limits.max_auto_channels`, default 30 |
| Concurrent native call setups | Default 3 |
| Call deadline / pacing / join quotas | Existing safety settings retained |
| Telegram permissions, moderation and FloodWait | Not bypassed |

These are **host safety ceilings**, not a finite purchased quota. Backend entitlement resolution supplies fresh numeric operational bounds to workers while preserving explicit unlimited flags. It never freezes allowance at the account count present when the grant was made.

An old private config that says 20 still caps enrollment at 20 unless overridden. For the existing after-20 upgrade, set `MAX_POOL_ACCOUNTS=200` and **recreate/redeploy** the app; a plain restart does not apply changed container environment. See [ACCOUNT_CAPACITY.md](ACCOUNT_CAPACITY.md).

Unlimited does not increase supported pool capacity above 200 in this release. A 200-saved-account pool is implemented, with the 8-vCPU / 64-GB profile in [VPS_200.md](VPS_200.md); 200 simultaneous real Telegram/RTC calls are not benchmarked here. Hardware sizing and live native-call capacity need staged tests on the actual host; stored account count is not simultaneous attendance capacity.

## Storage and compatibility

Schema 3 uses nullable values plus explicit, independent boolean flags:

```json
{
  "feature_plan": "both",
  "max_accounts": null,
  "accounts_unlimited": true,
  "channel_limit": null,
  "channels_unlimited": true,
  "schema_version": 3
}
```

Real plans also retain expiry, staff attribution, timestamps and version/request identity. Finite quotas remain positive integers with their flag false. Inconsistent/null-without-flag/string-flag records fail closed for staff review; a missing flag on a legacy finite plan means finite, not unlimited.

Legacy feature/default migration remains idempotent and does not overwrite explicit unlimited documents. Existing finite grants, encrypted sessions, target locks and plan durations are not automatically converted. Revoke/expiry stops access but preserves the saved settings/targets, so a short renewal restores the chosen modes without resetting slots. Notices/audit events carry the selected modes.

**Do not run old 1.3.x code against new unlimited plan documents.** Old code expects integers. Before production upgrade take a normal encrypted-session database/config backup, preserve the original encryption key, and plan rollback with compatible quota conversion or a reviewed matching backup. Never solve rollback by deleting Mongo, replacing sessions, or regenerating the key.

## Upgrade and live acceptance

1. Back up the existing database/config/key using your normal protected process. Keep private `.env`, `config.json`, volumes and `SESSION_ENCRYPTION_KEY` unchanged.
2. Replace source/deployment files, not private configuration. If increasing the old pool limit, change only the relevant capacity setting.
3. On a VPS, rebuild/recreate the single app service:
   ```bash
   docker compose up -d --build --no-deps --force-recreate app
   docker compose logs --tail=150 app
   ```
   On Railway redeploy the updated Dockerfile/source with the same secrets/database/volumes and one replica.
4. Run `docker compose exec -T app python scripts/live_check.py` in the **existing running app container**, after staff `/health`; native installations use their already configured environment. It never starts a user-session runtime or joins targets. Exit 2 without fresh identity/owned-call evidence is incomplete, not a failure demanding new login. See [HOST_VERIFICATION.md](HOST_VERIFICATION.md).
5. Check all three example quota combinations and short renewal; check notices and that an excluded feature remains unavailable.
6. With your authorized accounts/targets, verify one later account addition is eligible, a manual task keeps its reviewed count, automatic calls rebalance, and expiry/revoke stops automation.
7. Observe sanitized health/cleanup logs and host CPU/RAM/egress. Increase real workload in stages rather than assuming the configured maximum is a benchmark.

Automated coverage includes real Mongo, real asyncio/native-thread callback scheduling, real aiogram routing and local HTTP readiness. Telegram account/Bot API/RTC outcomes are controlled. No live OTP/2FA/QR/native attendance or VPS/Railway deployment was performed by the assistant. See [TEST_REPORT.md](../TEST_REPORT.md), [RUNTIME_LOG_AUDIT.md](RUNTIME_LOG_AUDIT.md) and [LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md).
