# Live acceptance checklist — required before production sales

Automated tests use mocked Telegram/RTC outcomes, so complete this with **your own test account, bot and owned target**. Do not test with someone else's account/OTP or a third-party group.

- [ ] Build image successfully on the actual CPU/OS; `docker compose ps` becomes healthy.
- [ ] Mongo authenticates using the app-scoped user; database has no public port. Save the original encryption key separately.
- [ ] `scripts/live_check.py` (or the smoke alias) reports read-only Bot API/HTTP/Mongo/current-runtime checks; indexes are not mutated. Follow [HOST_VERIFICATION.md](HOST_VERIFICATION.md).
- [ ] LOGIN_MODE=chat works without website; optional public health matches Host/PORT. Browser mode separately verifies TLS/cookies/origin.
- [ ] Owner `/start` has the exact supplied image as a reused banner plus one text panel. Repeated `/start` does not add duplicate messages.
- [ ] Every internal navigation/form/list/control button updates the same text panel; real alerts and transient QR are separate. Old pre-update messages are not bulk-deleted.
- [ ] Default smallcaps headings/buttons render well without an initial Latin capital; commands, links, payloads and copyable code examples retain exact values. Plain mode works if needed.
- [ ] Delete the banner/panel, then `/start` repairs them. Restart and verify navigation reuses stored IDs. Commands/form inputs are cleaned best effort.
- [ ] Set custom photo, restart, verify it persists; reset returns to default. UI wait errors leave the old panel rather than spam messages; do not provoke Telegram rate limits to test them.
- [ ] Owner can promote/demote an admin. Admin cannot edit owner-only features or manage another admin's account.
- [ ] Own staff private consent → phone → actual OTP → optional 2FA; preserve password whitespace/leading /. Posted OTP may expire; no code disguise workaround.
- [ ] Own official-app QR approval → Check approval → optional 2FA; short-token expiry/cleanup.
- [ ] No credentials/QR in logs/FSM/audit/Mongo; actual best-effort input/photo deletion, acknowledging Telegram may retain copies.
- [ ] /cancel/restart/role loss/wrong re-auth ID/persistent login FloodWait tested; default old browser routes return 410.
- [ ] Registered account `healthy`; database stores ciphertext, not a plaintext StringSession. Disable/enable and restart persistence work.
- [ ] ADMIN_USERNAME from VPS .env/Railway Variables opens the intended admin profile; the link does not grant permissions.
- [ ] Assign calls-only / channels-only / both and verify exactly the included automation buttons. Old excluded-feature callbacks/forms and queued tasks are rejected/stopped.
- [ ] Assign 1 then 2 channel slots; the user cannot add above limit or remove/recycle saved channels, including after expiry/renewal/restart. Identical re-registration is not double-counted.
- [ ] Staff correction requires role, reason and confirmation; queued/running target tasks block it. Confirmed correction revokes invites, audits actor/user/chat and intentionally frees a slot.
- [ ] Old Premium migration keeps both features and old allowance; new plans are not overwritten. Back up data first, never change the original key.
- [ ] Health button and /health show progress/results without blocking navigation. Leaving the page prevents late overwrite; busy/cooldown/disabled accounts are marked skipped and partial failures are visible.
- [ ] Customer `/start` and manual Premium grant: owner receives admin ID/customer ID/days/expiry/cap; customer receives activation/features notice.
- [ ] Free user cannot run automation; scheduled work beyond expiry is rejected. Revoke stops a running test job.
- [ ] Register owned private/public target with bot/admin Invite Users permission. Unauthorized target/link is rejected.
- [ ] One-account managed channel request submits **pending request**, not claimed approval; approve manually in the target and verify actual membership.
- [ ] Start an actual group voice/video chat. One account joins through the real RTC adapter with mic/camera off. Verify actual Telegram participant state; no fake-success response.
- [ ] End the call: job ends and leaves. Cancellation and configured duration/plan cap also leave.
- [ ] A genuine network-only disconnect gets bounded same-call retry; explicit moderation/removal stops retries. Avoid intentionally provoking Telegram FloodWait/bans to test them.
- [ ] A future local-time schedule executes within pacing/capacity constraints. A restart resumes only the original still-active call/deadline and skips saved channel success results.
- [ ] `t.me/call/...` conference links are rejected with the documented unsupported message; no misleading claim of support.
- [ ] Logging chat posts non-secret system events; blocked user delivery is recorded rather than claimed successful.
- [ ] Staging backup/restore with the matching key works. Original session-device revocation in Telegram Settings → Devices is available.
- [ ] VPS memory/CPU/network and actual call traffic support your planned account count. No “no ban”/always-on/guaranteed approval promise is made.

