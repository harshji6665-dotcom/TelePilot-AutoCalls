## 1.5.0 / 200-account VPS expansion

The 8-vCPU / 64-GB request intentionally raises the bounded pool/finite account allowance ceiling to 200; it does not raise customer defaults, channel/business/rate/call-duration restrictions. Manual health's old 100-row truncation and whole-roster lifecycle lock were fixed, identity/review evidence covers 200, and staff corrections now inspect every busy automatic account. All original encrypted records and session ownership/owner-review gates remain.

Added 65 regressions for 200-record enrollment/races/reauth, finite/unlimited quotas, exclusive allocation, health interleaving/state reload, periodic/recovery/shutdown/containment, busy-account-200 target safety, fair automatic shares/manual priority, VPS setup/resources and a fail-closed opt-in host watchdog. Full source: 706 passes. Final built-image/probe evidence and environmental retry disclosures are in [TEST_REPORT.md](../TEST_REPORT.md). No actual 200-account Telegram/RTC test or user-VPS deployment was performed.

[The VPS guide](VPS_200.md) separates new setup from original-key/database/volume/project-preserving migration and correct bundled/external Mongo profiles. Docker restart policy alone does not act on merely unhealthy containers. The optional watchdog uses one existing app container, a host lock, rechecks and 15-minute cooldown; it cannot clear session safety and must be stopped before manual maintenance to avoid an inspect/restart race.

Historical findings below retain their original release context; 100-account ceilings described in older sections are superseded by 1.5.0.

## 1.4.4 / new confirmed authorization-loss evidence

- JSON: 43 records, 8 info/35 warnings, including 12 transport-429 and 23 connection-ended events; startup identifies 1.4.3. Message export: 56 duplicated-key notices for 56 distinct accounts, plus 23 connection notices; union 57 identifiers. No raw identifiers/export content enter code/tests/archive.
- Official protocol documentation says duplicated main sessions can conflict on the same or different IPs; the affected authorization was already invalidated. Exact responsible process/connection remains unknown. User selected unsure about topology; no production/provider access or fresh host report was provided.
- Added first-error fleet containment on all sender futures, durable partial-crash-aware pause, cleanup-aware owner-reviewed resume, server-clock majority lease and early monotonic actual-write fencing. Pre-TCP SDK reconnect checks honor waits. No per-account auth stop is cleared or ciphertext erased.
- Added session-safety UI and read-only safety-scope/topology-hint report. It cannot certify all external copies stopped or repair invalidated keys. Stop copies and review before authorized reauthentication, not mass retries.
- **641 source + 641 final-image cases**, 34 new cases and all prior 607 retained. Separate actual HTTP/Mongo/non-root/read-only probe passed, including blocked safety scope with recorded duplicate evidence and unchanged ciphertext. No real Telegram login/call or deliberate duplicate session was used by the assistant.

See [SESSION_SAFETY.md](SESSION_SAFETY.md) and [../TEST_REPORT.md](../TEST_REPORT.md). Earlier entries below are historical.

## 1.4.3 / supplied transport log

- New 26-record log: 8 InvalidBufferError connection warnings, 3 ConnectionError connection warnings, 6 unobserved async errors, 2 connect timeouts and 1 MTProtoClientNotConnected leave. No wire code/exact startup version or proof of ban/revocation is supplied.
- Actual pinned SDK reproduction: ignored keepalive ping future can receive a terminal error and produce an unobserved exception even when another await added a reconnect getMe traceback to the shared exception. Fixed owner retrieves the actual original futures without suppressing global asyncio errors or altering real awaiter results.
- Per-instance task/future cleanup, exact TelegramClient bridge identity, fresh reconnect/handshake fencing, safe wire-code classification/backoff and offline native local cleanup added. Original key/ciphertext/data/roles/plans/targets preserved; no automatic OTP/logout.
- **607 source + 607 final-image cases**, including **56 new**. Separate actual HTTP/Mongo/non-root/read-only reader probe passed with controlled Bot identity. Real Telegram/user-host RTC acceptance remains pending; no production credentials or calls were used by the assistant.

