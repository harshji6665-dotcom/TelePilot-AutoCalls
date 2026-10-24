# Changelog

## 1.5.1 — 2026-10-24 — maximum safety defaults + realistic pacing (VPS risk reduction)

- **Much more conservative default limits** to lower load and detection surface:
  - max_pool_accounts default 50 (was 200)
  - max_parallel_jobs = 1, auto_parallel_connects = 1
  - global_rpc_gap 4.5s, account_join_gap 90s, account_joins_per_day 8
  - max_auto_channels 10, max_jobs_per_user_day 4, max_call_minutes 120
  - Lower auto-call polling frequency and rejoin attempts
- Randomized realistic device/system/app profiles for every new TelegramClient (Samsung, Xiaomi, Pixel, OnePlus, iPhone, Desktop, Mac).
- Login: 45s cooldown + 2.5–6.5s delay before code request; flood_sleep_threshold=24.
- RateGate uses stronger 25–70% random jitter.
- Join gap includes large random extra (8–35s). Multi-account joins and call-joins are heavily staggered (6–18s / 5–16s).
- Goal: make traffic look less automated and reduce simultaneous connections.  
  **Important:** No code can guarantee zero VPS suspension risk when running multi-account automation + calls. These changes only reduce risk.

## 1.5.0 — 2026-10-22 — 200-account Docker VPS release

- Raised the validated saved-pool and finite account-allowance ceiling to **200**, preserving default finite Premium allowance 5, existing custom paid quotas and independent unlimited/current-future eligibility. Chat/QR/exact optional 2FA, capacity feedback and full-pool reauth remain.
- Manual health now covers all 200, re-reads account state, releases the lifecycle lock per account and performs UI progress outside it. Host identity/review evidence no longer clamps at 100; staff target correction cannot overlook busy automatic account 101–200. Default health budget 600 seconds, validated env override through 1800.
- Added bundled and standalone-external Mongo VPS profiles for **8 vCPU / 64 GB**: one worker, app 6 CPU/48 GiB, bundled Mongo 1 CPU/8 GiB, 4096 app PIDs, 65536 files, longer stop/health grace, original persistent volumes and `unless-stopped`. The profile deliberately defaults to 200 despite an old MAX_POOL_ACCOUNTS=100. External Mongo needs no local root secrets or unused database.
- Added fresh-only `setup.py --profile vps200`, explicit optional owner/database passthrough preserving private JSON, host boot/restart instructions and opt-in systemd unhealthy watchdog. Watchdog is single-container/project scoped, serialized, rechecked, throttled and does not create replicas, start an already-stopped service or clear session safety. Stop its timer before manual maintenance to avoid a race with an independent stop.
- **706 source tests passed; all 706 built-image cases passed across eight isolated fresh-Mongo batches**, retaining 641 and adding 65. Separate UID-10001/read-only real HTTP/Mongo probe covered 200 inert encrypted records, truthful incomplete/full and blocked/safety reports, unchanged ciphertexts and graceful shutdown. An actual no-network Docker fixture verified watchdog starting skip, dry-run, same-container restart/persistence, cooldown and manual-stop behavior.
- Preserved original image, key/database/volume contracts, session conflict containment, server-clock lease/wire fencing, owner review, roles/target permanence, UI/features, scheduling/fairness/manual priority, Telegram waits and native lifecycle controls. Resources do not restore already-invalidated Telegram keys or prove 200 real concurrent RTC performance/permanent uptime. See VPS_200.md and TEST_REPORT.md for migration and honest evidence/retry limits.

## 1.4.4 — 2026-10-21 — duplicated authorization containment / runtime wire fence

