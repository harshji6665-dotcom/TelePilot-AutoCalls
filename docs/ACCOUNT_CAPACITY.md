# Account capacity — 200-account support (1.5.0)

The global pool has a validated **1–200 saved-account ceiling**, with a new-install default of **200**. This is not an unlimited fleet or evidence of 200 simultaneous real Telegram/RTC calls. The 8-vCPU / 64-GB Docker deployment is documented in [VPS_200.md](VPS_200.md); use that resource profile rather than the smaller base container limits.

## Existing installations: preserve data, explicitly choose the host capacity

Never replace private `.env` / `config.json`, rotate the original session encryption key, delete the database/volumes, or run another worker beside the current one. Extract the public source into staging first; the archive's config is not your private config. Follow [VPS_200.md](VPS_200.md), section 3.

For ordinary direct Docker / service environment configuration:

```dotenv
MAX_POOL_ACCOUNTS=200
```

A nonblank override changes only `limits.max_pool_accounts`; absent/blank preserves an existing intentional private JSON cap (including 20 or 100). Recreate/redeploy after changing container environment; a plain restart does not apply new env values. `default_plan_accounts` must fit inside the chosen host cap and stays **5** by default. Legitimate custom business allowances are not rewritten.

For the recommended VPS profile:

```sh
docker compose -f compose.yaml -f compose.vps200.yaml up -d --build
# Or, with the original external Mongo/key, use ONLY:
docker compose -f compose.vps200.external.yaml up -d --build
```

Choose the correct one, under the original Compose project identity. Both profiles deliberately use `VPS_MAX_POOL_ACCOUNTS` with default **200**, superseding a stale `.env` `MAX_POOL_ACCOUNTS=100` or JSON cap of 20. Set `VPS_MAX_POOL_ACCOUNTS=100` (or another supported 1–200 value) only when you deliberately want a smaller operational ceiling. Profiles do not scale the app.

For Railway, the same `MAX_POOL_ACCOUNTS=200` is supported in Variables, but this is not a promise that a provider's assigned memory/CPU/PID limits support 200 native instances. Use one replica and assess the actual host; the selected deployment for this release is the VPS.

## What is counted and preserved

- Every saved account record consumes a slot, including disabled/revoked accounts. New login completion rechecks count atomically against concurrent staff completions; the last free slot cannot be overfilled.
- Authorized reauthentication of an existing record remains possible at a full pool, subject to role/consent/busy/safety rules. Saved sessions are not deleted to make space. Signup, QR and exact optional 2FA are retained.
- Manage bot → **pool capacity** / `/capacity` reports effective capacity and saved/attached/healthy/busy availability. A full-pool callback sends a visible panel/message result, not a second ignored callback popup.
- Finite paid allowances remain finite. Staff may deliberately grant a finite **200**, or independent account/channel **unlimited**. Unlimited resolves against the current operational ceiling and eligible pool; new eligible accounts become available without rewriting the plan. It never overrides feature tiers, Telegram waits, permanent target quotas or host ceilings.
- Allocation uses healthy, enabled, attached, non-cooldown and free slots only. The requested count is not silently reduced. Pool ownership is exclusive, automatic shares are per channel, and manual work has priority.

## Large-roster operation

Startup loads saved accounts in a separate worker so bot readiness and `/start` do not await the whole fleet. Periodic and manual health operations release the lifecycle lock per account; manual progress/UI updates happen outside that lock and reload each account's latest state. Both cover account 200 rather than truncating at 100. Lightweight recovery ticks do not RPC-probe all healthy sessions every 15 seconds.

Manual health defaults to **600 seconds** outside the VPS profile; supported range **15–1800**. The VPS default is `MANUAL_HEALTH_TIMEOUT_SECONDS=1800`. Roughly 400 seconds are needed for 200 successful globally paced identity RPCs alone; cold attach, waits and migrations can take longer. Partial results remain partial. Busy calls and blocked authorizations are not disconnected merely to obtain a health proof.

The VPS app limit is 4,096 PIDs/threads and 65,536 open files, with a 48-GiB / 6-CPU ceiling, 300s stop grace, persistent data and `unless-stopped`. See the full guide for the separate 8-GiB / 1-CPU bundled Mongo envelope and optional host watchdog. Health status alone does not make Docker restart a container unless that optional watchdog is installed.

No join/day/RPC pacing, native setup concurrency, call duration, moderator restrictions, channel quotas or owner-review safety gates were increased. Already-invalidated keys still require authorized login after conflicting copies stop; RAM and retries cannot restore them.

## Verification boundaries

Automated regressions include enrollment at the 200th slot, concurrent final-slot completion preserving 199 original synthetic ciphertexts, full-pool reauth, finite/unlimited plans, 200-slot exclusive reserve/release, 200 identity checks, per-account lock interleaving, fresh state, recovery/shutdown/duplicate containment, busy-account-200 target correction, and fair 200/4 sharing with manual-priority headroom. Mongo is real and disposable; Telegram/RTC identities and outcomes are synthetic.

Built-image and restricted real HTTP/Mongo checks are documented in [TEST_REPORT.md](../TEST_REPORT.md). No user-VPS deployment or 200-account live Telegram/RTC benchmark is claimed. Complete [LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md) in stages on the real host, with one guarded runtime and the original key/database.
