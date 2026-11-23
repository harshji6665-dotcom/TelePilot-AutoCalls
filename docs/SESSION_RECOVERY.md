# Saved-session recovery — TelePilot 1.4.1

Prepared **16 October 2026**. Keep the **original encryption key, database, private configuration and volumes**. This update is not a guarantee of uninterrupted Telegram access or immunity from restrictions.

## What the supplied log actually shows

The newest attachment contains **27 records: 21 warnings and 6 informational records**. All 21 warnings are `Call leave failed … NotInCallError`. It does **not** show an authorization-revoked/expired/duplicated error, a ban or an actual Telegram logout. Raw logs, real account IDs and credentials are not included in this project.

The pinned PyTgCalls 3.0.0 implementation raises `NotInCallError` when the native binding has no connection for that chat. The previous generic leave-failure path retired the entire local account transport even for this already-absent call. That is a local disconnect, **not** `TelegramClient.log_out()`. It could make a valid saved account look unavailable; these logs alone cannot prove why a user subsequently chose or needed sign-in.

Separate code review found other problems: automatic authorization-status changes deleted ciphertext; recovery could wait another full five-minute scan or remain stuck behind failed cleanup; DC/key changes were not checkpointed; reauthentication disabled the old account before success; stale workers and ambiguous storage acknowledgements needed stronger protection. The release addresses these application issues without pretending the attachment proves every failure occurred.

## New behavior

### 1. Already absent is not an account logout

Only the pinned SDK's `NotInCallError` / `NoActiveGroupCall` are idempotent **when the native binding's calls map confirms absence and no join is pending**. No warning/transport retirement is generated for that verified case. A generic network failure, failed calls-map read, remaining native connection or pending join is still uncertain and stays fail-closed.

Native call cleanup does not end the whole group call (`close=False`). During a saved cooldown, authorization stop, removal, stale ownership or unavailable database, cleanup uses owned local shutdown rather than sending another MTProto leave request. A FloodWait reported by a leave is persisted before recovery.

### 2. Encrypted authorization survives automatic failures

Automatic `offline`, cooldown, revoked, deactivated, banned, identity-validation and storage-error handling **does not erase `session_ciphertext`**. Identity-validated checkpoints or an explicitly authorized successful replacement can update session material; only explicit local removal deletes its stored record. Confirmed bans disable automation. A generic deleted/deactivated account is no longer falsely classified as a proven ban.

Preserving rejected ciphertext does **not** make it usable. Known revoked/expired/duplicated/deactivated/banned authorizations and identity mismatches are blocked from automatic use. No automatic OTP, QR approval, password request or fresh Telegram authorization is attempted.

### 3. Paced saved-session reconnect

- Full health probes keep `limits.health_interval_seconds` (default 300 seconds).
- A wakeable local recovery check runs in between, at most approximately **15 seconds** apart when the worker is available. Healthy accounts are not RPC-probed every tick.
- Connection/storage failures get persisted exponential backoff: initially **60 seconds**, then roughly 120/240/480 seconds, capped at **900 seconds**, with bounded jitter. Actual recovery can be later because of pacing, busy jobs, cleanup, scan duration, unavailable dependencies or longer server waits.
- Both `next_recovery_at` and `cooldown_until` must be due. Atomic `$max` prevents a shorter new wait from replacing a longer Telegram wait. Staff reconnect does not shorten these waits.
- A disconnected transport is cleaned and reattached in the same due pass, not deliberately deferred for another full health interval.
- Failed **completed** disconnects and retired local cleanup can retry; a still-pending disconnect remains strongly owned and is never replaced in parallel. Unconfirmed native cleanup remains quarantined. Local cleanup retries are also paced.
- A per-account attach registry prevents concurrent public attach calls from opening duplicates. Shutdown owns/cancels/gathers in-flight attachment and cleanup.