If the live RTC check fails, do not sell that feature as working. Set `calls_enabled=false` for channel-only use while you diagnose native library/API/hosting compatibility. This project does not include E2E conference/one-to-one calls or a media broadcaster.

## New 1.3.0 acceptance

- [ ] /start and /start@Bot reply visibly at the bottom; repeat sends one replacement main panel, not only an old edit. A blocked/unavailable photo does not swallow the text. Ordinary button navigation still edits the current message.
- [ ] With a sanitized simulated UI/DB/outbox failure, recovery shows a safe incident/type—not exception contents or credentials. Failed ordinary replies do not first delete the command.
- [ ] Owner add/view/remove required public/private channels after review; admin can view only and forged mutation is rejected. Bot-kicked requirement can still be removed by owner.
- [ ] Unjoined regular and Premium user gets join links/check/contact; all joined memberships reopen home. Pending/left/kicked/unknown checks deny access. Staff remain exempt and stop/help/contact work.
- [ ] Enable selected saved channels in calls/both plan. Channels-only, expired, other-user or feature-removed confirmation cannot enable auto. New targets stay off.
- [ ] In four owned active calls with 12 healthy free owned accounts and sufficient account caps: 3 per channel; end one → 4 per remaining; end another → 6 per remaining only if caps allow. No identity is counted in two managed calls.
- [ ] Start an additional call and verify departure-before-redistribution, uneven remainder/caps/disabled/cooldown behavior, and no fabricated approval/connection claims.
- [ ] Due/running manual jobs have capacity priority and same-chat auto does not double-join; after completion shares recover.
- [ ] Turn auto off during setup/active calls; Native accounts leave and reservations clear. Plan expiry, force-subscribe loss and target permission loss stop participation at the next fresh authorization check.
- [ ] Restart preserves original call deadline; expired same call does not start another safety episode. Account transport/network cancellation cannot strand reservations or reuse an uncertain native connection.
- [ ] Auto off does not free channel slots. Staff correction refuses active auto; after disable/departure it remains reasoned/audited.
- [ ] Staff auto overview + health make delayed checks, actual counts and skipped busy accounts clear. Complete a real owned-group RTC test; local imports and fake tests are not host/network verification.

## 1.3.1 public join / photo acceptance

- [ ] Owned public saved target uses direct join; old queued managed-request link normalizes to public. Actual approval-required public target still says request_sent, not joined. Private saved target retains request/approval behavior.
- [ ] Native entity numeric identity and actual requester/bot control are unchanged. Renamed/foreign targets or arbitrary private invites cannot redirect a task.
- [ ] Enabled /start sends a visible photo above the editable panel on every invocation, including after five minutes and restart. Normal navigation edits without adding photos. Disabled delivery is text-only.
- [ ] Owner set/preview/on/off/default buttons and command alternatives; admins/users cannot forge any mutation. Setting a photo while disabled does not silently enable it; restoring default preserves the visibility choice.
- [ ] Rejected cached/custom file ID falls back to supplied PNG; photo/network error still attempts text. Known FloodWait pauses are honored. Failed ordinary commands are not deleted first; login QR/2FA flow is unaffected.
- [ ] Partial task notice → task details shows protected ASCII error classes, membership-pending clarity and staff priority results. Audit IDs/JSON remain copyable, not smallcaps-mangled.
- [ ] Revoked accounts must re-authenticate; connection/timeouts go offline/cooldown before reuse. Keep the original key/database; do not fabricate success or bypass account restrictions.

## 1.3.2 / sign in beyond 20