See [TRANSPORT_RECOVERY.md](TRANSPORT_RECOVERY.md), [HOST_VERIFICATION.md](HOST_VERIFICATION.md) and [../TEST_REPORT.md](../TEST_REPORT.md). Earlier entries below are historical.

## 1.4.2 native authority race / host-run verification

- No new error attachment was supplied. The delivered 1.4.1 ZIP/working source were checked before changes; existing 487-test evidence was not relabeled as live Telegram testing.
- Further source review found native SDK play lacked the post-gate/callback and post-start authority fencing already used for ordinary RPCs. Regression tests now cover disable, replacement, authorization stop, FloodWait, moderation and late native success.
- Explicit fresh identity proof, one existing-call server/native presence observation, closed sanitized health export and an independent read-only host reader complete the user's chosen safe test path without duplicate user-session clients.
- Reader freshness/runtime/bot/config/lease checks and failure/incomplete status prevent accepting skipped/stale/malformed results as live passes. It never echoes private data or marks manual acceptance complete.
- **551 source + 551 built-image tests** and a separate non-root/read-only actual HTTP/Mongo/reader probe passed with controlled Telegram outcomes. No real user host, Telegram sign-in or actual RTC call was accessed. Live acceptance remains pending the user's sanitized host report and manual observations.

See [HOST_VERIFICATION.md](HOST_VERIFICATION.md) and [../TEST_REPORT.md](../TEST_REPORT.md). Earlier release entries below are historical.

## 1.4.1 saved-session / newest-log findings

- Latest attachment: **27 records, 21 NotInCallError warnings, 6 info**; no attached proof of actual Telegram logout, ban or authorization revocation. Only sanitized counts/types are published.
- Fixed overly broad native leave retirement, destructive automatic ciphertext clearing, delayed/stuck recovery, retry of completed owned cleanup failures, missing identity-validated session checkpoints, stale-worker writes and early reauth disable.
- Added bounded wakeable recovery/backoff, maximum-wait fencing, verified idempotent native absence, local-only restricted cleanup, per-account attach ownership and generation/connection/staff-revision checks.
- Lost/ambiguous Mongo acknowledgement cannot trigger logout of a possibly saved authorization. Wrong-key restoration can reconnect retained sessions; already erased ciphertext is not falsely reported retained.
- Build verification found nested generated bytecode could enter COPY trees despite unqualified ignore patterns. Recursive exclusions and a clean image inventory now prevent this; final image contains no application bytecode/private config/local sessions.
- **487 source + 487 final-image tests**, separate non-root/read-only real HTTP/Mongo probe, protected file/banner checks. No live Telegram/RTC, production deployment, no-ban guarantee or independent penetration test is claimed.

Details: [SESSION_RECOVERY.md](SESSION_RECOVERY.md), [../TEST_REPORT.md](../TEST_REPORT.md). Earlier findings below are historical release records.

## 1.4.0 unlimited quota / supplied-log findings

- Added explicit independent nullable unlimited quotas, future-pool entitlement, preserving short renewals, complete wizard/command/panel/notices/audit support and existing server guards. No giant sentinel/current-count snapshot.
- Audited the supplied 159-entry log: unobserved connection futures, pending native/Telethon tasks, misleading leave success logging and one unspecified BadRequest. Root network/BadRequest causes are not inferred.
- Owned native callback tasks/futures, per-adapter handler removal, gated/drained teardown, observed public disconnect futures, cancellation-shielded cleanup and fail-closed quarantine. Atomic max cooldowns preserve longer Telegram waits.
- Replaced raw HTML truncation with bounded safe formatting; known parse/length fallback and closed delivery categories retain privacy. Asyncio logs retain severity/type/frames while excluding raw task/future reprs.
- Full source suite: 400 passed. Final image/packaging results are in [TEST_REPORT.md](../TEST_REPORT.md). No live Telegram/RTC or production-host benchmark is claimed.

Details: [UNLIMITED_PREMIUM.md](UNLIMITED_PREMIUM.md), [RUNTIME_LOG_AUDIT.md](RUNTIME_LOG_AUDIT.md). Earlier release findings below remain historical.

## 1.3.2 account-capacity findings

