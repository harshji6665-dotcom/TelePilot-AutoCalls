# Staff health check — TelePilot 1.3.1

Use **manage bot → check health** or `/health`. Free/Premium customers cannot run staff diagnostics.

## What changed

The old button waited for the serialized full pool sync and then displayed generic statistics. Slow account connections/probes or a busy periodic sync could make it appear unresponsive; it also did not show what was actually checked. The user's exact live failure was not reproduced with their logs/credentials, so this update does not claim that was the only root cause.

The new button starts/reuses a **non-blocking background run** and immediately renders its status in the existing panel. Progress/results update the same screen, with **refresh results** as a fallback. You can navigate away while it runs; late results never overwrite a newer menu. A quick zero-account scan still displays its finished result. Background health completion is not treated as a critical runtime-task exit.

## What it checks

- MongoDB ping, bounded to 5 seconds.
- Bot API identity request, bounded to 10 seconds; errors are displayed as class names only, never token/error-message contents.
- Readiness and critical worker-task liveness.
- Installed call-adapter/import/API signatures. **This is not a real WebRTC call test.**
- Stored account health through a real self-user request or identity-verified fresh attach. A newly attached session is not redundantly probed again.
- Per-account health/cooldown/revocation updates and appropriate detach/alerts.

Busy, disabled, cooldown and missing-session accounts are labelled as skipped, not claimed freshly verified. Busy accounts are left alone to avoid disrupting calls/jobs. Telegram FloodWait is persisted for account probes and not retried before the deadline. A Bot API RetryAfter defers another manual run.

Concurrent staff requests share one run. Results are reused for at least 30 seconds to avoid repeated probe spam. Whole scan budget defaults to **600 seconds** (`limits.manual_health_timeout_seconds`, range 15–1800; VPS profile `MANUAL_HEALTH_TIMEOUT_SECONDS=1800`). A timeout produces a **partial** result, not a success claim. If a periodic lifecycle operation holds the pool lock too long, the manual run can time out while waiting rather than blocking navigation indefinitely.

## Read the result honestly

- **Finished** means the scan finished, not that every listed component/account is healthy. Inspect individual results.
- **Partial** means some checks did not finish within the budget; they are not assumed healthy.
- **Failed** shows a sanitized error type. Inspect logs, `/health/ready` and database/Bot API connectivity.
- **Skipped: busy/cooldown/disabled** is not a positive network check.
- Only a real owned-group live call verifies your host's RTC path. VPS/Railway NAT/UDP, CPU/native wheels and provider policies are still deployment-dependent.

UI edit FloodWait leaves the previous panel intact; the diagnostic can continue, and refresh shows results after the pause. Health state is transient RAM metadata and resets on process restart. It contains IDs/status/type information only, no session strings, passwords or OTPs.

If your health button still fails after a full rebuild, share only the **sanitized incident/error type and stack-frame names**—never bot/API/Mongo secrets, OTPs, passwords or QR tokens. The source ZIP contains tests for the new checker, but no live Telegram or hosting deployment was performed here.

1.3.0 health also reports the auto worker's local running/disabled/error state. Busy auto-call accounts are skipped just like busy manual accounts. Use manage bot → auto overview and each customer's automatic-call page for counts. These states do not replace a real RTC/host test.

Join-task diagnostics detach rejected/network-failed transports without deleting saved authorization. In 1.4.1, temporary offline/cleanup failures receive paced automatic recovery; a manual scan is optional, not mandatory for every reconnect. A genuinely unregistered/revoked authorization may still require owned-account sign-in. Test the host RTC path if failures repeat.

## Larger roster lifecycle (1.3.2)

Account-health reload is a separate critical worker; bot startup, plan expiry and login cleanup do not await a whole 200-account scan. The staff view reports whether the roster is loading. Readiness is service/task/Mongo readiness, not all-accounts-connected. Periodic sync acquires the lifecycle lock per identity, skips busy/cooldown identities and avoids probing a just-attached account twice. Login post-save attachment is tracked, cancellable and never revokes a committed session merely because a later health step failed. See ACCOUNT_CAPACITY.md.


## Disconnect futures and cleanup quarantine (1.4.0)