- [ ] Existing private files/key/database/volumes preserved. MAX_POOL_ACCOUNTS=200 (or the VPS 200 profile) applied; capacity screen shows the effective limit, not stale 20. Only one app replica.
- [ ] Owned 21st account phone/OTP/2FA or QR completes; old 20 remain stored/working. Saved status responds while health loads in background. Do not bypass Telegram login protections/waits.
- [ ] Chosen finite cap shows actionable visible panel, not a silent callback; existing-account reauth still possible with consent/ownership/busy checks.
- [ ] Large-roster reload does not block /start, add-account prompts, dialog cleanup, expiry or readiness. Account health becomes ready gradually; readiness is not proof all Telegram accounts are connected.
- [ ] Shutdown/restart and post-save health errors preserve committed encrypted sessions. Old custom lower cap is not silently changed without env/config action.
- [ ] Existing paid limits/features, permanent targets, photo settings, forced subscriptions and reviewed native calls verified on the real authorized host. See ACCOUNT_CAPACITY.md for boundaries and smoke commands.


## 1.4.0 / independent unlimited + runtime-log follow-up

- Preserve the original key/config/database/volumes and take a protected backup. Check new schema 3 rollback precautions in [UNLIMITED_PREMIUM.md](UNLIMITED_PREMIUM.md).
- Give both/unlimited+unlimited, calls/2+unlimited, and channels/unlimited+5. Check review, My Plan, target list, help and user/owner notices say unlimited, not null/None/a frozen current account count.
- Short `/premium USER_ID 15 extend` preserves modes; an explicit finite value switches only that quota. Downgrade below saved targets rejects until audited correction.
- Add one later authorized pool account through the existing phone/OTP/exact-2FA or QR flow. Verify it can be selected by a new task and considered in the next automatic-call rebalance without a quota edit. An existing manual task must keep its reviewed count.
- Expiry/revoke/feature changes still stop disallowed work; saved targets remain locked. Force-subscribe/staff exemptions, target approval, moderation and FloodWait still apply.
- With owned accounts, test active native-call cancellation and graceful restart; inspect typed callback/cleanup/health evidence. No success-sounding leave message on arbitrary failures; no blind reuse of TransportCleanupPending identities.
- Check long/emoji/escaped notifications, blocked/unknown recipients and safe error categories. The attachment did not establish the exact old BadRequest cause.
- Test in stages on the real host. The current deployment guard is at most 200 saved pool accounts; actual 200 concurrent native attendance or permanent attendance remains unverified. Graceful teardown cannot be promised after SIGKILL/provider termination.

No live Telegram/RTC acceptance was run by the assistant. Real disposable Mongo/Docker/loopback HTTP results are separate in [TEST_REPORT.md](../TEST_REPORT.md).


## 1.4.1 / saved-session recovery on your authorized deployment

1. Back up existing Mongo and separately preserve the original encryption key/config. Upgrade in a new source directory without replacing private config or volumes. Keep one replica.
2. Record a saved authorized test account's state without exporting/logging its session. Restart cleanly; confirm it reconnects without OTP and the current Telegram ID matches.
3. Cause a brief controlled host network interruption. Confirm exclusion while offline, saved-record preservation, respected backoff and automatic recovery after connectivity returns. Do not trigger Telegram rate limits deliberately.
4. End an owned test call normally; confirm already-absent native cleanup does not falsely disconnect the Telegram account. A true uncertain native transport must quarantine until cleanup is confirmed.
5. Open reauth and cancel before commit; verify the original account remains available. Test wrong-identity denial using only accounts you own. Successful replacement must respect busy/staff changes and existing deadlines/counters.
6. Disable an account as staff and verify recovery cannot re-enable it. Check durable moderator blocks remain enforced; do not test by evading a real ban.
7. Review status-specific notices, optional reconnect saved session, nonblocking health and original private phone/2FA/QR behavior, plus unlimited plans/automatic fair sharing from 1.4.0.
8. For genuine revocation/expired/duplicated/deactivated/banned errors, expect stopped automatic use and honest staff guidance, not a promised repair. Never manufacture abuse/duplicated sessions to test bans.

These live steps were **not executed** by the source/container verification. Correct storage, Telegram acceptance and the host RTC/network remain required.


## 1.4.2 / execute the selected host-run verification

- [ ] Rebuild full source, keep original secrets/data and a single runtime. Do not use a second app process/container or clone StringSessions for diagnostics.
- [ ] `/health` in the existing bot emits fresh explicit self-identity evidence; stale healthy labels, skipped accounts, old code, expired lease or changed key/config cannot be used as a fresh pass.
- [ ] During one owned managed manual test call, the read-only in-process sample observes native binding presence AND Telegram self participation in the SAME call. It must not create/join a call or record/publish media.
- [ ] `docker compose exec -T app python scripts/live_check.py` returns sanitized JSON. Exit 2 with no active call/fresh proof is incomplete, not a fake live pass. Export contains no IDs/keys/URIs/session material.
- [ ] Confirm the existing native flow respects disable/replacement/cooldown/moderator changes while queued and after late native success. Use safe controlled staging scenarios; never provoke Telegram bans/rate limits.
- [ ] Return the sanitized JSON and short manual signup/QR/reconnect/UI/call-stop outcomes. No real production account/RTC run was performed by the assistant; full acceptance stays pending until those observations are available.