The shipped 20-record default/template is a reproducible application ceiling. A second callback popup after early ACK was an unreliable visible error path. Fixed with validated 100 default/env override, read-only capacity screen, common commit checks and visible errors. No new error attachment accompanied the user request, so this is not a claimed diagnosis of unseen logs.

Large-roster health locking/startup and post-save health work were reviewed: account-health now runs independently, per-account locking allows foreground lifecycle changes, only attached healthy free identities are reserved, and post-commit background load cannot erase a saved session. Existing paid limits are not edited. Tests include 21st phone/OTP/2FA enrollment preserving 20 old ciphertexts, counts 21/35/99 and hard cap 100, concurrent final-slot race, full-pool reauth, exact ACK/visible transport, env upgrade/invalid bounds, post-save failure/shutdown and real HTTP readiness.

**317 complete Docker tests passed**, plus Docker/non-root/read-only/ffmpeg/API checks; controlled Telegram outcomes are not live sign-ins. Prior repeated-test database memory failure was recovered with a fresh disposable test DB and is not counted as a pass. See ACCOUNT_CAPACITY.md / TEST_REPORT.md.

# Source audit and hardening — TelePilot 1.3.1

Prepared: **13 October 2026**. This is a source review with automated regressions, not an independent penetration test or a live hosting certification.

## Reviewed areas

Configuration/bootstrap, role/plan authorization, target verification, encrypted account storage, chat/browser sign-in, queues/scheduling/rejoin, notifications/logging, HTTP health/security, editable UI, Docker/VPS/Railway files and update/backup instructions were cross-checked. The full automated suite uses real disposable MongoDB and controlled Telegram/Bot API/RTC outcomes.

## 1.3.1 findings / reported logs

- Public targets previously had managed request invites selected by the default wizard even when a public username was available. Fresh canonical public/direct routing now applies at both create and worker execution, with input validation, numeric-ID/type checks and authorization still mandatory. Private joins retain request semantics; public approval-required targets cannot be forced.
- Start text was refreshed but photo was still edited in history. Each explicit start now replaces both visible parts; optional media remains bounded, invalid file-ID fallback is supported, file-ID caching reduces upload traffic rather than caching away visibility. Owner-only setting/preview/on/off/default roles and form expiry are tested.
- New per-account join mutex closes detector/manual cap/gap mutation races; post-wait re-read handles health/day changes. Entity lookup is bounded. Revoked, network-failed and timed-out join accounts detach/cool down instead of remaining apparently healthy.
- The supplied audit contains partial statuses and revoked/connection/native-cleanup events, but no exact per-account error for the partial joins. Diagnostics now show safe original error-type counts/priority results/remediation, and audit JSON/actions/IDs are protected from smallcaps corruption. No supplied real IDs/credentials were used as fixtures or config.
- Old public-default/media-order assertions were explicitly updated to the chosen new policy. Earlier login/native/UI/plan/quota/force-subscribe/auto/lease tests retained. Latest full suite: **292 passed**. See TEST_REPORT.md and PUBLIC_JOINS_PHOTOS.md. No live production or independent security certification is claimed.

## Retained 1.3.0 findings and cross-checks

