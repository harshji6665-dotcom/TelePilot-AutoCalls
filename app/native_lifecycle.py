"""Per-adapter task ownership for the pinned PyTgCalls 3.0.0/NTgCalls 3.0.3.

The SDK has no public stop(). Its native thread callbacks otherwise discard
run_coroutine_threadsafe futures. Keep task/future ownership, close the callback
gate, remove only this adapter's Raw handlers and drain before disconnecting.
Never monkeypatch asyncio or close another account's/global SDK session.
"""

import asyncio
from concurrent.futures import Future
from contextlib import suppress
import inspect
import logging
import threading
import time

logger = logging.getLogger(__name__)

CALLBACK_METHODS = {
    "on_stream_end": "_handle_stream_ended",
    "on_upgrade": "_update_status",
    "on_connection_change": "_handle_connection_changed",
    "on_update_emojis": "_handle_emojis_update",
    "on_signaling_data": "_app.send_signaling",
    "on_frames": "_handle_stream_frame",
    "on_request_broadcast_part": "_request_broadcast_part",
    "on_request_broadcast_timestamp": "_request_broadcast_timestamp",
    "on_outbound_block": "_app.send_conference_call_broadcast",
    "on_request_participants": "_handle_request_participants",
    "on_subchain_request": "_handle_subchain_request",
}


def handlers_snapshot(client):
    method = getattr(client, "list_event_handlers", None)
    if not callable(method) or inspect.iscoroutinefunction(method):
        return []
    handlers = method()
    return list(handlers) if isinstance(handlers, (tuple, list)) else []


class OwnedBinding:
    def __init__(self, owner, binding):
        self.owner, self.binding = owner, binding

    def __getattr__(self, name):
        original = getattr(self.binding, name)
        if not name.startswith("on_"):
            return original
        if name not in CALLBACK_METHODS:
            raise RuntimeError("Native callback signature changed; review pinned SDK integration.")

        def register(_sdk_callback):
            method = self.owner.app
            for part in CALLBACK_METHODS[name].split("."):
                method = getattr(method, part)
            return original(lambda *args: self.owner.submit(name, method, args))

        return register


class NativeLifecycle:
    def __init__(self, app, client, previous_handlers, account_id):
        self.app, self.client, self.account_id = app, client, account_id
        self.loop = asyncio.get_running_loop()
        self.binding = app._binding
        self.tasks, self.futures = set(), set()
        self.lock = threading.RLock()
        self.closing = False
        self.error_log = {}
        previous = {(id(callback), id(builder)) for callback, builder in previous_handlers}
        self.handlers = [
            (callback, builder) for callback, builder in handlers_snapshot(client) if (id(callback), id(builder)) not in previous
        ]
        app._binding = OwnedBinding(self, self.binding)
        original_update = app._handle_mtproto_updates

        async def owned_update(update):
            return await self.run_owned("mtproto_update", original_update, (update,))

        app._handle_mtproto_updates = owned_update

    async def run_owned(self, name, method, args):
        if self.closing:
            return None
        task = asyncio.current_task()
        self.tasks.add(task)  # Strong reference until actual coroutine completion.
        try:
            return await method(*args)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            key = (name, type(exc).__name__)
            previous, skipped = self.error_log.get(key, (0.0, 0))
            if time.monotonic() - previous >= 60:
                logger.warning(
                    "Native callback failed; account=%s callback=%s error=%s repeated=%s", self.account_id, name, key[1], skipped
                )
                self.error_log[key] = (time.monotonic(), 0)
            else:
                self.error_log[key] = (previous, skipped + 1)
            raise
        finally:
            self.tasks.discard(task)

    def future_done(self, future):
        # concurrent Future exceptions are retrieved without changing what its
        # caller receives. Never serialize callback args, frames or RPC text.
        if not future.cancelled():
            with suppress(Exception):
                future.exception()
        with self.lock:
            self.futures.discard(future)

    def submit(self, name, method, args):
        with self.lock:
            if self.closing or self.loop.is_closed():
                future = Future()
                future.set_result(None)
                return future  # No coroutine allocated after closure.
            coro = self.run_owned(name, method, args)
            try:
                future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            except RuntimeError:
                coro.close()
                raise
            self.futures.add(future)
            future.add_done_callback(self.future_done)
            return future

    def quiesce(self):
        with self.lock:
            self.closing = True
            for future in list(self.futures):
                future.cancel()
        for callback, _builder in self.handlers:
            self.client.remove_event_handler(callback)
        self.handlers.clear()
        self.app._is_running = False

    async def drain(self, timeout=5):
        # Threadsafe submissions accepted just before gate closure can be queued
        # on this loop; give them a turn, then await actual Tasks (not merely the
        # concurrent futures whose cancellation can complete ahead of finally).
        await asyncio.sleep(0)
        tasks = set(self.tasks) - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        if not tasks:
            return True
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in done:
            if not task.cancelled():
                task.exception()
        if pending:
            logger.error("Native callback drain timed out; account=%s pending=%s", self.account_id, len(pending))
        return not pending

    async def stop_local(self, timeout=5):
        # Stop only locally existing transports; do not discard/end anyone's
        # Telegram group call or pretend a failed leave RPC succeeded.
        calls = await asyncio.wait_for(self.binding.calls(), timeout)
        okay = True
        for chat_id in list(calls):
            try:
                await asyncio.wait_for(self.binding.stop(chat_id), timeout)
            except Exception as exc:
                okay = False
                logger.warning("Native transport stop failed; account=%s error=%s", self.account_id, type(exc).__name__)
        return okay