Terminal public Telethon disconnected futures are observed. An unexpected disconnect excludes the slot from reservation immediately and persists a typed health alert through owned background work; idle health reloads the old transport rather than demanding OTP for a network-only loss. Longer Telegram waits are preserved atomically. Native callback draining/local stop and shielded Telethon disconnect cleanup are tracked. `TransportCleanupPending` is an explicit fail-closed quarantine: do not repeatedly reattach that identity; investigate and gracefully restart if needed. The encrypted session/key are retained.

Notification failures now retain safe `error_type` + `error_category` metadata, not raw Telegram response text. A known parse/length error gets one plain-format fallback. The supplied log's unspecified BadRequest is not retroactively assigned a cause. Details: [RUNTIME_LOG_AUDIT.md](RUNTIME_LOG_AUDIT.md).


## Saved authorization is not a transport (1.4.1)

Full health probes keep their configured interval; a cheap wakeable tick recovers due failed transports/checkpoints in between, without probing healthy accounts every 15 seconds. Network/storage backoff is persisted (60–900 seconds with bounded jitter), and longer Telegram waits win. Retired cleanup can retry, but a pending/uncertain old transport cannot be replaced. Staff-disabled/removed or server-rejected identities are not silently re-enabled.

Verified `NotInCallError` / `NoActiveGroupCall` with no native connection or pending join is idempotent, not an account logout. Other leave failures remain uncertain. Generic authored control/network errors during a health scan are not mislabeled as authorization revocation. All automatic states retain existing ciphertext; wrong original keys/local format failures can retry safely after restoration. Missing legacy ciphertext is reported honestly.

Accounts shows a status-specific explanation, next recovery deadline and eligible saved-session reconnect control. This requests safe recovery without OTP or wait bypass. Recovery notices are transition-based; they are not a guarantee of ongoing Telegram/RTC availability. Read [SESSION_RECOVERY.md](SESSION_RECOVERY.md).


## Host-verifiable live evidence (1.4.2)

Health now emits an explicit identity-verified flag only after a real matching self request or a newly validated current attach. A stored healthy label alone is not proof. Full identity probes still skip busy/disabled/cooldown accounts. After that scan, one bounded read-only existing-call sample may use a current busy managed account to verify its native binding and same-call Telegram self participant, without joining/leaving, recording, new clients or wait/moderation bypass.

The aggregate export is one bounded settings record, tied to singleton/bot/code/config and stripped of account/target IDs, usernames, sessions and raw exception text. A failed export does not crash health/bot execution; the host reader then lacks valid fresh evidence. The standalone reader never takes a lease, initializes indexes, decrypts a session or starts another account client. It can report incomplete, and never certifies manual OTP/2FA/QR/UI behavior. Follow [HOST_VERIFICATION.md](HOST_VERIFICATION.md).


## Transport diagnostics (1.4.3)

Terminal sender failures exclude the slot immediately and close its native callback gate before Mongo persistence. Only error class and safe numeric wire code are emitted; raw packets/requests/exception text are not. A 404/key-not-found transport response can be temporary or permanent, not proof of a ban. A wire 429 gets at least a 900-second local cooldown, with longer waits preserved. Connect timeouts back off and retain saved sessions. Offline native cleanup never pretends a remote leave succeeded.

Source reports are not actual host acceptance: collect fresh same-runtime `/health` evidence with [HOST_VERIFICATION.md](HOST_VERIFICATION.md). The startup version now identifies deployed code. See [TRANSPORT_RECOVERY.md](TRANSPORT_RECOVERY.md).


## Confirmed session conflicts (1.4.4)

Health now reports fleet safety state and current wire-fence/ownership evidence without probing paused accounts. `/sessionguard` exposes staff view and owner-only reviewed resume; home shows zero ready accounts while fenced. `--scope safety` can inspect the incident without a new user session/call. Missing/stale proof, unknown global topology, or a paused incident cannot be called complete live acceptance. See [SESSION_SAFETY.md](SESSION_SAFETY.md).

## 200-account scan interleaving (1.5.0)

Manual health reviews up to 200 records, reloads current per-account state and holds the lifecycle lock only for one account at a time. UI/progress notifications run outside that lock. Host evidence preserves all 200 reviewed/self-verified counts. Existing busy/cooldown/auth-stop/safety-pause checks remain. A partial scan is still partial; do not weaken pacing or stop a valid call to manufacture a green report. See [VPS_200.md](VPS_200.md).