- /start could update an old unchanged panel higher in the chat without an obvious reply; image and coupled error-notification failures could prevent recovery after input deletion. Fresh acknowledged text delivery, cleanup ordering, optional-banner isolation and independent safe fallback address these reproduced source weaknesses. The exact production incident was not independently diagnosed from logs/credentials.
- Middleware callback acknowledgement now precedes potentially slow subscription/DB checks. Real aiogram feed_update tests verify bound Message/CallbackQuery objects, bot-authored anchors and the outgoing send/edit/delete sequence.
- Required-subscription configuration is owner-only at both form/service layers. Admin view is read-only; staff stay exempt. All regular memberships are verified, unknown/left/kicked/pending states deny access and entitlement-level checks cover workers. Config changes invalidate caches; initial explicit recheck after joining does not reuse the negative cache. Private invite rollback/removal, including bot-kicked repair, is covered.
- Auto modes require active call entitlement, own saved targets and fresh target control before joins. Detection uses authorized group access only. Permanent quotas and account caps are not relaxed. Physical chats cannot receive duplicate auto shares under different customer registrations.
- Shared pool reservations prevent manual/auto double use. Native departures complete before redistribution; failed/blocked eligibility cannot create fictitious capacity. Manual work has headroom and suppresses same-chat auto participation.
- Added regression for a real source bug found during new tests: an explicit target-permission failure initially fell into transient-probe grace. It now denies retention immediately; only genuine unknown probes use bounded grace.
- Call deadlines/block sets persist; new safety episodes have a per-user daily cap. Restart recovery does not wipe new auto ownership after launch. Cancellation covers children waiting on connection concurrency and before their cleanup begins. Uncertain native joining/leaving and partial adapter startup retire transports before reuse.
- Bounded/rotating detection budget, partial/stale handling, health/overview states, shutdown, one-replica lease order, config/env/Compose and existing chat/QR/UI tests cross-checked. All diagnostics are status/type/ID data; no exception message/credential is exposed by new error paths.
- Full suite recorded: **263 passed**. See TEST_REPORT.md and LIVE_ACCEPTANCE.md. This is source/integration testing, not live Telegram/hosting or independent security certification.

## Retained 1.2.0 findings and checks

- Paid feature visibility and fresh server enforcement were added independently: old buttons/forms, direct create requests, queued work and active call loops are covered. Calls require target membership but do not unlock independent channel tasks.
- Shared target/plan locks close slot-grant/registration/removal races. Every customer target is non-removable at the service boundary. Expiry/revocation/renewal never recycle a slot; staff correction is a separate actor/nonce/reason/confirmation workflow and rejects active target tasks.
- Explicit assignment rejects a quota lower than the saved count. Migration preserves both/old allowance without deleting data or overwriting new plans. Invalid explicit plan metadata fails closed; explicit staff reassignments can repair it.
- The plan wizard uses the callback actor, not the bot-authored anchor's from_user ID; a regression reproduces a real Telegram-style anchor. Request-key grants round to Mongo millisecond precision and avoid double extension.
- Contact configuration is validated and passed from stock VPS .env by Compose; old support contact remains a fallback. A link never conveys admin permissions.
- The original health handler synchronously awaited pool.sync and showed generic statistics; the new non-blocking report has bounded component/scan checks, progress, recent-run/FloodWait handling, skipped-state clarity and stale-view protection. Quick completion, concurrent starts, role restriction, timeout, sanitized errors, actual self-user probes and shutdown cancellation are covered. The user's exact live symptom was not independently reproduced.
- No dependency pins were opportunistically replaced. The working login/session commit, encryption, exact image and original platform hardening remain regression-tested.
- Current full result: **201 passed**, real disposable MongoDB and controlled Telegram/RTC outcomes. See TEST_REPORT.md. No live host/Telegram deployment or independent vulnerability/penetration scan was done.

## Retained 1.1.0 hardening

