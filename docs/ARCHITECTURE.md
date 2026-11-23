# Architecture and state transitions

## Components

- `config.py`: validates external JSON, env references and required fields; supports safe public-default/environment-only cloud bootstrap and strict explicit file paths.
- `services.py`: fresh DB-backed RBAC, Premium mutations, target admin-control checks and managed invites.
- `security.py`: session vault, tokens/digests, HTML escaping and safe user errors.
- `bot.py`: private-chat button panels + FSM drafts, role-checked commands; only `/chatid` is handled in target chats.
- `login.py` + `bot.py`: staff private-chat consent/phone/OTP/2FA and QR, no credential FSM/storage/logs. `web.py` retains health and explicitly opt-in browser mode.
- `accounts.py`: StringSession clients, synchronization/health, shared pacing, durable FloodWait, exclusive reservations and RTC adapter.
- `jobs.py`: persistent scheduling, user/plan/control checks, account allocation, channel queues and bounded same-call lifecycle.
- `notifier.py`: durable/idempotency-keyed outbox; plan/terminal-job events are committed in their source documents and drained after restarts.
- `compat.py`: local API signatures + stable package version alerts.
- `runtime.py`: single event loop, supervisor, leader lease, periodic checks and clean shutdown.

## Mongo collections

`users` (plan + pending plan events), `admins`, `accounts` (encrypted session, identity, added_by, enabled/health/cooldown/quota), `targets` (requester/admin-verified target, managed invites), `jobs` (schedule/state/original call/deadlines/results), `outbox`, `audit`, `settings`, `login_tickets` (hashed tickets, TTL), `leases` (singleton runtime).

Timezone-aware Mongo clients decode UTC values. Human display uses configured IANA timezone. Quotas reset on UTC dates. Audit/job/outbox/ticket TTL indexes handle bounded operational retention.

## Account/login lifecycle

```text
Staff private dialog + fresh nonce + full-session/ownership consent
 → phone → OTP → optional 2FA
 OR QR export → official Telegram device approval → actor Check approval → optional 2FA
 → actual Telegram ID + management rights validation
 → encrypt StringSession before Mongo acknowledgement (commit point)
 → temporary-client disconnect + pool attach + audit/notification
 → clear dialog/input/QR and inspect account health
```

FSM stores only context ID. Credentials/hash/QR waiter are transient RAM. Telegram deletion is not guaranteed erasure. Cancel/expiry/role loss revoke authorized-but-unsaved sessions best effort; postcommit failures never log out saved sessions. Re-auth preserves ID, disables only after consent and has a pending claim. Actor login cooldown persists with per-account job cooldowns.

Browser exchange is explicit opt-in; default portal routes are disabled while health remains. Browser/QR secrets must never enter logs/durable notices.

## Job lifecycle

```text
Premium/staff + controlled target + matching link + quotas
 → queued (UTC run_at + original start_deadline)
 → atomically claimed by singleton scheduler
 → execution-time entitlement/control recheck
 → reserve requested number of free healthy sessions
     no capacity → delayed queued (or deadline failure)
 → rate-controlled channel requests OR active-call joins
 → completed / partial / failed / cancelled
 → durable terminal notice → release reservations
```

Channel results distinguish `request_sent`, `joined` and `already_member`. A sent request is successful submission, not membership. Requested capacity is not silently reduced; actual per-account Telegram rejections are reported as partial/failure. After a crash, recorded successes are skipped. RPCs and database updates cannot be one cross-system transaction, so retry-after-acceptance is possible.

Call membership may need approval before access. The worker waits a bounded start grace for an existing call, stores its original call ID/end deadline, joins with no mic/camera media, probes the call and native transport, and allows limited backoff rejoin only to the same call. Explicit remote removal stops retries. Calls never auto-create or migrate into a different call. End/cancel/revoke/control-loss/error paths leave transport and release slots.

A restart requeues unfinished jobs; call deadlines and expected IDs do not reset. A delayed initial job past its start deadline is rejected. At most `max_parallel_jobs` tasks are processed simultaneously. The pool's common lock prevents reservation vs account disable/removal races.

## Premium events

Plan updates write the new plan **and pending event in the same user-document update**. The notification worker upserts actor/owner/target notices and audit events by unique event key, then removes the pending source event. Terminal jobs similarly retain `notification_pending` until an outbox entry exists. This avoids losing the event if a process restarts between plan/job persistence and outbox creation. External message delivery remains at-least-once best effort around crash boundaries.

Grant rules: `set` = now + days; `extend` = max(now,current expiry) + days. Future scheduled work must fall within current Premium entitlement. A revoked/expired plan cancels queued/running jobs and stops active call loops; a reduced cap is checked before further actions. Staff test jobs have config-limited operator entitlement, separate from paid customer status.