- New JSON evidence: 43 records, 12 transport-429 and 23 connection warnings. Message export: 56 distinct account authorizations rejected with AuthKeyDuplicatedError. This changes the diagnosis from transport-only trouble to server-invalidated keys; exact conflicting process remains unknown.
- Added fail-closed fleet safety stop on the first confirmed duplicate, including errors on SDK-internal futures even if a caller catches them. Stops additional roster connects, logins/reauth, RPC/call work; owns local cleanup without deleting credentials or marking every valid key revoked.
- Startup detects old duplicate records and partial-crash incidents newer than an old acknowledgement. Owner-only nonce/expiry/incident-bound audited review can resume only after local cleanup; it does not reset account revocation/ban flags or request OTP.
- Singleton claims now use Mongo server time, majority acknowledgement and an early 70-second monotonic packet deadline before the 90-second server lease. Checks run before primary TCP opening/actual writes, including queued packets and SDK reconnects. Heartbeat loss fences immediately; unconfirmed cleanup cannot voluntarily release the lease for immediate takeover.
- Account cooldown/ownership is checked before SDK TCP reconnect, not merely in a callback afterward. Real TelegramClient/native ownership and existing signup, roles/unlimited plans, target locks, UI/photo/force-subscribe/schedules/fairness remain.
- Added `/sessionguard`, staff-view/owner-resume controls, paused-ready UI, explicit irreversible duplicated-key hints and a read-only `--scope safety` host report with bounded local topology hints. No public control endpoint, global asyncio patch, credential export or session/IP-rotation bypass.
- **641 source + 641 built-image tests**; 34 new safety regressions and all prior 607 retained. Separate UID-10001/read-only real HTTP/Mongo probe verified both incomplete full scope and blocked safety scope, without real Telegram requests.
- The fix protects future operation. It cannot revive Telegram-invalidated keys, inventory every external service/database clone, prove network stability or replace authorized host/RTC acceptance.

## 1.4.3 — 2026-10-18 — transport future ownership / native offline cleanup

- Audited new 26-record deployment log: 8 invalid-buffer and 3 connection-ended warnings, 6 unobserved async exceptions, 2 connect timeouts and one MTProto-offline native leave. It does not establish a ban/revocation; wire code and exact running release were absent.
- Reproduced the ignored Telethon keepalive ping future with the actual pinned SDK and a synthetic error, without network. Per-instance `TelegramLifecycle` now observes original sender futures/batches, owns/drains reconnect tasks and settles queued requests only after confirmed disconnect. Awaited exceptions/cancellation remain unchanged; no global asyncio handler or SDK class patch.
- Kept the real TelegramClient class/module for PyTgCalls' module-based bridge; verified against the installed SDK.
- Added safe numeric wire-code telemetry and honest hints. Transport 404/AuthKeyNotFound remains possibly temporary/permanent, not an invented ban. Wire 429 gets a 900-second local minimum pause without shortening a longer wait. No raw packet/exception/request is logged.
- Paced recovery handshakes and SDK post-reconnect notification; rechecked saved/retired ownership, staff enabled/auth state, generation/epoch and wait after pacing. Timeouts retain ciphertext and owned cleanup, never trigger automatic OTP/logout.
- Terminal transport loss immediately closes only its native callback gate. Known-offline leave skips remote MTProto and uses owned local stop/drain/disconnect; a leave race is not claimed successful. Stale workers cannot mutate newer authorization.
- Startup now reports code version without bot identifiers. Existing sign-in/QR/exact-2FA, encryption, roles/unlimited plans/locked targets, UI/photos, force-subscribe, scheduling and allocation preserved.
- **607 source + 607 final-image tests**, 56 new cases. Real HTTP/Mongo/non-root/read-only host-reader probe passed with controlled Bot identity; actual Telegram/RTC on the user's host remains pending the sanitized host report/manual observations.

## 1.4.2 — 2026-10-16 — native authority race / host-run verification

- Closed native setup races after rate pacing/target callbacks and after SDK startup: disabled, replaced, authorization-blocked, cooldown or moderator-removed identities cannot retain newly denied call access. Failed/uncertain setup still receives owned cleanup; no session erasure or new scope.
- Added explicit fresh self-identity flags to health results, rather than interpreting an old healthy label as a new successful check.
- Added bounded in-process observation of one existing managed call: native presence plus Telegram self participant in the same call, using the existing pool only, with current authority/deadline checks. No new call, user login, publishing or recording.
- Health exports one sanitized aggregate settings record bound to runtime/bot/version and a private keyed configuration attestation. No session/account/target identifiers or credentials enter the host report.
- New `scripts/live_check.py` reads existing HTTP/Mongo/evidence and calls Bot API getMe once. It never constructs/decrypts user sessions, mutates Mongo/indexes or takes a lease. The old smoke entry point now uses this safe reader.
- Freshness, same-runtime/bot/config checks, strict projection, no-secret failure output and truthful failed/incomplete exit codes prevent untested live claims. Manual sign-in/QR/recovery/UI acceptance remains unclaimed until the operator returns evidence.
- **551 source + 551 final-image tests**, 64 cases added beyond 1.4.1. Separate UID-10001/read-only real HTTP/Mongo host-reader probe passed with controlled Telegram identity; correctly incomplete without live account/call proof.
- Full source/Dockerfile/config/deployment guides and user-selected host-run procedure included. Original key/database/volumes, exact image, role/Premium/unlimited/target/moderation/rate constraints remain.

