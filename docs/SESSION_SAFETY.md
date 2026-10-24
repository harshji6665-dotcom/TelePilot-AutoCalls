# Confirmed duplicated authorizations — containment and recovery (introduced 1.4.4; retained in 1.5.0)

## What changed in the evidence

The new JSON log has **43 records**: 8 information and 35 warnings, including **12 transport-429 warnings** and **23 connection-ended warnings**. Its startup identifies **1.4.3**. The separate message export is decisive: **56 `AuthKeyDuplicatedError` notices for 56 distinct account identifiers**, plus 23 connection notices. A total of 57 distinct account identifiers appears across those notice types. These counts do not prove the total configured pool size.

Unlike the earlier unknown-code transport logs, this export establishes **server-invalidated authorizations**. Telegram documents that AUTH_KEY_DUPLICATED can result from parallel main TCP/MTProto sessions using one authorization, on the **same or different IPs**; when received, that authorization was already invalidated and a new key/login is required. Normal separate official-app authorizations and permitted media connections are different cases. [1](https://core.telegram.org/api/errors) [8](https://core.telegram.org/api/datacenter)

**Retaining ciphertext is essential, but cannot make a server-invalidated key valid.** Restoring the same old key from a backup, changing the database encryption key or repeatedly reconnecting it will not repair that invalidation. This error is not itself proof that the Telegram account was banned. [1](https://core.telegram.org/api/errors)

The files do **not** identify which other process/connection caused overlap. One visible deployment's log does not inventory other services, hosts or copied databases. The operator selected **not sure** about deployment topology. Do not assume the cause is solved merely because the current service says one replica, its IP is static, or a unit-test suite passes.

No production identifiers, export contents, session strings, phone/OTP/passwords or credentials are reproduced in the release.

## Stop the cascade before using more saved keys

1. **Do not mass-reauthenticate now.** First stop every conflicting copy using these managed sessions: old deployments, overlapping rollout containers, staging services, local scripts, other VPS processes and production database clones.
2. Preserve the **original private configuration, encryption key, database and volumes**. Do not delete account records/paid targets or use `down -v`, new keys, restored session clones or disposable replacement databases as a fix.
3. Choose one deployment and one active main client per managed authorization. Inspect **all projects/environments/services**, not just the service whose logs were exported. Old 1.4.3 or older copies do not honor the new circuit breaker and must be stopped.
4. Inspect locally; do not upload raw environment/process arguments, tokens or Mongo URIs. On a VPS, `docker ps` can help inventory containers, but a count inside one container cannot see every host/service. Read-only local PID observations are hints, not proof that all other copies stopped.
5. Rebuild the complete 1.5.0 source only on the selected deployment. Keep private config and volumes; never replace them with the ZIP's public starter config.

For an existing Compose deployment, after inventory/stopping other copies and confirming Mongo remains healthy:

```sh
docker compose build app
docker compose up -d --no-deps app
```

For a hosted service, verify old deployments really terminate, one selected replica/region is used, and no other project/environment uses the same managed-session backup. A static-IP toggle is not a single-main-session guarantee. Current Railway documentation also describes load-balanced static outbound address sets, so a static-IP label must not be interpreted as one exclusive TCP identity. [2](https://docs.railway.com/networking/static-outbound-ips.md)

## What the new code enforces

### First confirmed duplicate triggers a fleet safety stop

- Observes duplicated-key errors on **all original sender RPC futures**, including SDK-internal requests whose caller catches the error. The first observation freezes account traffic before another roster identity is intentionally tried.
- Stops new account connections, RPC/call work, enrollment and reauthentication. Closes native callback gates, quiesces owned SDK reconnect work and schedules owned local cleanup.
- Persists a bounded fleet safety record and the affected account's fenced revoked state. Original encrypted records, enabled/staff choices, plan/target data and valid authorizations are not deleted or globally marked revoked.
- Startup finds previously recorded duplicate errors, including a partial crash between per-account rejection and fleet-pause persistence. A reviewed old incident does not hide a newer duplicate.
- Does not automatically retry an invalidated key or generate another OTP/login.

### Runtime ownership is checked at the wire

The singleton lease uses **Mongo server time**, atomic ownership renewal and majority acknowledgement—not each host's local wall clock. A conservative local **70-second monotonic write deadline** precedes the **90-second server lease**; renewals run every 20 seconds.

Ownership/safety is checked before TCP opening and immediately before actual primary connection writes, including packets queued before lease expiry and SDK-internal reconnect traffic. A lost/expired lease fences writes and requests shutdown. Account cooldown/retired/authorization checks now run **before** SDK TCP reconnect, not only in the callback after reconnection. Ordinary allowed DC migration remains supported.

Shutdown does not voluntarily release the singleton for immediate takeover while owned transport cleanup remains unconfirmed. The real TelegramClient class/module is retained for PyTgCalls. No global asyncio patch, new login client for diagnostics, packet logging or session/IP-rotation workaround is introduced.

**Boundary:** a Mongo lease protects this database/runtime scope. It cannot stop an old unguarded version, another tool, a different host or a separately cloned database that uses the same authorization. The wire fence is local protection, not proof that all external copies disappeared. There is no no-ban/no-revocation guarantee.

## Run the safe report before any new login or call

1. Send `/sessionguard` in your existing bot (or manage → session safety). Staff may view; only the owner can approve resume.
2. Send `/health`. While safety is paused it inspects metadata and reports account checks as paused, not new successful Telegram identity probes.
3. Run in the **existing running app container**, not as another bot worker:

```sh
docker compose exec -T app python scripts/live_check.py --scope safety
```

In an existing hosted-service container shell/native environment with the original configuration:

```sh
python scripts/live_check.py --scope safety
```

The reader opens **no Telegram user session**, requests no OTP, creates no indexes, acquires no lease, writes no Mongo and starts no call. It reads loopback HTTP, counts and projected safety metadata, calls Bot API getMe once and gives bounded local process/platform hints without IDs/arguments/environment values.

- Exit **2** with `session_safety.status=blocked` is expected while the known incident awaits review. It is not a demand to sign in repeatedly.
- Exit **1** indicates essential configuration/HTTP/DB/lease/Bot API/owner checks failed.
- Exit **0** in **safety scope** covers fresh safety/fence observations only; it does **not** certify Telegram sign-in, RTC, all deployments, IP stability or uninterrupted service.
- `complete_live_acceptance`, global deployment verification and route-stability verification remain false. The report cannot remotely discover all your other providers.

Return this sanitized JSON, not raw credentials or session data. The assistant has not accessed your provider dashboard or run your production Telegram calls.

## Owner-reviewed resume, then replace only invalidated authorizations

After stopping conflicting copies and reviewing the deployment:

1. Open `/sessionguard` → **review before resume**. Read the warning and confirm only if it is true. The confirmation is owner-bound, expires in five minutes and is tied to the current incident.
2. Resume is audited and refused if local clients/cleanup/attach/persistence work is still unresolved, ownership is not current, the review is stale or a new incident arrived. Admins/users cannot forge it.
3. Resume **does not clear per-account revoked/banned flags** or automatically sign in. Still-valid saved accounts can recover normally. Affected duplicated keys remain rejected.
4. Reauthenticate **one account you own** through the existing phone → OTP → exact optional 2FA or QR flow, only after the source of overlap is fixed. Keep one authorized runtime; confirm it remains healthy before proceeding gradually.
5. If another duplicate appears, the safety stop returns. Stop and investigate; do not cycle all accounts through more paid logins or restore the same invalid key.
6. Only after safety and one-account sign-in are verified, perform one authorized owned call and the full `scripts/live_check.py` procedure in [HOST_VERIFICATION.md](HOST_VERIFICATION.md).

The expected outcome is safer future operation and honest handling of rejected keys—not resurrection of an invalidated authorization. Existing encrypted data and production configuration remain necessary and preserved. Full automated source/image and restricted HTTP/Mongo evidence: [../TEST_REPORT.md](../TEST_REPORT.md).
