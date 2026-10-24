> **Historical 1.4.3 transport analysis:** the newer export establishes confirmed duplicated authorizations, not just an unknown transport failure. Follow [SESSION_SAFETY.md](SESSION_SAFETY.md) before requesting another login. The future-ownership/transport fixes below remain included.

# Transport failures, SDK futures and saved sessions — 1.4.3

## What the new supplied log actually establishes

The new attachment contains **26 records**: 6 information, 12 warnings and 8 errors. The non-information events are:

| Event | Count |
|---|---:|
| Connection ended: `InvalidBufferError` | 8 |
| Connection ended: `ConnectionError` | 3 |
| Async background exception not retrieved | 6 |
| Account connect: `TimeoutError` | 2 |
| Native leave: `MTProtoClientNotConnected` | 1 |

Three async records name `InvalidBufferError` with a traceback passing through the SDK's reconnect `get_me`; three name `ConnectionError` without frames. This is real deployment evidence of transport failures and incomplete exception ownership. **It does not prove an account ban, revocation or deletion of saved session data.** The attachment omits the wire error's numeric code, so do not retroactively assume all eight buffers were 404 or 429. Its startup line also does not identify an exact release; new startup logging includes the code version.

No production identifiers, raw packets, credentials or attachment contents are reproduced in source/tests.

## Reproduced SDK cause, not just quieter logging

The installed, pinned Telethon **1.45.0** `MTProtoSender._keepalive_ping()` calls `send(PingRequest(...))` and intentionally does not await/retain its returned future. A terminal disconnect sets an exception on pending request futures, including that ping. Watching only `client.disconnected` cannot retrieve a different ignored RPC future.

A controlled **real SDK, no-network** reproduction produced one unobserved `InvalidBufferError` event from such a ping. The fixed version retrieves it, reports typed transport health, and produces no unobserved event. The traceback of a shared exception object can include the reconnect `get_me` await even when that coroutine caught its own exception; those frames alone do not identify which other future was abandoned.

`TelegramLifecycle` now observes the **actual original futures** returned by that client's sender, including batches. Future results, cancellation and errors seen by real awaiters remain unchanged. SDK reconnect callbacks/tasks are strongly owned, closed and drained during pool-owned retirement. Unsent owned request futures are settled only after confirmed SDK disconnection. Unknown/still-connected/stubborn cleanup cannot certify safe replacement.

This is per-instance integration with the pinned SDK, not a global asyncio exception handler or SDK class patch. It does not hide arbitrary loop errors or disable logging. It keeps the exact `TelegramClient` class/module: PyTgCalls identifies the MTProto implementation by its module, so a custom subclass in `app.*` would break that bridge. Tests check the real bridge.

## Safe transport classification and recovery

- New typed connection diagnostics include only `error` class and safe numeric `transport_code`, never packet bytes, request representations or exception messages.
- An `InvalidBufferError` can have code **404**, **429**, another numeric code or no code. `AuthKeyNotFound` also means the transport currently cannot recognize the key.
- **404 / AuthKeyNotFound is not automatically a ban/revocation.** It may be temporary or permanent according to the SDK. Preserve the encrypted authorization and use bounded, identity-validated recovery. Persistent rejection can still require a consented new sign-in; this code cannot recreate a key Telegram no longer accepts.
- **429** gets a conservative **local minimum 900-second pause**. The packet supplies no retry-after, so 900 is a local safety policy, not a claimed Telegram deadline. An already longer Telegram cooldown/backoff is never shortened. Do not repeatedly retry OTP, rotate identities or bypass restrictions.
- Confirmed RPC revocation/deactivation/ban handling remains honest and protected. Encrypted data is retained; automatic OTP/login and automatic remote logout are not introduced.
- Saved-session handshakes are paced before connect and recheck generation/enabled/wait state after pacing. Existing 25-second connect and bounded self validation timeouts remain; timing out retains the saved authorization, owns cleanup and backs off instead of looping logins.
- The SDK's post-reconnect identity notification is paced and checked against current saved/retired ownership, staff disable, auth stops, generation/epoch and cooldown before its request. Normal consented temporary sign-in clients remain supported.
- Terminal failure immediately excludes that slot and closes only its native callback gate, preventing new SDK broadcast/RPC callbacks while owned cleanup proceeds. Old/stale persistence workers cannot change a newer authorization.

A real network failure can still occur. The fix is to handle it accurately and recover valid authorizations safely, not claim Telegram/network errors can never happen.

## Native leave after transport loss

PyTgCalls' `leave_call` checks MTProto connectivity before its local binding stop. Calling it after transport loss can therefore raise `MTProtoClientNotConnected` before stopping native resources.

Known disconnected/denied/cooldown/unknown-authority transports skip the remote leave request. The existing per-adapter lifecycle closes callbacks, drains work, stops local native transports, disconnects only the owned Telegram client and shuts down only its executor. Replacement remains blocked while cleanup is uncertain. A disconnect racing a leave is recorded as local cleanup required, **not a successful remote leave**. The stored encrypted session is not erased.

The 1.4.1 verified-already-absent handling and 1.4.2 post-wait/post-start native authority checks remain. Generic uncertain leave failures are still quarantined; no blanket ignore-all-errors change was made.

## Deploy without losing saved accounts

1. Back up Mongo and separately preserve the **original encryption key/private configuration**. Use the complete new source, but never overwrite those private files with the ZIP's public starter config.
2. Keep the same database/volumes and one app replica. Rebuild/recreate only the app, allowing graceful old-process shutdown and singleton lease handover. Do not start a second session runtime, generate another key, delete accounts/data or run `down -v`.
3. Confirm startup reports **1.4.3**. Existing valid sessions reconnect when their stored waits permit. A temporarily offline account is not a request for another OTP.
4. Run `/health` inside the existing bot. Do not perform a fresh production reauthentication just to test an already valid saved session.
5. During one authorized owned managed test call, run the read-only host checker and return its sanitized JSON. It must not be launched as a second bot runtime.

```sh
docker compose exec -T app python scripts/live_check.py
```

Exact safe commands, exit-code meanings and manual signup/QR/restart/call-stop observations are in [HOST_VERIFICATION.md](HOST_VERIFICATION.md). Source/container results are in [../TEST_REPORT.md](../TEST_REPORT.md). Real user-host Telegram/RTC acceptance is still pending your report; no production login/call was performed by the assistant.

Never deliberately provoke bans, duplicated authorization, FloodWait or destructive production network events as a test. Use authorized controlled staging scenarios and respect Telegram/moderator restrictions.