## 1.4.1 — 2026-10-16 — durable saved-session recovery

- Audited the newest 27-record attachment: 21 `NotInCallError` warnings and 6 informational records, no proven authorization revocation/ban/logout. No raw production IDs/logs are shipped.
- Verified native already-absent leave is idempotent only with an empty binding map and no pending join; other failures stay quarantined. Cleanup respects persisted waits and records native-leave FloodWait/auth errors.
- Automatic health errors never erase encrypted authorizations. Confirmed bans disable automation; generic deactivation is distinct. Legacy missing ciphertext is reported honestly, not claimed retained.
- Wakeable local recovery between full scans, persisted bounded backoff, longest-wait preservation, one-pass reattach and owned retry of completed cleanup failures. Pending cleanup never permits duplicate attachment.
- Identity-validated encrypted DC/key checkpoints, authorization/transport CAS fences, post-pacing RPC checks, clean-migration observer handling and owned in-flight attach shutdown.
- Reauth cancellation/failure retains the original saved account. Successful replacement rechecks role/identity/busy/staff revision; ambiguous Mongo acknowledgement cannot trigger logout of a possibly saved key. Temporary login transports transfer to pool ownership before storage.
- Restored original keys can recover retained decrypt/format failures without OTP after paced validation. Known server-invalidated or mismatched sessions are not auto-retried; no ban/Telegram bypass.
- Accurate per-state notices and saved-session reconnect panel; existing plans, unlimited modes, target locks, bans, deadlines, counters and original image remain.
- Recursive Docker context exclusions prevent nested bytecode, private config and local session files entering the runtime image.
- **487 source tests and 487 built-image tests passed**, plus a separate UID-10001/read-only real HTTP/Mongo probe. These are controlled Telegram outcomes, not live Telegram/RTC/hosting acceptance. See TEST_REPORT.md and docs/SESSION_RECOVERY.md.

## 1.4.0 — 2026-10-16 — unlimited Premium + owned transport cleanup

- Independent `unlimited` account/channel quotas in commands and wizard, explicit nullable schema 3 flags, dynamic future-pool allowance, short-renewal preservation, finite switch/downgrade protection and accurate panels/help/notices/audit metadata.
- Deployment-bounded worker entitlement keeps all existing feature/expiry/target/role/locked-slot/FloodWait/manual-priority/deadline guards. Manual tasks retain concrete reviewed counts; automatic calls use later eligible pool additions.
- Audited supplied log without copying identifiers: observed terminal Telethon futures; owned/gated/drained pinned native callbacks and only their Raw handlers; shielded owned disconnect/detach cleanup; quarantine unproven transports; join SDK executor off the loop; truthful typed leave failures; atomic longest-wait preservation.
- Safe HTML/UTF-16 notification bounds, one known formatting fallback, permanent-rejection handling and safe BadRequest categories; sanitize raw asyncio task/future reprs without disabling lifecycle errors.
- Added 83 automated cases beyond 317. Full source suite: 400 passed; final container/packaging verification in TEST_REPORT.md. No live Telegram/RTC/production deployment or 200-account capacity claim.
- Retain private phone/OTP/exact-2FA/QR behavior, encrypted sessions/key/database/volumes, exact image, public/private joins, capacity override, force subscriptions, start-photo controls and all prior regression coverage. New schema requires compatible rollback planning.


## 1.3.2 — 2026-10-15

