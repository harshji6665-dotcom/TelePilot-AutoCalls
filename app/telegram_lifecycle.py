"""Per-client future/task ownership for pinned Telethon 1.45.0.

MTProtoSender._keepalive_ping intentionally ignores send()'s Future. A terminal
network error sets an exception on that same Future: observing only the public
'disconnected' future cannot retrieve it. Observe the actual sender futures
without changing their result/cancellation/exception semantics or asyncio's
exception handler. Keep the real TelegramClient class/module for PyTgCalls.
"""

import asyncio
from contextlib import suppress
from functools import wraps
import logging

from telethon import functions, errors
from telethon.errors.common import AuthKeyNotFound, InvalidBufferError
from telethon.network.mtprotosender import MTProtoSender

logger = logging.getLogger(__name__)
TRANSPORT_FLOOD_BACKOFF = 900  # Local minimum, NOT a claimed Telegram retry-after.


def transport_code(error):
    if isinstance(error, AuthKeyNotFound):
        return 404
    value = getattr(error, "code", None) if isinstance(error, InvalidBufferError) else None
    return value if type(value) is int and 100 <= value <= 599 else None


class TelegramLifecycle:
    def __init__(self, client, on_failure, before_reconnect=None, wire_guard=None, before_connect=None):
        self.client, self.on_failure, self.before_reconnect = client, on_failure, before_reconnect
        self.futures, self.tasks, self.reported = set(), set(), set()
        self.closing = False
        self.wire_guard, self.before_connect = wire_guard, before_connect
        self.connections = {}
        sender = client._sender
        if not isinstance(sender, MTProtoSender) or not callable(sender.send):
            raise RuntimeError("Pinned Telethon sender shape changed; transport integration requires review.")
        self.sender = sender
        original_send = sender.send

        @wraps(original_send)
        def send(request, ordered=False):
            if self.wire_guard:
                self.wire_guard()
            self.observe_sender()
            result = original_send(request, ordered=ordered)
            # Ignored keepalive errors need a typed health event as well as
            # retrieval. Ordinary RPC errors stay with their existing callers.
            ping = isinstance(request, functions.PingRequest)
            self.observe(result, notify=ping)
            return result  # EXACT original Future/list, never a replacement.

        sender.send = send
        original_connect = sender.connect

        @wraps(original_connect)
        async def connect(connection):
            self.guard_connection(connection)
            if self.wire_guard:
                self.wire_guard()
            return await original_connect(connection)

        sender.connect = connect
        original_reconnect = sender._auto_reconnect_callback
        if original_reconnect:

            @wraps(original_reconnect)
            async def reconnect():
                if self.closing:
                    return None
                task = asyncio.current_task()
                self.tasks.add(task)
                self.observe(task)
                self.observe_sender()
                try:
                    if self.before_reconnect and not await self.before_reconnect(client):
                        return None
                    if self.closing:
                        return None
                    return await original_reconnect()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning("SDK reconnect callback failed; error=%s transport_code=%s", type(error).__name__, transport_code(error))
                    # The SDK creates this task without awaiting its result.
                    # Report the failure explicitly, without raw RPC/payload text.
                    self.report(error)
                    return None
                finally:
                    self.observe_sender()
                    self.tasks.discard(task)

            sender._auto_reconnect_callback = reconnect
        self.observe_sender()

    def guard_connection(self, connection):
        if id(connection) in self.connections:
            return
        self.connections[id(connection)] = connection
        original_connect, original_send = connection.connect, connection._send

        @wraps(original_connect)
        async def connect(*args, **kwargs):
            if self.closing:
                raise ConnectionError("Retired Telegram transport cannot reconnect")
            if self.wire_guard:
                self.wire_guard()
            if self.before_connect and not await self.before_connect(self.client):
                raise ConnectionError("Saved-session reconnect is paused by ownership/cooldown checks")
            if self.wire_guard:
                self.wire_guard()
            return await original_connect(*args, **kwargs)

        @wraps(original_send)
        def send(data):
            if self.closing:
                raise ConnectionError("Retired Telegram transport cannot write")
            if self.wire_guard:
                self.wire_guard()  # Before writer.write, not just before enqueue.
            return original_send(data)

        connection.connect, connection._send = connect, send

    def report(self, error):
        if self.closing and not isinstance(error, errors.AuthKeyDuplicatedError):
            return
        wait = getattr(error, "seconds", None)
        wait = wait if type(wait) is int and 0 <= wait <= 31_536_000 else None
        key = (type(error), transport_code(error), wait)
        if key in self.reported:
            return
        try:
            if self.on_failure(self.client, error) is not False:
                self.reported.add(key)
        except Exception as callback_error:
            logger.error("Transport event callback failed; error=%s", type(callback_error).__name__)

    def observe(self, value, notify=False):
        if isinstance(value, (list, tuple)):
            for item in value:
                self.observe(item, notify=notify)
            return value
        if not isinstance(value, asyncio.Future) or value in self.futures:
            return value
        self.futures.add(value)

        def done(future):
            self.futures.discard(future)
            if not future.cancelled():
                error = future.exception()
                if error is not None and (notify or isinstance(error, errors.AuthKeyDuplicatedError)):
                    self.report(error)

        value.add_done_callback(done)
        return value

    def observe_sender(self):
        # Direct ownership avoids allocating extra shield futures for polling.
        # _connect replaces this future; send/connect/reconnect hooks re-arm it.
        self.observe(self.sender._disconnected)
        task = getattr(self.sender, "_reconnect_task", None)
        if isinstance(task, asyncio.Task):
            self.observe(task)

    def quiesce(self):
        self.closing = True
        self.observe_sender()
        current = asyncio.current_task()
        tasks = set(self.tasks)
        reconnect = getattr(self.sender, "_reconnect_task", None)
        if isinstance(reconnect, asyncio.Task):
            tasks.add(reconnect)
        for task in tasks - {current}:
            if not task.done():
                task.cancel()

    async def drain(self, timeout=5):
        # Only this client's reconnect work. SDK disconnect owns send/recv loops.
        await asyncio.sleep(0)
        tasks = set(self.tasks)
        reconnect = getattr(self.sender, "_reconnect_task", None)
        if isinstance(reconnect, asyncio.Task):
            tasks.add(reconnect)
        tasks.discard(asyncio.current_task())
        pending = {task for task in tasks if not task.done()}
        if pending:
            _, pending = await asyncio.wait(pending, timeout=timeout)
        for task in tasks - pending:
            if not task.cancelled():
                with suppress(Exception):
                    task.exception()
        return not pending

    async def finish(self, timeout=5):
        """Only AFTER confirmed SDK disconnect: settle unsent owned requests.

        The SDK cancels pending sent requests but may leave queued ping futures.
        No same-client reuse follows this permanent pool-owned retirement.
        DC migration does not call this method.
        """
        okay = await self.drain(timeout)
        if self.client.is_connected():
            return False
        if okay:
            for future in list(self.futures):
                if not isinstance(future, asyncio.Task) and not future.done():
                    future.cancel()
            await asyncio.sleep(0)
        return okay