## Health and compatibility

Leader lease renews independently of slower account checks; loss stops the runtime. Supervisor treats a critical task exit as service shutdown. HTTP readiness checks Mongo + service-task liveness. Account checks are real MTProto self-user requests, not just a cached `get_me` object. Compatibility probes verify installed adapter interfaces and query stable PyPI versions; they do not automatically implement upstream protocol changes.


## Railway/environment bootstrap (1.0.1)

Default config absence is no longer fatal: public image defaults plus validated service Variables provide configuration. Actual JSON/secret files are never baked into the image. Explicit custom CONFIG_PATH remains strict. PORT is validated and used by the HTTP listener; an exact public URL/domain feeds Host/Origin controls.

HTTP liveness starts before slow DB/account work. APIs reject credentials while ready=false. A new instance waits for the original process's lease to be released or expire before starting Telegram clients/polling, allowing deploy-time liveness to drive a controlled Railway handover. Only after DB/bot/workers initialize does readiness become true. Liveness is not operational success; calls may be interrupted during redeployment.

## Editable UI and mutation hardening (1.1.0)

`app/ui.py` owns a durable private text panel and separate optional start banner. Mongo `ui_panels` stores IDs, banner identity, render hash and TTL timestamps only. A bounded RAM cache and weak keyed locks serialize rendering; per-user action locks serialize callback/text FSM navigation. Identical screens skip API edits; /start explicitly probes for deleted messages. Delayed UI metadata persistence keeps a just-sent panel in RAM and retries without resending. This cache is never consulted for authorization.

An outbound Aiogram request middleware styles all bot messages/buttons, including actual alerts. HTML text nodes are smallcaps while code/pre, HTML attributes, commands/URLs/identifiers and payloads remain functional. QR photos remain transient in LoginManager, not durable banners. ForceReply is converted to inline sign-in cancel when editing.

Stable user-bound draft keys determine new job IDs and return a previous acknowledged job on retry. Grant/revoke/expire share a mutation lock. Targets register/remove and job creation share user-local target locks, with rollback of newly created invites on failed setup. Locks are single-runtime controls, not distributed transaction guarantees. Mongo operations have bounded client deadlines; shutdown attempts cleanup for every account independently. See CLEAN_UI.md and AUDIT.md for limits.

## Feature subscriptions and health (1.2.0)

`plans.py` defines channels/calls/both and normalized legacy defaults. `services.Access.entitlement(..., kind=...)` performs fresh feature checks; creation and worker/pacing loops enforce them independently of menus. Plan documents contain feature_plan, channel_limit, max_accounts, expiry and schema version. Logical grant request keys make immediate retries idempotent. Target locks are shared by registration/removal/job creation and plan mutations; lock order is user-target then global plan mutation. Expiry re-reads the current expired row after acquiring those locks.

Regular users cannot delete any saved target. Staff correction uses its customer lock, fresh role checks, no queued/running target tasks and an acknowledged audit authorization before invite revocation/deletion. Upgrade cannot silently remove targets; downgrade below saved count is rejected. A leader-only idempotent migration fills old missing fields and locks customer targets without changing the original session key/expiry/account cap. Target pages use a stable created_at/_id index.

`plan_ui.py` separates typed, actor-bound staff forms from task/login handlers. `health.py` owns one shared non-critical bounded diagnostic task with sanitized RAM results/watchers. Pool lifecycle locks are retained, but navigation does not wait for a full scan. Manual probes skip busy/disabled/cooldown accounts and avoid re-probing a fresh attach. A non-secret UI view key rejects stale progress edits. Diagnostics are cancelled before shutdown pool cleanup; periodic lifecycle changes are stopped first. Native adapter availability is not proof of a successful RTC call.

## Required subscriptions and fair auto pool (1.3.0)

force_sub.py holds owner-only global requirements, bounded per-user cache/locks and concurrency-limited Bot API membership checks. Guard renders the gate, but Access.entitlement is the independent server boundary used by jobs/auto. Staff exemptions rely on role, not a username. automation_ui.py uses actor-bound reviewed forms; add/remove and auto opt-in never take the bot-authored anchor's ID as actor.

auto_calls.py polls enabled targets through healthy non-manual accounts, records physical call IDs/deadlines in auto_sessions and owns nonoverlapping auto:<session> pool reservations. Capped water filling treats a channel as the allocation unit. Queued/running manual demand and same-chat manual calls preempt auto capacity. Departures precede new joins. Partial probes have bounded recent-confirmation grace, but explicit authorization loss does not. Configuration wakes cancel slow cycles without making the worker a completed critical task. Native setup is concurrency-limited; cancelled/unconfirmed transports are retired before reuse.