- Fix identified 20-account enrollment ceiling: new validated default/templates 100, MAX_POOL_ACCOUNTS nested-limit override (including old private JSON), common capacity checks for chat/browser/completion and explicit full-pool guidance. Existing custom limits remain intentional; no silent deletion or unlimited enrollment.
- Add staff read-only pool-capacity view and visible blocked-add panel. Render callback errors instead of relying on a second ignored popup after an early ACK; ACK network failure and FSM-state errors no longer skip independent recovery. Actual Telegram rate pauses remain honored.
- Saved encrypted login sessions no longer wait for whole-pool health loading. Managed/cancellable post-commit attachment, bounded identity lookup and fresh staff/expiry check preserve committed sessions even if later health fails. Consent, exact OTP/2FA parsing and QR paths retained.
- Separate account-health startup/periodic worker keeps bot polling, plan expiry and dialog cleanup responsive during large roster loading. Per-account lifecycle locking, skip busy/cooldown, no double probe after attach, and untruncated free-pool selection after busy prefixes.
- **316 passed on host; 317 passed in the built Docker image (49.21 s)** after adding a real-loopback HTTP test. Real disposable Mongo, controlled Telegram/RTC; Docker build, non-root read-only SDK/ffmpeg checks passed. An earlier reused-test-database memory stall is disclosed, not counted as passed. No live Telegram login/RTC or production deployment performed.
- Existing paid limits, permanent channel slots, forced-subscribe roles, auto allocation and original image/key/database contracts retained. Added ACCOUNT_CAPACITY.md and safe upgrade/live acceptance guidance.

## 1.3.1 — 2026-10-14

- Normalize public channel/supergroup join tasks to current @username and native JoinChannelRequest, including old queued/resumed jobs; private targets keep the bot-managed request invite. Validate submitted links, ownership and numeric entity identity; Telegram approval responses remain request_sent, not joined.
- Serialize whole per-account membership attempts with a separate join lock; re-read day/cap/health/cooldown after waits and bound public entity lookup. Revoked/failing network identities detach and are not immediately reused as healthy.
- Fix start-photo visibility: a fresh acknowledged photo above fresh text on every explicit /start, not an edit of an old banner. Default Telegram file-ID caching avoids repeat PNG uploads without suppressing sends; bot/checksum mismatch and invalid IDs fall back safely. Ordinary navigation keeps editing; QR remains transient/separate.
- Owner photo settings panel with set/preview/explicit on/off/default, 15-minute actor-bound input, fresh owner checks and persisted visibility. New JSON/env default with optional Compose passthrough; preference survives restart. Optional media failure remains bounded/text-fallback-safe and actual RetryAfter is never bypassed.
- Protected error-type summaries/task-details buttons, per-account authored recovery hints and code-formatted audit JSON/IDs. No raw exception/credential contents shown. Provided audit partial rows do not identify exact RPC failures; revoked sessions need re-authentication.
- **292 tests passed in 37.90 seconds**, real isolated Mongo, controlled Bot API/Telegram/RTC; 29 new cases beyond 1.3.0. Ruff/syntax/config/adapter/manifest checks passed at packaging. No live Telegram, Docker image, VPS/Railway deployment or independent vulnerability/penetration scan performed.
- Preserve original login implementation, encryption key/database/volumes, paid access/locks, force-subscribe/auto opt-ins and exact supplied banner. New PUBLIC_JOINS_PHOTOS.md and updated acceptance/upgrade docs.

## 1.3.0 — 2026-10-13