Recovery checks current roles/enabled state, saved identity and connection ownership. It never enables a staff-disabled account, resurrects a removed record or clears automatic-call moderator block lists. Runtime forbidden-chat guards carry across reconnect. Existing plan/target locks, paid tiers/unlimited allowances, daily join counters, deadlines and host limits remain.

### 4. Validated DC/key checkpoints

Telethon's session-save callback schedules an owned checkpoint when nonempty DC/key material changes. A matching raw `GetUsers(InputUserSelf)` response must validate the saved account ID before encryption/persistence. Empty intermediate migration keys and mismatched identities never overwrite the last saved ciphertext.

`session_generation` fences authorization replacement; `connection_epoch` fences a particular transport. Atomic compare-and-set updates prevent old watchers, probes, jobs, cooldowns or checkpoints from damaging a replacement. Plain sessions/keys are not logged or written to an unencrypted local journal. Checkpoints still require a working MongoDB; a process/storage loss before durable acknowledgement cannot be magically recovered.

A clean Telethon DC reconnect does not mark an already-connected replacement transport offline. Queued application RPCs recheck authority, ownership and waits after global pacing.

### 5. Cancel-safe sign-in replacement

Opening/consenting to phone or browser/QR reauthentication keeps the old saved account unchanged. Cancellation, wrong credentials, wrong identity, expiry or authority loss before commit does not disable its valid authorization.

Only after successful login are role, original ID, account generation, staff revision, existence, capacity and busy state rechecked. Old local transport cleanup must be confirmed before the authorized replacement is saved. A staff disable/removal or newer authorization during the dialog invalidates that stale dialog. The old transport is retired before the replacement is committed; the newly saved StringSession cannot be attached again while its temporary login transport cleanup is pending. The fresh temporary authorization can coexist with the old saved authorization during the pending dialog; it is not a clone of the old key.

A temporary authorized login client transfers to strong pool ownership **before** storage is attempted. If Mongo's acknowledgement is lost, the primary is checked for the new generation. A possibly committed authorization is never remotely logged out merely because confirmation failed; the user is told to check Accounts/Mongo before requesting another OTP. A truly uncertain failed write can leave an unused device authorization: review Telegram **Settings → Devices**. This is preferable to invalidating a key that may already have been saved.

Unambiguously unsaved, rejected/abandoned temporary authorizations still receive best-effort logout for security. This is not a logout of an existing saved account. Successful replacement disconnects the old local client; review old Telegram device authorizations separately if desired.

## Account panel and status meaning

| State | Meaning / action |
|---|---|
| `healthy` | Saved session connected; no new sign-in needed. |
| `offline` / cooldown | Saved authorization retained. Wait for paced automatic recovery; check networking/host RTC if repeated. |
| `TransportCleanupPending` | Old local transport cleanup is uncertain. Recovery retries safely; no duplicate replacement is permitted. Investigate/restart gracefully if it persists. |
| `disabled` | Staff disabled it; automatic recovery never overrides that choice. |
| `storage_error` | Restore the **original** key/database or repair the encrypted record from a compatible backup. Paced local validation automatically retries; once decryptable, correct and accepted by Telegram, it can reconnect without OTP. |
| `revoked` | Telegram rejected the authorization. Retained ciphertext is not a repair; genuinely revoked/expired/duplicated keys generally require authorized sign-in again. Stop duplicate runtimes first. |
| `deactivated` | Telegram reported deletion/deactivation, not necessarily a ban. Account use stops. |
| `banned` | Telegram reported a confirmed ban; automation is disabled. Do not bypass it. Use Telegram's official review/appeal process. |
| `reauth_required` | Identity/authorization needs staff review. Mismatched sessions are not silently substituted. |
| Missing ciphertext | No saved authorization remains in this database. Code cannot reconstruct an erased key. Restore a compatible valid backup or sign in again. |

Eligible enabled accounts have a **reconnect saved session** control. It requests the same safe recovery worker, not OTP, and cannot bypass a wait, staff disable or confirmed authorization stop. Health alerts now distinguish temporary disconnect from server rejection, and recovery notices are deduplicated by transition.