Runtime creates/recoveries the manual/auto engines after singleton lease acquisition, clears stale ownership once before pool startup and adds the auto worker to critical tasks. Health remains separate non-critical background work. Shutdown stops auto before manual jobs/login/pool. A partial unique target index enforces one enabled auto owner per chat; old plans, keys and saved locks are unchanged.

## Public join and photo corrections (1.3.1)

Targets.join_link resolves the current saved numeric chat ID and chooses a canonical public username/direct RPC or private managed request invite after input/ownership checks. Join workers re-resolve queued legacy links. Slot.join_lock serializes safety day/gap/counter work independently of the RPC lock; health/cooldown/date is refreshed after waits. Public entity lookup is bounded and checks the same marked peer ID before any join.

start_photo.py owns owner visibility/source controls and bounded optional delivery. Panels.banner fresh=True sends rather than edits the old image, saves/cache-commits metadata and cleans old IDs after acknowledgement. The default image file-ID cache is bot/checksum-bound; it never suppresses a start send. Login QR path bypasses banner metadata. diagnostics.py contains authored type/hint mapping only, not exception serialization; audit JSON uses pre/code.

## Capacity and post-commit lifecycle (1.3.2)

Limits.max_pool_accounts defaults to 100; non-empty MAX_POOL_ACCOUNTS overrides only this nested field and does not rewrite private JSON. LoginManager.capacity/require_capacity and PoolFullError serve chat/browser/completion checks; finish_lock serializes last-slot commits. Staff capacity view is read-only. Saved records count even when disabled/offline; reauth does not consume a new record.

After Mongo acknowledgement, LoginManager marks completion and schedules owned attach_saved tasks instead of waiting on a whole sync lock. Shutdown cancels/gathers them before pool close. Runtime account-health is a separate infinite critical worker, started only after queue/auto recovery and singleton acquisition. AccountPool.sync holds its lifecycle lock per account, not the whole roster, and available filters the complete eligible cursor by live reservations. Guard renders visible UserError after ACK and independently recovers backend/ACK errors.


## Unlimited quotas and owned native teardown (1.4.0)

Stored plan schema 3 has independent explicit unlimited flags and nullable values; old finite plans remain valid. `normalized_plan` validates commercial metadata; `effective_plan` resolves deployment-bounded integers for the existing job/automatic-allocation contracts. No snapshot of pool count is persisted. Legacy short renewal omissions preserve modes; target locks, feature/expiry checks and downgrade protection remain. See [UNLIMITED_PREMIUM.md](UNLIMITED_PREMIUM.md).

`native_lifecycle.py` wraps per-adapter native registrations/MTProto handler for pinned PyTgCalls 3.0.1/NTgCalls 3.0.7. It owns actual tasks and concurrent futures, closes the callback gate, removes its own Raw handlers, cancels/drains callbacks and stops known local transports without ending the Telegram group call. Pool detach owns a shielded cleanup task; public disconnect futures remain referenced across non-cancelling timeout waits. Unproven cleanup quarantines the identity and preserves its encrypted session. Terminal public Telethon disconnected futures are observed; health work is tracked and reservations exclude dead/closing slots immediately. `$max` preserves longer Telegram cooldowns.

`message_safety.py` bounds raw HTML/UTF-16 without splitting markup/entities, provides one known-format fallback, and classifies BadRequests into safe closed categories. The outbox retains deduplication and bounded retry behavior. No raw task/future/request/exception repr is added to logs. See [RUNTIME_LOG_AUDIT.md](RUNTIME_LOG_AUDIT.md).

HTTP shutdown now gives Uvicorn a bounded graceful request/lifespan drain (10-second server grace, 15-second runtime wait) before cancelling remaining workers. An idle normal shutdown must finish its HTTP task without a CancelledError traceback; deadline failures are logged, not hidden.


## Authorization generations and recovery (1.4.1)

`session_state.py` separates encrypted authorization, local transport failure, server-invalid authorization and confirmed bans. `DurableStringSession.save()` schedules at most one owned checkpoint per client for a nonempty changed key/DC; raw self-user validation precedes encryption and CAS persistence. Empty intermediate keys are never saved. Session strings remain only in the necessary Telegram client/process memory, not a plaintext fallback file.

`session_generation` changes on explicit authorization replacement; `connection_epoch` changes on a validated attach. Status, cooldown and checkpoint writes fence old owners. A registry owns/serializes public per-account attach attempts, while existing lifecycle locks protect commit/detach. Shielded disconnect futures retain their real completion; completed failures can retry without replacing pending work. Runtime recovery ticks between full scans and respects persisted maximum deadlines, busy reservations and known authorization stops.