- Explicit /start sends a visible fresh panel and removes the old text panel only after acknowledgement; ordinary navigation remains editable/deduplicated. Commands are cleaned after successful response, while credentials remain immediately cleaned. Optional banner errors cannot swallow the home response. Error replies no longer depend on the same failing owner outbox or edit path. Stale/non-password sign-in states can reopen home; exact slash-prefixed 2FA remains intact.
- Real aiogram dispatcher/update/session tests reproduce /start and callback routing with production-style bot-authored anchors; all prior chat/QR login and smallcaps regressions retained.
- Owner-only required-subscription add/remove/review/view; admins view only, staff exempt. Public/private managed links, all-membership gate, correct restricted/left/kicked/request states, cache invalidation, bounded concurrency/timeouts and RetryAfter. Direct automation entitlement checks prevent UI/callback bypass. A kicked bot does not strand owner requirement removal.
- Opt-in periodic detection of native calls on saved authorized channels; exclusive account sharing with capped equal water filling and stable integer remainders. Automatic joins never create a call/publish media. New target registrations remain off.
- Dynamic redistribution on starts/ends, purchased account caps, manual-job headroom/same-chat suppression, only one enabled auto owner per physical chat, staff overview and current connection status.
- Durable per-call IDs/deadlines/block sets; restart/toggling/redistribution do not reset safety caps. New auto episodes are daily-limited. Privately inaccessible detector entities use only authorized saved invites. Revoked detector sessions detach; explicit target control/plan/membership failures stop retained calls rather than using timeout grace.
- Bounded native startup/connection setup and cancellation cleanup, pending-join/uncertain-leave transport retirement, fail-closed stale probes and early callback spinner acknowledgement. Account recovery metadata is cleared once before manual/auto workers start; automatic diagnostics and calls stop before pool teardown.
- **263 automated tests passed in 40.90 seconds** at the recorded full run, real disposable Mongo and controlled Telegram/RTC outcomes. No actual Telegram call, Docker image build, live VPS/Railway deployment, penetration test or dependency vulnerability scan performed.
- New FORCE_SUBSCRIBE.md and AUTO_CALLS.md; updated deployment, privacy, architecture, audit and acceptance guides. Original key/database/sessions, prior Premium allowance and exact supplied banner retained.

## 1.2.0 — 2026-10-13

- Channel-only, calls-only and both feature plans; hide unavailable automation buttons and enforce the chosen feature in confirmation/create/worker/pacing/call-loop checks. Changes cancel newly disallowed tasks.
- Per-plan permanent saved channel/group quotas (new default 1, global configurable maximum 100); users cannot remove/recycle a target across renewal/expiry/revocation. Only owner/admin audited corrections can free a slot. Shared plan/target locks prevent quota races; unsafe downgrades below saved count are rejected.
- Staff button wizard for user → feature → days → channel slots → account cap → set/extend → review. Actor-bound request keys prevent duplicate extension, and real bot-authored callback anchors do not become the grant actor.
- New explicit /premium syntax and /premiumhelp; update plan/home/help/user notifications, paginated channel/target selectors and staff correction forms. Old short commands preserve existing feature/slot restrictions.
- Idempotent leader-only legacy migration preserves both features, original expiry/account caps and old 10-target allowance (or existing count if higher); locks customer targets without deleting data. New-schema plans/staff test targets are not overwritten.
- ADMIN_USERNAME environment/JSON contact button, with validation and legacy support fallback; VPS Compose actually passes .env contact configuration.
- Reworked health button and /health: bounded non-critical background report, database/Bot API/worker/adapter checks, real account identity probes, explicit busy/disabled/cooldown skips, recent-run reuse, RetryAfter handling and stale-view-safe editable updates. A zero-account completion race is handled; no real-call success is implied.
- Shutdown cancels manual diagnostics/periodic lifecycle changes before pool cleanup. Working private-chat sign-in, exact supplied image, encryption, editable smallcaps and previous safety/platform fixes retained.
- **201 automated tests passed in 15.82 seconds** at the recorded full run. Real disposable Mongo; Telegram/Bot API/RTC outcomes controlled. No live Docker/VPS/Railway deployment or independent penetration/vulnerability scan performed.
- New docs SUBSCRIPTIONS.md and HEALTH.md, updated deployment/audit/live acceptance instructions. Keep the original key/database, rebuild, run one replica. Do not roll back to old unenforced quota/feature code while promising the new restrictions.

## 1.1.0 — 2026-10-13