Exact safe commands and interpretation: [HOST_VERIFICATION.md](HOST_VERIFICATION.md).


## 1.4.3 / transport log follow-up

- [ ] Complete source rebuilt, startup says 1.4.3, original key/private config/database/volumes and single replica preserved.
- [ ] Existing valid saved accounts reconnect after their persisted wait without another OTP. Keep genuine bans/revocations/staff disables stopped; do not provoke restrictions for testing.
- [ ] Check new typed `transport_code` on naturally occurring wire failures. Old unknown-code records must not be retrospectively labeled 404/429/ban.
- [ ] Confirm owned native stop after network loss without remote leave after MTProto disconnect, no duplicate session runtime and no deletion of saved ciphertext. Use controlled authorized staging, not disruptive production experiments.
- [ ] Gather fresh `/health` during one owned managed call and run the existing-container host reader. Return only sanitized JSON and manual outcomes from [HOST_VERIFICATION.md](HOST_VERIFICATION.md).
- [ ] Verify private phone/OTP/exact-2FA/QR, cancellation, editable English/smallcaps UI/photos, roles/independent unlimited/locked targets/force-subscribe/scheduling/allocation on the actual host as required. Don't reauthenticate a good production account merely to fill a test box.

The assistant's real SDK/synthetic-packet and HTTP/Mongo/container checks are not real user-host Telegram/RTC acceptance. See [TRANSPORT_RECOVERY.md](TRANSPORT_RECOVERY.md).


## 1.4.4 / do not mass-reauthenticate before safety review

- [ ] Inventory and stop other copied-session workers/services/old deployments/database clones. Local PID counts and one visible replica/IP do not prove global exclusivity.
- [ ] Original key/private config/database/volumes retained; deploy full 1.5.0 source only on the selected runtime. Observe paused bootstrap for old duplicate records.
- [ ] `/sessionguard` and `/health`, then `scripts/live_check.py --scope safety` in the existing container, without a user login or call. Return sanitized JSON; blocked/incomplete is expected pending owner review.
- [ ] Owner-only review/expiry/nonce/incident/audit/cleanup gates verified. Resume leaves revoked/banned flags and encrypted data untouched.
- [ ] After the cause is actually resolved, reauthenticate one owned affected account through the original consented flow and verify it stays healthy. Another duplicate means STOP and investigate; don't repeat mass paid login attempts.
- [ ] Only then perform authorized full Telegram/RTC/UI/roles/plans/schedules/force-subscribe/photo/allocation acceptance. No test deliberately duplicates a real authorization or provokes Telegram bans/rate limits.

The assistant's source/image/HTTP/Mongo checks are not the user's deployment inventory or real Telegram/RTC acceptance. Read [SESSION_SAFETY.md](SESSION_SAFETY.md).

## 1.5.0 / 8-vCPU, 64-GB Docker host

- [ ] Follow [VPS_200.md](VPS_200.md), selecting bundled versus original external Mongo correctly; one app, same project identity, original private files/key/database/volumes.
- [ ] Capacity panel shows 200, but existing finite customer allowances remain unchanged; explicit finite 200 and independent unlimited modes work.
- [ ] Enroll gradually; review account 101–200, saved-session recovery and skipped busy/cooldown states without mass OTPs or parallel copies.
- [ ] Check actual CPU, RAM, PID/thread/open-file use and disk while ramping; 48-GiB/6-CPU app and 8-GiB/1-CPU Mongo are configured ceilings, not a measured 200-RTC result.
- [ ] Enable Docker at host boot; verify persistence and graceful single-container restart on your host. If installing the optional watchdog, dry-run under the actual project identity, verify a manually stopped/healthy safety-paused app stays untouched, and stop the timer before maintenance.
- [ ] Run the read-only existing-container host reader and report only sanitized outcomes. No permanent uptime, restored invalid key or media-quality guarantee.