Reauth consent no longer detaches the old account. At commit, role/existence/original ID/generation/staff revision/busy state are rechecked; old local cleanup is confirmed and the temporary authorized client transfers to strong pool ownership before Mongo storage. Ambiguous writes are verified by generation, and never authorize automatic logout of a possibly committed key. Independent staff toggle/remove mutation is serialized and increments `account_revision`. New enrollments still reply without waiting for a whole roster health scan.

Already-absent native calls are idempotent only for exact pinned exception classes with empty binding state and no pending join. Generic cleanup uncertainty remains quarantine. Runtime forbidden-chat guards and durable auto-call block lists survive recovery; no commercial quota, target lock, deadline or rate-limit bypass is introduced. Details: [SESSION_RECOVERY.md](SESSION_RECOVERY.md).


## Read-only host reader / native setup fencing (1.4.2)

`assert_call_allowed` rechecks live slot ownership, enabled/auth state, generation/epoch, Telegram cooldown and moderation before native setup, after gate/callback yields and after SDK completion. A late success on newly denied access remains uncertain until normal owned cleanup; no account session is erased.

`live_diagnostics.py` executes only inside staff health on the existing runtime. It samples one currently managed manual/auto call with current authorization/deadline, native map presence and server self-participation in the same call. Explicit health identity flags separate real new proof from labels/skips. `health_evidence` publishes a closed aggregate settings value, not UI/result dictionaries. Runtime and bot references plus a per-runtime HMAC over the existing configuration detect stale/wrong-runtime/config reports; references remain internal, never in the returned host JSON.

`host_check.py` and the `live_check.py`/`smoke_test.py` wrappers create only an HTTP reader, Mongo reader and Bot API identity client. They never initialize indexes, acquire a lease, construct/decrypt an account session or mutate the database. Bounded reads use count-only account queries and a strict settings projection. Exit 0 covers declared automated observations only, 1 means essential host failure, 2 means incomplete evidence. Manual acceptance stays explicit and pending. No extra bot worker/service/HTTP control endpoint was added.


## Per-client Telethon future ownership (1.4.3)

`telegram_lifecycle.py` wraps only the sender of a pool-created real TelegramClient instance. `send()` returns its original Future/list unchanged, while the owner retrieves completed exceptions—including the SDK's intentionally ignored keepalive ping future. It observes replaced terminal/reconnect futures and strongly owns SDK reconnect callback tasks. Closing the per-client gate prevents late callbacks; cancellation/drain is scoped to that client. Queued owned promises are settled only after confirmed SDK disconnect, never during an ordinary DC migration. A still-connected/stubborn task cannot certify cleanup. No asyncio handler/class/global SDK patch is used; the TelegramClient class/module remains unchanged for PyTgCalls' package-name detection.

Pool transport events mark the current slot disconnected synchronously, close its native callback gate, and schedule epoch/generation-fenced persistence. They retain ciphertext, respect waits and distinguish wire 404/key-not-found from confirmed RPC bans/revocations. Unknown packets are never serialized. Wire 429 uses a 900-second local minimum policy and preserves a longer known wait.

Initial/recovery handshakes and SDK post-reconnect notification are paced and checked against fresh enabled/auth/wait/ownership state. Pool-owned disconnect quiesces/drains the SDK owner without losing the shielded cleanup future. Known-offline call cleanup skips remote leave; existing per-adapter local stop/drain/executor cleanup remains authoritative. See [TRANSPORT_RECOVERY.md](TRANSPORT_RECOVERY.md).


## Confirmed session conflicts (1.4.4)

`SessionSafety` contains confirmed duplicated-key replies from every original sender future, including SDK-caught requests. It synchronously gates all managed account traffic, persists one fleet incident, owns local quarantine and retains account data. Initialization catches existing/unacknowledged or newer partial-crash incidents. Owner review is nonce/actor/expiry/incident-bound, audited and refused while local ownership is unresolved; it never clears account auth stops.

`Store.acquire_leader` seeds a lease record, then atomically uses Mongo `$$NOW` with majority acknowledgement. Local monotonic send authority expires at 70 seconds, before the 90-second server lease; failed renewals permanently fence that runtime. Per-primary-connection wrappers check before TCP open and synchronous socket writes, not just queue insertion or post-reconnect callbacks. Shutdown retains the lease if transport cleanup is unconfirmed. Database clones/other tools/old versions are outside that coordination scope.

The read-only `deployment_audit` returns only bounded local PID-namespace counts and platform-presence hints, not process arguments/IDs/environment values. Host safety scope reads projected fleet/health metadata and never creates user sessions or claims global inventory verified. See [SESSION_SAFETY.md](SESSION_SAFETY.md).