| Finding | Change and verification |
|---|---|
| Navigation generated repeated messages | Durable main panel; reused start banner; identical-render deduplication; deleted-message fallback; restart recovery. Dedicated UI transport tests enable the actual production defaults. |
| Smallcaps could corrupt functional content | HTML-aware text-node styling; protected code/pre, commands, URLs/email/usernames and attributes; original callback/URL values retained. Escaped URL queries and copyable plan examples are covered. |
| Panel FloodWait could lead to another error render during cooldown | Unified panel/banner send/edit handling, per-user pause and callback alerts; no recursive render retry. Tests include initial send, edit, banner and Guard recovery. |
| A saved UI message could be forgotten after metadata-write failure | Cache the accepted message before Mongo persistence; mark metadata dirty and retry without resending. Metadata only, never an authorization cache. |
| Concurrent callbacks/input could race through a form | Per-user action serialization; panel-creation locks. The 2FA panel uses an inline cancel button because edited text cannot attach ForceReply. Exact password text and leading `/` remain intact. |
| QR UI could leave old consent controls as the main screen | Main panel changes to the QR step. QR PNG stays transient, is never the durable banner, and is deleted best effort by the login manager. |
| Duplicate confirmation could create duplicate tasks | One draft key produces a stable user-bound job ID; repeated create requests return the existing job. Tests cover simultaneous confirmation and retry after post-insert audit failure. |
| Grant, revoke and expiry could interleave | Shared plan mutation lock; fresh extension and revoke-then-grant regressions. Existing cancelled tasks are not resurrected by a later grant. |
| Simultaneous target registration could create orphan invites | Per-user target lock; revoke newly created links if setup fails. Tests cover concurrent registration and partial invite failure. |
| Target removal could race job insertion | Job creation uses the same target-user lock as registration/removal. A target with a queued/running task cannot be removed. |
| Mongo operations could wait too long on an unhealthy connection | Bounded server selection/connect/queue waits and a 20-second client operation timeout; lease loss still stops the runtime. Hot-query/TTL indexes include panels, plan expiry, account health, target tasks and user listing. |
| Native call setup needed an explicit disabled/removed check | Check account state before starting the call adapter; regression verifies no native setup for a disabled account. |
| One account disconnect error could skip the rest during shutdown | Bounded disconnect and independent cleanup of all slots; native executor cleanup runs in finally. Regression covers one failing and one successful disconnect. |
| Partial busy-state write failure could strand other RAM slots | Bulk reservation metadata with rollback before Telegram actions; release clears every RAM slot before persistence. Fault-injection regressions cover both writes. Independent call accounts leave concurrently, avoiding account-count-multiplied teardown waits. |

## Important existing controls retained

- Private owner/admin account sign-in, explicit account ownership/privacy consent, actor nonce, role recheck, expiry/cancel/attempt bounds and original re-auth account identity.
- The Telethon DC-migration fix: three bounded request retries with the last RPC error raised. Positive FloodWait is still immediate and honored; no hidden retry to bypass it.
- Fernet-encrypted sessions in Mongo; no OTP/password deliberately stored in logs, FSM, Mongo or audit. Acknowledged session save is the login commit point, so later cleanup failures do not log it out.
- Requester and bot target-admin verification with bot invite permission. Private links are bot-managed. Join requests are reported as pending requests, not approvals.
- Account reservations, quota/pacing checks, persistent queue recovery, original call/deadline binding, fresh entitlement checks and conservative stop after moderation/removal.
- Durable plan/task source events and deduplicated outbox event keys. External message delivery is at-least-once best effort around crash boundaries, not exactly once.
- Secret-free public Docker defaults, validated environment bootstrap/PORT, early HTTP liveness, readiness/API gating and single-runtime Mongo lease handover.
- Non-root Docker user, private authenticated Mongo in Compose, no secret configuration baked into the image, bounded logs and best-effort sanitized logging fallback.

## Limits and residual risks

1. **No new live Telegram UI, OTP/QR, RTC, VPS container or Railway deployment was executed here.** The user reports the previous chat sign-in release works; that is useful user evidence, not a new deployment test. Bot API errors/outcomes in these regressions are controlled fakes.
2. Telegram bot chats are not end-to-end encrypted. Input/QR deletion cannot guarantee Telegram/operator retention erasure. A compromised service, host or encryption key can expose full account sessions.
3. Unicode smallcaps rendering/accessibility varies; use plain style if needed. Names supplied by Telegram are not translated. Old pre-update bot messages are not bulk-purged.
4. Per-user/action/plan locks are in-process. Run one replica/region per bot/database; the Mongo lease is not a multi-region RTC orchestration system or perfect network-partition proof.
5. Network errors after a server accepted a request can leave uncertain send/edit or DB outcomes. Stable job IDs and event keys reduce duplicate logical work, but cannot atomically commit external Telegram requests with Mongo writes.
6. Readiness is not a promise of continuous call quality. Native wheels/CPU, Telegram API changes, host egress/NAT/UDP, maintenance, external rates and account restrictions need owned-target live checks.
7. No no-ban, guaranteed approval, automatic payment verification, E2E conference/one-to-one calling, microphone/camera publishing or recording feature is claimed.
8. Dependency pins/import/signature and consistency checks were run; no independent dependency vulnerability service, penetration test, Docker image scan or Docker build was run in this workspace.

See [../TEST_REPORT.md](../TEST_REPORT.md) for exact release results and [LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md) before enabling paid production use.
