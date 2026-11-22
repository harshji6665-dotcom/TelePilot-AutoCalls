# Supplied runtime-log audit and cleanup changes — 1.4.0

The supplied JSON log contained **159 entries: 145 info, 13 error and 1 warning**. This document deliberately excludes raw records, account/chat identifiers, credentials and session material.

## Observed evidence vs conclusions

| Evidence | What can be concluded |
|---|---|
| Five asyncio `Future exception was never retrieved` entries with `ConnectionError` / connection retry exhaustion | Terminal/background connection failures were not all being observed by their owner. The log does not establish the host/network cause. |
| Destroyed pending PyTgCalls broadcast-part and Telethon send/receive tasks; `coroutine ignored GeneratorExit` | Some asynchronous transport work outlived cleanup/ownership. This warrants task ownership/draining, not blanket exception suppression. |
| Repeated “Call leave completed or already disconnected” info messages | The prior catch-all branch claimed completion even when it caught an arbitrary failure. It did not prove successful leave. |
| A final notification `TelegramBadRequest`, without the response reason | Delivery failed. The specific reason cannot be recovered from this attachment. HTML, permissions, recipient state and other causes must not be asserted as proven. |

This is a source/evidence audit, not a claim that a plan bug caused all network failures or that a deployment upgrade fixes unreachable Telegram routes.

## Implemented changes

### Observe connection futures

The pool's Telethon factory keeps the real TelegramClient class (required by the pinned SDK bridge) and observes its public `disconnected` future after connection attempts. Exception results are retrieved and logged by **type**, not by request/exception repr.

An unexpectedly disconnected live slot is immediately excluded from reservation and gets an owned background health update. Idle periodic/manual health paths retire/reload the old transport instead of incorrectly demanding a new OTP for a network-only disconnect. Staff's encrypted session/key are preserved. Atomic `$max` cooldown writes prevent a short connection cooldown or shorter later wait from replacing a longer existing Telegram FloodWait.

### Own native callbacks per adapter

Pinned PyTgCalls 3.0.1 exposes no public `stop()` method. Its NTgCalls callback bridge previously scheduled coroutines through discarded `run_coroutine_threadsafe` futures. The application now owns the eleven native callback registrations for the pinned 3.0.1/3.0.7 pair and the SDK MTProto update handler:

- retain strong references to actual running callback Tasks and their concurrent futures;
- retrieve failures without changing the future result the caller receives;
- log safe callback/type evidence; repeated identical callback errors are rate-limited with a repeat count;
- close the callback gate before teardown; late callbacks allocate no new coroutine;
- remove **only** Raw handlers added by this adapter, leaving unrelated handlers/other accounts alone;
- cancel and await the actual callback Tasks, not only the concurrent futures whose cancellation may finish earlier;
- stop remaining known local native transports without discarding/ending the group's Telegram call;
- disconnect Telethon and join the adapter executor using a worker thread rather than blocking the event loop.

No global asyncio monkeypatch, global SDK shutdown, recording, publishing or moderation bypass is added. Local compatibility checks require the pinned versions/bridge methods; upstream updates remain advisory and must be tested before changing pins.

### Keep disconnect cleanup owned

Telethon shields an internal disconnect Task. Cancelling an outer `wait_for` can otherwise abandon ownership while its send/receive cleanup is still running. Application cleanup now retains the public future, uses bounded non-cancelling waits, and keeps detach in an owned task shielded from cancellation of its job/UI/health caller. Pool shutdown waits for those same tasks.

An identity whose local stop/drain/disconnect is not proven complete is **quarantined**, not immediately reattached/reserved. Strong references and a typed `TransportCleanupPending` status are retained. It can be retried by pool teardown/disable handling; unresolved cases need operator investigation/restart, not repeated blind reuse. Session ciphertext is not erased for a network/cleanup failure. No library can guarantee orderly cleanup after SIGKILL, power loss or a permanently unresponsive native operation.

### Finish HTTP lifespan shutdown cleanly

A separate real non-root/read-only image probe (not the supplied production log) exposed an idle Uvicorn lifespan `CancelledError`: shutdown signalled the server, then cancelled its task before it could finish. The runtime now allows a bounded graceful HTTP/lifespan drain before cancelling remaining workers, with an explicit deadline warning if it cannot complete. A real-socket regression checks the HTTP task exits normally rather than being cancelled. This does not hide a failed shutdown.

### Tell the truth about leave failures

Arbitrary leave exceptions are now typed warning events rather than success-sounding info. A failed leave triggers the existing fail-closed transport retirement even if a cached calls map is empty. Pending joins/uncertain cleanup continue to retire the transport; protection was not disabled to hide the error.

### Protect notifications and improve future diagnostics

Source review found `text[:3900]` slicing raw HTML. That can cut a tag/entity, and Python character count does not handle Telegram's UTF-16 bounds for supplementary emoji. This is a **potential independent defect**, not the proven reason for the supplied BadRequest.

Notifications now preserve short HTML and conservatively bound oversized content without slicing tags/entities/UTF-16 characters. Oversized messages become escaped plain-format content with a visible details hint. A known HTML/length rejection gets one plain-format fallback, also repairing legacy queued malformed HTML; unknown BadRequests are not falsely classified as formatting failures.

Failures retain the exception class plus a closed safe category (`html_parse`, `message_too_long`, `chat_not_found`, `invalid_keyboard`, `write_forbidden`, or `unknown_bad_request`). Known permanent recipient/permission/keyboard rejections stop retrying; unknown/transient failures remain bounded retries. No Telegram response text, request body or credential-bearing repr is serialized. Outbox deduplication remains.

### Sanitize asyncio diagnostics, not their severity

The standard asyncio default log message embeds raw Task/Future/coroutine reprs, potentially including exception or argument data. Those messages now have safe lifecycle categories while retaining severity and exception type/traceback frames when supplied. Logs are **not disabled** and the event-loop exception handler is not replaced with a no-op. Ownership fixes address the task/future lifecycle itself; sanitizer changes alone are not presented as a runtime repair.

## Automated verification and limits

New tests cover cross-thread callback submission/bursts, actual Task draining/finalizers, late callback gating, safe exception retrieval, isolation of Raw-handler removal, changed callback rejection, real pinned SDK registration shape, empty native binding cleanup, bounded pending/shielded disconnects, cancelled detach callers, quarantine/session retention, cooldown preservation, manual health reload, and notification formatting/fallback/classification.

The real pinned Telethon/PyTgCalls/NTgCalls packages are imported and the empty native binding is exercised. Tests **do not connect real accounts or join a live voice chat**. SDK registration and asyncio behavior are verified locally; an active Telegram RTC transport must still be verified on the user's authorized host.

## Host follow-up

After rebuilding/redeploying one replica with the original key/database, inspect the new typed health/cleanup evidence. Check network reachability/DNS/egress rules, Telegram-related service disruptions and actual CPU/RAM/file-descriptor pressure. The attachment alone cannot select one of those as the cause. Test a small authorized call first, then staged load, cancellation and graceful stop. Do not raise global capacity or bypass FloodWait/moderation to mask failures.