- Private navigation edits one durable text panel per user; `/start` reuses its own banner. Identical screens skip edits, explicit `/start` repairs reported missing messages, and panel IDs survive restarts.
- Default smallcaps messages/buttons without an initial Latin capital. Protected commands, links/usernames/email, code/pre and button payloads retain exact values. Plain mode remains available for accessibility.
- Shorter English menus and split quick guide/safety help; best-effort command/form cleanup. Genuine notifications and transient QR sign-in photos are deliberately separate.
- Unified panel/banner FloodWait handling and safe callback alerts avoid recursive error rendering. Bounded metadata cache and delayed-write recovery avoid resending an already accepted panel after a Mongo write failure.
- Per-user callback/text serialization; inline password-cancel controls on edited panels. The working chat phone/OTP/optional 2FA flow and QR remain, including exact password/leading slash handling.
- Stable user-bound draft job IDs make create retries idempotent. Shared plan mutation locks and target/job locks close grant/expire/revoke, duplicate registration and removal/creation races; failed setup revokes newly created invites.
- Mongo operation deadlines and hot-query/TTL indexes; disabled-account native-call check; independent bounded disconnect and parallel call cleanup; bulk busy metadata with reservation-failure rollback and all-slot RAM release.
- Dedicated UI/recovery/privacy/concurrency regressions plus all previous tests: **154 passed in 14.26 seconds** at the recorded run. Lint/format, compile/import/signature, pip, shell/template checks are recorded in TEST_REPORT.md.
- Documentation includes CLEAN_UI.md and AUDIT.md. No real Telegram UI, Docker image build or Railway deployment was performed here; live acceptance remains required. Existing production encryption key and database must be preserved.

## 1.0.2 — 2026-10-12 · Private-chat sign-in and SDK migration fix

- Default LOGIN_MODE=chat; no browser code/site for owner/admin account login.
- Private chat nonce/consent/phone/OTP/optional 2FA, best-effort immediate input deletion, bounded attempts/timeouts/cancel, role checks and no credential FSM/storage/logs.
- Optional in-chat QR PNG/native Telegram device approval, explicit actor check and optional 2FA; QR/client cleanup after check/timeout/cancel.
- Full-session/E2E/Telegram-retention warnings; OTP expiry never prompts code-disguising/verification-bypass tricks.
- Re-auth disables only after consent, enforces original ID/ownership/busy state and pending-account claim.
- Fixed reproduced Telethon no-follow-up DC migration generic ValueError with bounded retries and raised original RPC error; positive FloodWait still surfaces immediately.
- Persisted actor login FloodWait across fresh dialogs/restarts; preserves exact password text including leading / instead of treating it as an admin command.
- Mongo session acknowledgement is commit point; later disconnect/notification failure does not revoke an already saved session.
- Legacy browser implementation remains explicit opt-in only; default portal routes return 410, health/PORT/Railway bootstrap retained.
- Added qrcode/pypng pinned renderer and updated setup/config/docs/tests. Original encryption key/database are unchanged by code update.
- Full test suite: 117 passed, real local Mongo and SDK mock-transport internals; live Telegram/QR/Docker/Railway not verified.

## 1.0.1 — 2026-10-12 · Railway startup fix

### Root-cause fix
- Removed image-level requirement for an unmounted `/app/config.json`.
- Image includes only a public `config.example.json`; private `.env`/`config.json` remain excluded.
- External JSON remains supported; environment-only deployment now supplies required settings through validated service Variables. Explicit `CONFIG_PATH` still fails clearly if missing.

### Railway compatibility
- OWNER_IDS CSV/JSON and OWNER_ID alias; no invented default owner.
- Required credential aliases and exact public URL/domain fallback.
- Dynamic PORT binding and port-aware Docker healthcheck.
- Allowed Railway healthcheck Host without disabling general Host/Origin checks.
- Early HTTP liveness, singleton handover wait and login-API readiness gate. No account clients or polling before leadership.
- Authored startup diagnostics and complete-Fernet-key guidance; no credential dumps or automatic key replacement.
- Optional file-log failure falls back to sanitized console logging.
- Offline standard-library key-generation utility and Railway deployment guide.

### Verification
- New environment/bootstrap/host/port/handover/security regression tests.
- Full test suite: 97 passed against a disposable real local MongoDB; Telegram/RTC outcomes still mocked.
- Real local HTTP startup test and a Docker filesystem-layout simulation without config.json.
- No live Railway redeploy or Docker image build was performed in this workspace.

## 1.0.0 — 2026-10-12

Initial Docker Compose/VPS source release: role hierarchy, encrypted account login, manual Premium plans, controlled targets, persisted scheduling, native group-call adapter, health/audit/outbox and fallback start photo. 74 automated tests passed in the original verification environment. The original Dockerfile required a Compose config bind mount and was not environment-only Railway-ready.