## Upgrade without losing accounts

1. Take a protected Mongo backup and separately retain the original `SESSION_ENCRYPTION_KEY` in a password manager. Preserve the original private JSON/env, bot/API/owner IDs, Mongo URI/database name and volumes.
2. Unpack the new source in a **new release directory**. The ZIP's `config.json` is a public starter, not your private production configuration. **Never copy it over your working private config.** Use your existing external configuration/env instead.
3. Stop the old application cleanly; keep Mongo/data volumes. Do **not** run `docker compose down -v`, delete account documents, rerun key generation or change the database to an empty namespace.
4. Rebuild the supplied Dockerfile; deploy **one replica/worker** against the existing database. Do not clone StringSessions onto another host. Keep the Mongo singleton lease; after abrupt failure let the old lease expire.
5. Check `/health/live`, `/health/ready` and Accounts. Service readiness is not proof that every account is connected. Allow persisted cooldown/recovery deadlines to expire.
6. For a temporary fault, prefer saved-session recovery, not repeated phone login. If ciphertext is missing from an older release, only a compatible backup with the original key and still-accepted Telegram authorization can help; otherwise new sign-in is necessary.
7. Run the live acceptance checklist on your own authorized host/accounts before broad use. See [DEPLOYMENT.md](DEPLOYMENT.md), [RAILWAY.md](RAILWAY.md) and [LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md).

Session metadata is upgraded lazily; no database reset or encryption-key migration is required. Keep schema-3 unlimited-plan compatibility when considering rollback. Old code also contains the session-clearing/early-disable behavior fixed here, so blind rollback is unsafe.

## What cannot be promised

Telegram can revoke/expire keys, terminate devices, detect duplicated authorizations or restrict/ban accounts. Network/RTC, storage, hardware and provider failures also exist. This code cannot prevent bans, restore a server-invalidated key, retrieve erased secrets without a valid backup, bypass 2FA/approval/moderation or promise zero downtime. Keep the conservative pacing, use only authorized accounts/targets, avoid spam/unsolicited automation and comply with Telegram/provider rules.

Current 1.4.4 verification retains these fixes: **641 tests passed from source and 641 against the final image**, plus separate non-root/read-only real HTTP/Mongo checks. Telegram/Bot API/RTC outcomes in the suite are controlled; no live Telegram login/call or production deployment was performed. Exact evidence: [../TEST_REPORT.md](../TEST_REPORT.md).


The 1.4.2 native authority race fix and user-selected, session-safe live host procedure are in [HOST_VERIFICATION.md](HOST_VERIFICATION.md). Your real Telegram/RTC result is not claimed until you run and return that evidence.


## 1.4.3 / wire errors do not automatically mean logout

The supplied transport log prompted per-client Telethon future ownership, paced SDK callback/handshake recovery, safe numeric 404/429 diagnostics and local-only native cleanup after MTProto loss. An unknown key can be temporary or permanent; 429 uses a conservative local minimum rather than inventing a retry-after. Saved ciphertext and the original key/database are retained. No OTP/remote logout or restriction bypass is automatic. Exact analysis and deployment steps: [TRANSPORT_RECOVERY.md](TRANSPORT_RECOVERY.md).


## 1.4.4 / confirmed duplicate authorizations are different

The latest export explicitly records AuthKeyDuplicatedError for 56 distinct accounts. Those managed authorization keys were invalidated; encrypted retention does not revive them. Stop parallel/copy workers first, including same-IP main sessions. Fleet safety now contains the first confirmed duplicate, even inside SDK-caught requests, and boots paused for an unreviewed/new incident. Owner review cannot clear per-account revocation/bans; authorized new login is required for invalidated keys only after the cause is resolved. Server-clock/majority leasing, early monotonic wire fencing, pre-connect checks and cleanup-aware handover strengthen single-runtime ownership without claiming control over other tools/database clones. Read [SESSION_SAFETY.md](SESSION_SAFETY.md).
