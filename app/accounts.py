from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from contextlib import suppress
import logging
import inspect
import time
import secrets
import random
from collections import Counter

from telethon import TelegramClient, errors, functions, types, utils

from .session_state import (
    AUTH_BLOCKED,
    RECOVERY_BLOCKED,
    CONFIRMED_BANS,
    DurableStringSession,
    auth_status,
    session_guard,
    session_value,
    fingerprint,
    recovery_delay,
    recovery_hint,
)
from .native_lifecycle import NativeLifecycle, handlers_snapshot
from .config import POOL_ACCOUNT_CEILING
from .session_safety import SessionSafety
from .telegram_lifecycle import TelegramLifecycle, transport_code, TRANSPORT_FLOOD_BACKOFF
from .links import TelegramLink
from .security import UserError, html
from .timeutils import now

logger = logging.getLogger(__name__)
FATAL_AUTH = (
    errors.AuthKeyUnregisteredError,
    errors.AuthKeyDuplicatedError,
    errors.SessionRevokedError,
    errors.SessionExpiredError,
    errors.UserDeactivatedError,
    errors.UserDeactivatedBanError,
    errors.PhoneNumberBannedError,
)
BANNED = CONFIRMED_BANS

# Realistic client fingerprints to reduce clustering / detection risk.
# Rotate across common official Telegram client profiles.
DEVICE_PROFILES = [
    {"device_model": "Samsung SM-S918B", "system_version": "SDK 34", "app_version": "11.2.2"},
    {"device_model": "Samsung SM-A546B", "system_version": "SDK 33", "app_version": "10.14.5"},
    {"device_model": "Xiaomi 2211133G", "system_version": "SDK 34", "app_version": "11.1.3"},
    {"device_model": "Xiaomi 23013PC75G", "system_version": "SDK 33", "app_version": "10.14.5"},
    {"device_model": "Google Pixel 8", "system_version": "SDK 34", "app_version": "11.2.2"},
    {"device_model": "Google Pixel 7", "system_version": "SDK 33", "app_version": "10.14.5"},
    {"device_model": "OnePlus CPH2449", "system_version": "SDK 34", "app_version": "11.1.3"},
    {"device_model": "iPhone 15 Pro", "system_version": "17.4.1", "app_version": "10.14.5"},
    {"device_model": "iPhone 14", "system_version": "17.2", "app_version": "10.13.1"},
    {"device_model": "iPhone 13", "system_version": "16.6", "app_version": "10.12.0"},
    {"device_model": "Desktop", "system_version": "Windows 11", "app_version": "5.6.1 x64"},
    {"device_model": "Desktop", "system_version": "Windows 10", "app_version": "5.5.5 x64"},
    {"device_model": "MacBookPro18,1", "system_version": "macOS 14.4", "app_version": "10.14.5"},
    {"device_model": "MacBookAir10,1", "system_version": "macOS 13.6", "app_version": "10.13.1"},
]


class SessionChanged(UserError):
    """A newer authorization replaced this connection while it was validating."""


class SessionIdentityMismatch(UserError):
    """Successful authorization belongs to the wrong identity; never reuse it."""


class RateGate:
    """Cooperative pacing with light human-like jitter. FloodWait always wins."""

    def __init__(self, gap):
        self.gap, self.next_at = max(0.5, float(gap)), 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            await asyncio.sleep(max(0, self.next_at - time.monotonic()))
            # Stronger human-like jitter (25–70%) to avoid regular patterns.
            jitter = self.gap * random.uniform(0.25, 0.70)
            self.next_at = time.monotonic() + self.gap + jitter


@dataclass
class Slot:
    account_id: str
    client: TelegramClient
    busy_job: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    join_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    call_client: object | None = None
    native_owner: object | None = None
    closing: bool = False
    disconnected: bool = False
    connection_epoch: str | None = None
    session_generation: str | None = None
    session_ciphertext: str | None = None
    session_fingerprint: str | None = None
    validated_fingerprint: str | None = None
    member_chats: set[int] = field(default_factory=set)
    forbidden_chats: set[int] = field(default_factory=set)
    closed_chats: set[int] = field(default_factory=set)
    leaving_chats: set[int] = field(default_factory=set)
    joining_chats: set[int] = field(default_factory=set)


class AccountPool:
    def __init__(self, store, access, vault, notifier, config):
        self.store, self.access, self.vault, self.notifier, self.config = store, access, vault, notifier, config
        self.slots: dict[str, Slot] = {}
        self.retired: dict[str, Slot] = {}
        self.cleanup_tasks = {}
        self.disconnects = {}
        self.disconnect_watches = {}
        self.connection_tasks = set()
        self.stopping = False
        self.client_registry = {}
        self.client_connect_tasks = {}
        self.safety = SessionSafety(self)
        self.recovery_wake = asyncio.Event()
        self.connecting = Counter()
        self.checkpoint_tasks = {}
        self.account_guards = {}
        self.retired_retry_at = {}
        self.attaching = {}
        self.lock = asyncio.Lock()
        self.sync_lock = asyncio.Lock()
        self.gate = RateGate(config.limits.global_rpc_gap_seconds)

    def make_client(self, session: str = ""):
        self.safety.require_allowed()
        durable = DurableStringSession(session)
        profile = random.choice(DEVICE_PROFILES)
        # Cloud hosts (Railway/Render) often drop idle MTProto or prefer broken
        # IPv6 paths. Prefer IPv4, more connect retries, and a longer socket
        # timeout so temporary blips do not strand the account offline.
        client = TelegramClient(
            durable,
            self.config.api_id,
            self.config.api_hash.get_secret_value(),
            device_model=profile["device_model"],
            system_version=profile["system_version"],
            app_version=profile["app_version"],
            lang_code="en",
            system_lang_code="en-US",
            flood_sleep_threshold=24,
            # A DC migration must get a subsequent attempt. Zero retries can
            # switch DC successfully and then end as generic ValueError.
            request_retries=5,
            raise_last_call_error=True,
            connection_retries=5,
            retry_delay=2,
            auto_reconnect=True,
            timeout=20,
            use_ipv6=False,
        )

        self.client_registry[id(client)] = client
        client._telepilot_transport = TelegramLifecycle(
            client, self.transport_failed, self.before_sdk_reconnect, self.safety.check_wire, self.before_network_connect
        )
        original_connect = client.connect

        async def connect_observed():
            key = id(client)
            self.connecting[key] += 1
            task = asyncio.current_task()
            self.client_connect_tasks.setdefault(key, set()).add(task)
            try:
                self.safety.require_allowed()
                client._telepilot_transport.observe_sender()
                return await original_connect()
            finally:
                client._telepilot_transport.observe_sender()
                self.connecting[key] -= 1
                self.client_connect_tasks.get(key, set()).discard(task)
                if not self.client_connect_tasks.get(key):
                    self.client_connect_tasks.pop(key, None)
                if not self.connecting[key]:
                    self.connecting.pop(key, None)
                self.watch_disconnection(client)

        durable.on_save = lambda: self.schedule_checkpoint(client)
        client.connect = connect_observed
        return client

    async def before_network_connect(self, client):
        # Runs BEFORE TCP open on initial connect AND every SDK reconnect, not
        # only in the post-reconnect callback after traffic already happened.
        if self.safety.blocked() or self.stopping or any(slot.client is client for slot in self.retired.values()):
            return False
        slot = next((slot for slot in self.slots.values() if slot.client is client), None)
        if not slot:
            return True  # Consented temporary/new attach; wire fence still applies.
        if slot.closing or slot.disconnected:
            return False
        row = await self.store.db.accounts.find_one({"_id": slot.account_id})
        return bool(
            row
            and row.get("enabled")
            and row.get("status") not in AUTH_BLOCKED
            and not row.get("authorization_block")
            and (not slot.connection_epoch or row.get("connection_epoch") == slot.connection_epoch)
            and (not slot.session_generation or row.get("session_generation") == slot.session_generation)
            and max(row.get("cooldown_until") or now(), row.get("next_recovery_at") or now()) <= now()
        )

    async def before_sdk_reconnect(self, client):
        # Pace the SDK's own post-reconnect getMe, not a new login/OTP. A
        # temporary login client is allowed; saved/retired ownership is fenced.
        if self.safety.blocked() or self.stopping or any(slot.client is client for slot in self.retired.values()):
            return False
        await self.gate.wait()
        if any(slot.client is client for slot in self.retired.values()):
            return False
        slot = next((slot for slot in self.slots.values() if slot.client is client), None)
        if not slot:
            return not self.stopping
        row = await self.store.db.accounts.find_one({"_id": slot.account_id})
        allowed = bool(row and row.get("enabled") and row.get("status") not in AUTH_BLOCKED and not row.get("authorization_block"))
        allowed = allowed and not slot.closing and not slot.disconnected
        allowed = allowed and (not slot.connection_epoch or row.get("connection_epoch") == slot.connection_epoch)
        allowed = allowed and (not slot.session_generation or row.get("session_generation") == slot.session_generation)
        allowed = allowed and max(row.get("cooldown_until") or now(), row.get("next_recovery_at") or now()) <= now()
        if not allowed:
            slot.disconnected = True
            self.recovery_wake.set()
        return bool(allowed and not self.stopping)

    def transport_failed(self, client, error):
        if isinstance(error, errors.AuthKeyDuplicatedError):
            if not self.safety.paused:
                self.safety.freeze()
            task = asyncio.create_task(self.persist_duplicate_failure(client), name="duplicated-authorization-stop")
            self.connection_tasks.add(task)
            task.add_done_callback(self.connection_done)
            return True
        if self.safety.paused or self.stopping or self.connecting.get(id(client)):
            return False  # A DC migration/connect caller still owns its result.
        slot = next((slot for slot in self.slots.values() if slot.client is client and not slot.closing), None)
        if not slot:
            return False
        slot.disconnected = True  # Immediate exclusion, before persistence.
        if slot.native_owner:
            try:
                slot.native_owner.quiesce()  # No new SDK broadcast/RPC callbacks after terminal failure.
            except Exception as native_error:
                logger.error("Native callback gate closure failed; error=%s", type(native_error).__name__)
        logger.warning("Telegram connection ended; error=%s transport_code=%s", type(error).__name__, transport_code(error))
        task = asyncio.create_task(self.persist_transport_failure(slot, error), name="transport-health")
        self.connection_tasks.add(task)
        task.add_done_callback(self.connection_done)
        return True

    async def persist_duplicate_failure(self, client):
        try:
            slot = next((slot for slot in list(self.slots.values()) + list(self.retired.values()) if slot.client is client), None)
            if slot:
                await self.set_status(slot.account_id, "revoked", "AuthKeyDuplicatedError", slot=slot)
            else:
                saved = getattr(client, "_telepilot_saved_record", None)
                if isinstance(saved, dict):
                    await self.set_status(saved["_id"], "revoked", "AuthKeyDuplicatedError", expected=saved)
        finally:
            await self.safety.persist()

    async def persist_transport_failure(self, slot, error):
        code = transport_code(error)
        if isinstance(error, errors.FloodWaitError):
            await self.cooldown(slot.account_id, error.seconds, slot=slot)
        elif code == 429:
            # The wire error provides NO retry-after. This is a conservative
            # local minimum; never shorten an existing Telegram wait.
            await self.cooldown(slot.account_id, TRANSPORT_FLOOD_BACKOFF, slot=slot)
        status = auth_status(error) if isinstance(error, FATAL_AUTH) else "offline"
        await self.set_status(slot.account_id, status, type(error).__name__, slot=slot, error_code=code)

    def watch_disconnection(self, client, future=None):
        owner = getattr(client, "_telepilot_transport", None)
        existing = self.disconnect_watches.get(id(client))
        if existing is not None and not existing.done():
            if isinstance(future, asyncio.Future):
                # A supplied shield may already exist. Never abandon it just
                # because another terminal watcher is installed.
                if isinstance(owner, TelegramLifecycle):
                    owner.observe(future)
                else:
                    future.add_done_callback(lambda item: item.exception() if not item.cancelled() else None)
            return
        future = future if future is not None else getattr(client, "disconnected", None)
        if not isinstance(future, asyncio.Future):
            return
        if isinstance(owner, TelegramLifecycle):
            owner.observe(future)
        self.disconnect_watches[id(client)] = future

        def done(future):
            if self.disconnect_watches.get(id(client)) is future:
                self.disconnect_watches.pop(id(client), None)
            if future.cancelled():
                return
            error = future.exception()
            if self.stopping:
                return
            connected = getattr(client, "is_connected", None)
            if self.connecting.get(id(client)):
                return
            if callable(connected) and connected():
                replacement = getattr(client, "disconnected", None)
                if isinstance(replacement, asyncio.Future):
                    if replacement.done():
                        if not replacement.cancelled():
                            replacement.exception()
                    else:
                        self.watch_disconnection(client, replacement)
                return  # Successful DC/transport replacement is not a logout.
            error = error or ConnectionError("Telegram transport disconnected")
            if isinstance(owner, TelegramLifecycle):
                owner.report(error)
            else:
                self.transport_failed(client, error)

        future.add_done_callback(done)

    def connection_done(self, task):
        self.connection_tasks.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error:
                logger.error("Connection health persistence failed; error=%s", type(error).__name__)

    async def disconnect_client(self, client, timeout=15):
        # Telethon shields its internal disconnect Task. wait_for() would cancel
        # the shield and lose ownership of the still-running send/receive cleanup.
        # asyncio.wait() leaves the public future owned until real completion.
        key = id(client)
        owner = getattr(client, "_telepilot_transport", None)
        if isinstance(owner, TelegramLifecycle):
            owner.quiesce()
        existing = self.disconnects.get(key)
        if existing and existing[1].done():
            # A completed failure is not a permanently cached disconnect result.
            error = None if existing[1].cancelled() else existing[1].exception()
            self.disconnects.pop(key, None)
            if not existing[1].cancelled() and error is None:
                okay = await owner.finish(min(5, timeout)) if isinstance(owner, TelegramLifecycle) else True
                if okay:
                    self.client_registry.pop(key, None)
                return okay
        if key not in self.disconnects:
            future = asyncio.ensure_future(client.disconnect())
            self.disconnects[key] = (client, future)

            def done(future):
                error = None if future.cancelled() else future.exception()
                current = self.disconnects.get(key)
                if not future.cancelled() and error is None and current and current[1] is future:
                    self.disconnects.pop(key, None)

            future.add_done_callback(done)
        future = self.disconnects[key][1]
        done, _ = await asyncio.wait({future}, timeout=timeout)
        if not done:
            logger.error("Telegram disconnect still pending; transport quarantined")
            return False
        if future.cancelled():
            return False
        error = future.exception()
        if error:
            logger.warning("Telegram disconnect failed; error=%s", type(error).__name__)
        okay = await owner.finish(min(5, timeout)) if error is None and isinstance(owner, TelegramLifecycle) else error is None
        if okay:
            self.client_registry.pop(key, None)
        return okay

    async def set_status(self, account_id, status, error_type=None, *, slot=None, expected=None, error_code=None):
        query = {"_id": account_id}
        if slot:
            if self.slots.get(account_id) is not slot and self.retired.get(account_id) is not slot:
                return False
            if status in {"offline", "revoked", "banned", "deactivated", "reauth_required", "storage_error"}:
                slot.disconnected = True
            if slot.connection_epoch:
                query["connection_epoch"] = slot.connection_epoch
            elif slot.session_generation:
                query["session_generation"] = slot.session_generation
            elif slot.session_ciphertext:
                query.update(session_guard({"session_ciphertext": slot.session_ciphertext}))
        elif expected:
            query.update(session_guard(expected))
        previous = await self.store.db.accounts.find_one(query)
        if not previous:
            return False
        if (previous.get("status") in AUTH_BLOCKED or previous.get("authorization_block")) and status in {"offline", "cooldown", "healthy"}:
            return False  # Cleanup/network callbacks cannot undo an auth stop.
        if status == "healthy" and not previous.get("enabled"):
            return False
        if status == "offline" and previous.get("status") == "disabled":
            return False
        if status == "healthy":
            query["enabled"] = True
        if status == "healthy" and slot and (slot.closing or slot.disconnected):
            return False
        duplicate = error_type == "AuthKeyDuplicatedError" and status in AUTH_BLOCKED
        if duplicate and not self.safety.paused:
            self.safety.freeze()
        fields = {"status": status, "last_health_at": now(), "last_error_type": error_type, "last_error_code": error_code}
        if error_code is not None:
            fields.update(last_transport_code=error_code, last_transport_at=now())
        update = {"$set": fields}
        # NEVER erase an encrypted authorization for an RPC/network/ban failure.
        # Only an explicit authorized replacement/removal may change/delete it.
        if status in AUTH_BLOCKED:
            fields["authorization_block"] = status
            fields["authorization_error_type"] = error_type
        if status == "banned":
            fields["enabled"] = False
        if status in {"offline", "storage_error"}:
            failures = min(32, previous.get("recovery_failures", 0) + 1)
            fields["recovery_failures"] = failures
            update["$max"] = {
                "cooldown_until": now() + timedelta(seconds=60),
                "next_recovery_at": now() + timedelta(seconds=recovery_delay(failures)),
            }
        elif status == "healthy":
            fields["recovery_failures"] = 0
            update["$unset"] = {"next_recovery_at": ""}
        try:
            result = await self.store.db.accounts.update_one(query, update)
        finally:
            if duplicate:
                await self.safety.persist()
        if not result.matched_count:
            return False
        if status in {"offline", "cooldown"} or status in AUTH_BLOCKED:
            self.recovery_wake.set()
        changed = previous.get("status") != status
        recovered = status == "healthy" and previous.get("recovery_failures", 0) > 0
        if changed and (status not in {"healthy", "disabled"} or recovered):
            alert = dict(previous, **fields)
            text = f"<b>Account {'recovered' if recovered else 'health alert'}</b>\n<blockquote>Account ID: <code>{html(account_id)}</code>\nStatus: {html(status)}\nError: <code>{html(error_type or '—')}</code>\n{html(recovery_hint(alert))}</blockquote>"
            await self.notifier.owners(text, f"account:{account_id}:{status}:{now().isoformat()}")
            if previous.get("added_by") not in self.config.owner_ids and previous.get("added_by"):
                await self.notifier.enqueue(previous["added_by"], text, f"account-admin:{account_id}:{status}:{now().isoformat()}")
            await self.store.audit(
                0,
                "account_health",
                account_id=account_id,
                status=status,
                error_type=error_type,
                error_code=error_code,
                session_preserved=bool(previous.get("session_ciphertext")),
            )
        return True

    def schedule_checkpoint(self, client):
        if self.stopping:
            return
        slot = next((item for item in self.slots.values() if item.client is client), None)
        if not slot or slot.closing or slot.disconnected or not slot.connection_epoch:
            return
        try:
            if fingerprint(session_value(client)) == slot.session_fingerprint:
                return
        except Exception:
            return  # A later health check can report a malformed SDK session.
        key = id(client)
        if key in self.checkpoint_tasks and not self.checkpoint_tasks[key].done():
            return
        task = asyncio.create_task(self.checkpoint_session(slot), name="saved-session-checkpoint")
        self.checkpoint_tasks[key] = task

        def done(task):
            if self.checkpoint_tasks.get(key) is task:
                self.checkpoint_tasks.pop(key, None)
            if not task.cancelled():
                error = task.exception()
                if error:
                    logger.warning("Saved session checkpoint needs retry; error=%s", type(error).__name__)
                    self.recovery_wake.set()

        task.add_done_callback(done)

    async def checkpoint_session(self, slot):
        # Serialization observes a key change, not proof that the key is valid.
        # Only a matching raw GetUsers(Self) authorizes a durable replacement.
        async with slot.lock:
            if self.slots.get(slot.account_id) is not slot or slot.closing or slot.disconnected:
                return False
            row = await self.store.db.accounts.find_one({"_id": slot.account_id, "connection_epoch": slot.connection_epoch})
            if not row or not row.get("enabled") or row.get("status") in AUTH_BLOCKED:
                return False
            if (row.get("cooldown_until") or now()) > now():
                return False
            value = session_value(slot.client)
            candidate = fingerprint(value)
            if not value or candidate == slot.session_fingerprint:
                return False
            if candidate != slot.validated_fingerprint:
                try:
                    await self.gate.wait()
                    response = await asyncio.wait_for(slot.client(functions.users.GetUsersRequest([types.InputUserSelf()])), 20)
                    me = response[0] if response else None
                    if not isinstance(me, types.User) or me.id != row["telegram_id"] or me.bot:
                        raise SessionIdentityMismatch("Session checkpoint identity mismatch.")
                    if me.deleted:
                        raise errors.UserDeactivatedError(None)
                    if fingerprint(session_value(slot.client)) != candidate:
                        return False  # Another migration occurred; validate its key next time.
                    slot.validated_fingerprint = candidate
                except errors.FloodWaitError as exc:
                    await self.cooldown(slot.account_id, exc.seconds, slot=slot)
                    return False
                except FATAL_AUTH as exc:
                    slot.disconnected = True
                    await self.set_status(slot.account_id, auth_status(exc), type(exc).__name__, slot=slot)
                    self.recovery_wake.set()
                    return False
                except SessionIdentityMismatch:
                    slot.disconnected = True
                    await self.set_status(slot.account_id, "reauth_required", "SessionIdentityMismatch", slot=slot)
                    self.recovery_wake.set()
                    return False
            cipher = self.vault.encrypt(value)
            result = await self.store.db.accounts.update_one(
                {"_id": slot.account_id, "connection_epoch": slot.connection_epoch, "session_generation": slot.session_generation},
                {"$set": {"session_ciphertext": cipher, "session_saved_at": now()}, "$inc": {"session_checkpoints": 1}},
            )
            if result.matched_count:
                slot.session_fingerprint, slot.session_ciphertext = candidate, cipher
                return True
            return False

    async def wait_for_recovery(self, timeout=15):
        try:
            await asyncio.wait_for(self.recovery_wake.wait(), timeout)
        except TimeoutError:
            pass
        finally:
            self.recovery_wake.clear()

    async def recover_due(self):
        """Light local tick; healthy clients are NOT RPC-probed every 15 seconds."""
        if self.safety.blocked():
            return
        ids = [row["_id"] async for row in self.store.db.accounts.find({}, {"_id": 1})]
        ids.extend(key for key in set(self.retired) | set(self.slots) if key not in ids)
        for account_id in ids:
            if self.stopping:
                return
            async with self.sync_lock:
                row = await self.store.db.accounts.find_one({"_id": account_id})
                slot = self.slots.get(account_id)
                if (
                    not row
                    or not row.get("enabled")
                    or row.get("status") in RECOVERY_BLOCKED
                    or row.get("authorization_block") in RECOVERY_BLOCKED
                    or not row.get("session_ciphertext")
                ):
                    if slot and (not slot.busy_job or row and row.get("status") in AUTH_BLOCKED):
                        await self.detach(account_id)
                    if account_id in self.retired and time.monotonic() >= self.retired_retry_at.get(account_id, 0):
                        await self.detach(account_id)
                    continue
                if slot and not slot.disconnected and not slot.closing:
                    self.schedule_checkpoint(slot.client)
                    continue
                if slot and slot.busy_job:
                    continue  # Its job owns cleanup/release; never double-allocate.
                if max(row.get("cooldown_until") or now(), row.get("next_recovery_at") or now()) > now():
                    continue
                if account_id in self.retired and time.monotonic() < self.retired_retry_at.get(account_id, 0):
                    continue
                if slot or account_id in self.retired:
                    await self.detach(account_id)
                if account_id not in self.retired and account_id not in self.slots:
                    await self.attach(account_id)

    async def request_recovery(self, actor, account_id):
        async with self.lock:
            row = await self.store.db.accounts.find_one({"_id": account_id})
            if not row:
                raise UserError("Account not found.")
            await self.access.can_manage_account(actor, row)
            if not row.get("enabled"):
                raise UserError("Account is disabled by staff. Enable it first; recovery never overrides a staff disable.")
            if (
                row.get("status") in RECOVERY_BLOCKED
                or row.get("authorization_block") in RECOVERY_BLOCKED
                or not row.get("session_ciphertext")
            ):
                raise UserError(recovery_hint(row))
            slot = self.slots.get(account_id)
            if slot and slot.busy_job:
                raise UserError("Account is busy; its active job owns the connection.")
            if slot and not slot.disconnected and not slot.closing:
                raise UserError("Saved session is already connected; no sign-in or reconnect is needed.")
            # Do not shorten a Telegram wait or network backoff to satisfy a button.
            self.recovery_wake.set()
        await self.store.audit(actor, "account_recovery_requested", account_id=account_id, session_preserved=True)

    async def cooldown(self, account_id, seconds, *, slot=None, expected=None):
        query = {"_id": account_id}
        if slot:
            if self.slots.get(account_id) is not slot and self.retired.get(account_id) is not slot:
                return
            if slot.connection_epoch:
                query["connection_epoch"] = slot.connection_epoch
            elif slot.session_generation:
                query["session_generation"] = slot.session_generation
            elif slot.session_ciphertext:
                query.update(session_guard({"session_ciphertext": slot.session_ciphertext}))
        elif expected:
            query.update(session_guard(expected))
        await self.store.db.accounts.update_one(
            query,
            {"$max": {"cooldown_until": now() + timedelta(seconds=max(1, seconds) + 1)}, "$set": {"last_error_type": "FloodWaitError"}},
        )

    async def attach(self, account_id):
        # Protect the public boundary too, not merely today's callers' locks.
        if self.stopping or account_id in self.attaching:
            return
        task = asyncio.current_task()
        self.attaching[account_id] = task
        try:
            await self.attach_owned(account_id)
        finally:
            if self.attaching.get(account_id) is task:
                self.attaching.pop(account_id, None)

    async def attach_owned(self, account_id):
        if self.safety.blocked():
            return
        if account_id in self.slots or account_id in self.retired or self.stopping:
            return
        row = await self.store.db.accounts.find_one({"_id": account_id})
        if (
            not row
            or not row.get("enabled")
            or not row.get("session_ciphertext")
            or row.get("status") in RECOVERY_BLOCKED
            or row.get("authorization_block") in RECOVERY_BLOCKED
        ):
            return
        if max(row.get("cooldown_until") or now(), row.get("next_recovery_at") or now()) > now():
            return
        client = None
        try:
            try:
                session = self.vault.decrypt(row["session_ciphertext"])
            except UserError:
                await self.set_status(account_id, "storage_error", "SessionDecryptError", expected=row)
                return
            original_fingerprint = fingerprint(session)
            try:
                client = self.make_client(session)
                client._telepilot_saved_record = {
                    "_id": account_id,
                    "session_generation": row.get("session_generation"),
                    "session_ciphertext": row.get("session_ciphertext"),
                }
            except (ValueError, TypeError):
                await self.set_status(account_id, "storage_error", "SessionFormatError", expected=row)
                return
            del session
            await self.gate.wait()  # Pace initial/recovery handshakes, not only the later self RPC.
            current = await self.store.db.accounts.find_one({"_id": account_id, "enabled": True, **session_guard(row)})
            if not current or current.get("status") in RECOVERY_BLOCKED or current.get("authorization_block") in RECOVERY_BLOCKED:
                raise SessionChanged("Saved authorization changed before reconnect.")
            if max(current.get("cooldown_until") or now(), current.get("next_recovery_at") or now()) > now():
                raise SessionChanged("A newer wait started before reconnect.")
            await asyncio.wait_for(client.connect(), 25)
            await self.gate.wait()
            me = (await asyncio.wait_for(client(functions.users.GetUsersRequest([types.InputUserSelf()])), 20))[0]
            if not isinstance(me, types.User) or me.id != row["telegram_id"] or me.bot:
                raise SessionIdentityMismatch("Stored session identity mismatch.")
            if me.deleted:
                raise errors.UserDeactivatedError(None)
            value = session_value(client)
            current_fingerprint = fingerprint(value) or original_fingerprint
            epoch = secrets.token_hex(16)
            generation = row.get("session_generation") or secrets.token_hex(16)
            cipher = row["session_ciphertext"]
            if value and current_fingerprint != original_fingerprint:
                cipher = self.vault.encrypt(value)
            if self.stopping or self.safety.blocked():
                raise SessionChanged("Runtime stopped/paused while connecting; saved authorization retained.")
            result = await self.store.db.accounts.update_one(
                {
                    "_id": account_id,
                    "enabled": True,
                    "status": {"$nin": list(RECOVERY_BLOCKED)},
                    "authorization_block": {"$nin": list(RECOVERY_BLOCKED)},
                    **session_guard(row),
                },
                {
                    "$set": {
                        "connection_epoch": epoch,
                        "session_generation": generation,
                        "session_ciphertext": cipher,
                        "session_saved_at": now(),
                        "status": "offline",  # Identity proved; publish ready only after RAM ownership.
                    },
                    "$unset": {"authorization_block": "", "authorization_error_type": ""},
                },
            )
            if not result.matched_count:
                raise SessionChanged("Saved authorization changed while connecting.")
            slot = Slot(
                account_id,
                client,
                connection_epoch=epoch,
                session_generation=generation,
                session_ciphertext=cipher,
                session_fingerprint=current_fingerprint,
                validated_fingerprint=current_fingerprint,
            )
            slot.forbidden_chats.update(self.account_guards.get(account_id, set()))
            self.slots[account_id] = slot
            await self.set_status(account_id, "healthy", slot=slot)
        except FATAL_AUTH as exc:
            await self.set_status(account_id, auth_status(exc), type(exc).__name__, expected=row)
        except errors.FloodWaitError as exc:
            await self.cooldown(account_id, exc.seconds, expected=row)
            await self.set_status(account_id, "cooldown", type(exc).__name__, expected=row)
        except SessionChanged:
            logger.info("Discarding stale reload after saved authorization changed; account=%s", account_id)
        except SessionIdentityMismatch:
            await self.set_status(account_id, "reauth_required", "SessionIdentityMismatch", expected=row)
        except Exception as exc:
            code = transport_code(exc)
            logger.warning("Account connect failed; account=%s error=%s transport_code=%s", account_id, type(exc).__name__, code)
            if code == 429:
                await self.cooldown(account_id, TRANSPORT_FLOOD_BACKOFF, expected=row)
            await self.set_status(
                account_id,
                "storage_error" if row.get("status") == "storage_error" else "offline",
                type(exc).__name__,
                expected=row,
                error_code=code,
            )
        finally:
            if client and account_id not in self.slots:
                self.retired[account_id] = Slot(
                    account_id,
                    client,
                    closing=True,
                    connection_epoch=row.get("connection_epoch"),
                    session_generation=row.get("session_generation"),
                    session_ciphertext=row.get("session_ciphertext"),
                )
                with suppress(Exception):
                    await self.detach(account_id)

    async def sync(self):
        # Never hold the lifecycle lock across the whole roster. New sign-ins,
        # removals and re-authentication can interleave between account checks.
        if self.safety.blocked():
            return
        ids = [row["_id"] async for row in self.store.db.accounts.find({}, {"_id": 1})]
        ids.extend(key for key in set(self.slots) | set(self.retired) if key not in ids)
        for account_id in ids:
            if self.safety.blocked():
                return
            async with self.sync_lock:
                row = await self.store.db.accounts.find_one({"_id": account_id})
                slot = self.slots.get(account_id)
                if (
                    not row
                    or not row.get("enabled")
                    or not row.get("session_ciphertext")
                    or row.get("status") in RECOVERY_BLOCKED
                    or row.get("authorization_block") in RECOVERY_BLOCKED
                ):
                    if slot and (not slot.busy_job or row and row.get("status") in AUTH_BLOCKED) or account_id in self.retired:
                        await self.detach(account_id)
                    continue
                if max(row.get("cooldown_until") or now(), row.get("next_recovery_at") or now()) > now() or (slot and slot.busy_job):
                    continue  # Do not probe busy calls or bypass a Telegram wait.
                if account_id in self.retired or slot and slot.disconnected:
                    await self.detach(account_id)
                    slot = self.slots.get(account_id)
                if not slot:
                    await self.attach(account_id)
                    continue  # attach already validates identity; don't probe twice.
                try:
                    response = await self.rpc(slot, functions.users.GetUsersRequest([types.InputUserSelf()]))
                    if not response or not isinstance(response[0], types.User) or response[0].id != row["telegram_id"] or response[0].bot:
                        await self.set_status(account_id, "reauth_required", "SessionIdentityMismatch", slot=slot)
                        await self.detach(account_id)
                        continue
                    if response[0].deleted:
                        raise errors.UserDeactivatedError(None)
                    await self.set_status(account_id, "healthy", slot=slot)
                except errors.FloodWaitError:
                    pass
                except FATAL_AUTH as exc:
                    await self.set_status(account_id, auth_status(exc), type(exc).__name__, slot=slot)
                    await self.detach(account_id)
                except UserError:
                    pass
                except Exception as exc:
                    await self.set_status(account_id, "offline", type(exc).__name__, slot=slot)
                    await self.detach(account_id)

    async def scan_health(self, progress):
        """Manual scan shares lifecycle lock, but skips busy/cooldown accounts.

        Newly attached accounts are already identity-checked; do not probe twice.
        No OTP/password/session plaintext is returned in the report.
        """
        rows = await self.store.db.accounts.find({}).sort("created_at", 1).limit(POOL_ACCOUNT_CEILING).to_list(length=POOL_ACCOUNT_CEILING)
        for snapshot in rows:
            async with self.sync_lock:
                row = await self.store.db.accounts.find_one({"_id": snapshot["_id"]}) or {
                    "_id": snapshot["_id"],
                    "enabled": False,
                    "status": "removed",
                }
                key, check = row["_id"], "checked"
                identity_verified, did_attach = False, False
                slot = self.slots.get(key)
                if self.safety.blocked():
                    check = "paused: session/runtime safety review"
                elif not row.get("enabled"):
                    check = "skipped: disabled"
                    if slot and not slot.busy_job:
                        await self.detach(key)
                elif row.get("status") in RECOVERY_BLOCKED or row.get("authorization_block") in RECOVERY_BLOCKED:
                    check = "authorization blocked; saved data retained"
                elif max(row.get("cooldown_until") or now(), row.get("next_recovery_at") or now()) > now():
                    check = "skipped: cooldown"
                elif slot and slot.busy_job:
                    check = "skipped: busy"
                elif key in self.retired or slot and slot.disconnected:
                    check = "transport reloaded"
                    await self.detach(key)
                    await self.attach(key)
                    did_attach = True
                elif not slot:
                    if row.get("session_ciphertext"):
                        await self.attach(key)
                        did_attach = True
                    else:
                        check = "skipped: sign-in needed"
                else:
                    try:
                        response = await self.rpc(slot, functions.users.GetUsersRequest([types.InputUserSelf()]))
                        if (
                            not response
                            or not isinstance(response[0], types.User)
                            or response[0].id != row["telegram_id"]
                            or response[0].bot
                        ):
                            raise SessionIdentityMismatch("Stored session identity mismatch.")
                        if response[0].deleted:
                            raise errors.UserDeactivatedError(None)
                        identity_verified = bool(await self.set_status(key, "healthy", slot=slot))
                    except errors.FloodWaitError:
                        check = "Telegram cooldown"
                    except FATAL_AUTH as exc:
                        await self.set_status(key, auth_status(exc), type(exc).__name__, slot=slot)
                        await self.detach(key)
                    except SessionIdentityMismatch:
                        await self.set_status(key, "reauth_required", "SessionIdentityMismatch", slot=slot)
                        await self.detach(key)
                    except UserError:
                        fresh = await self.store.db.accounts.find_one({"_id": key}) or {}
                        if (fresh.get("cooldown_until") or now()) > now():
                            check = "skipped: cooldown"
                        elif not fresh.get("enabled"):
                            check = "skipped: disabled/removed"
                        elif fresh.get("status") in RECOVERY_BLOCKED:
                            check = "authorization blocked; saved data retained"
                        elif (
                            slot.disconnected
                            or slot.closing
                            or slot.connection_epoch
                            and fresh.get("connection_epoch") != slot.connection_epoch
                        ):
                            check = "connection changed; automatic recovery"
                            await self.set_status(key, "offline", "TelegramDisconnected", slot=slot)
                            await self.detach(key)
                        else:
                            check = "skipped: authority/state changed"
                        # An authored control/network error is NOT evidence that
                        # Telegram revoked the saved authorization.
                    except Exception as exc:
                        await self.set_status(key, "offline", type(exc).__name__, slot=slot)
                        await self.detach(key)
                latest = await self.store.db.accounts.find_one({"_id": key}) or {}
                current = self.slots.get(key)
                if did_attach and current and current is not slot and current.connection_epoch:
                    identity_verified = current.validated_fingerprint is not None and current.connection_epoch == latest.get(
                        "connection_epoch"
                    )
                identity_verified = bool(
                    identity_verified and current and not current.closing and not current.disconnected and latest.get("status") == "healthy"
                )
            await progress(
                {
                    "account_id": key,
                    "status": latest.get("status", "removed"),
                    "check": check,
                    "error_type": latest.get("last_error_type"),
                    "identity_verified": identity_verified,
                },
                len(rows),
            )

    async def rpc(self, slot: Slot, request, before=None):
        self.safety.require_allowed()
        async with slot.lock:
            if slot.closing or slot.disconnected:
                raise UserError("Account connection needs a health reload.")
            row = await self.store.db.accounts.find_one({"_id": slot.account_id})
            if not row or not row.get("enabled"):
                raise UserError("Account is disabled or removed.")
            if row.get("status") in AUTH_BLOCKED or slot.connection_epoch and row.get("connection_epoch") != slot.connection_epoch:
                raise UserError("Saved authorization changed or is blocked; the old connection cannot be used.")
            if row.get("cooldown_until", now()) > now():
                raise UserError("Account is in Telegram FloodWait cooldown.")
            await self.gate.wait()
            if before:
                await before()
            # Ownership/waits can change while global pacing or entitlement
            # checks yield. Never send a queued RPC from the old authorization.
            if slot.closing or slot.disconnected or self.slots.get(slot.account_id) is not slot:
                raise UserError("Account connection changed while queued; no Telegram request was sent.")
            current = await self.store.db.accounts.find_one({"_id": slot.account_id})
            if not current or not current.get("enabled") or current.get("status") in AUTH_BLOCKED:
                raise UserError("Account was disabled, removed or authorization-blocked while queued.")
            if slot.connection_epoch and current.get("connection_epoch") != slot.connection_epoch:
                raise UserError("Saved authorization changed while queued; the old connection cannot be used.")
            if (current.get("cooldown_until") or now()) > now():
                raise UserError("Account entered Telegram cooldown while queued.")
            try:
                result = await asyncio.wait_for(slot.client(request), 30)
                self.schedule_checkpoint(slot.client)
                return result
            except errors.FloodWaitError as exc:
                await self.cooldown(slot.account_id, exc.seconds, slot=slot)
                raise

    async def available(self):
        if self.safety.blocked():
            return []
        rows = await self.store.db.accounts.find(
            {"enabled": True, "status": "healthy", "$or": [{"cooldown_until": {"$lte": now()}}, {"cooldown_until": {"$exists": False}}]}
        ).to_list(length=None)
        return [
            r
            for r in rows
            if r["_id"] in self.slots
            and not self.slots[r["_id"]].busy_job
            and not self.slots[r["_id"]].closing
            and not self.slots[r["_id"]].disconnected
        ]

    async def reserve(self, job_id, count, exclude=None):
        async with self.lock:
            rows = sorted(
                [r for r in await self.available() if r["_id"] not in (exclude or set())],
                key=lambda r: r.get("last_used_at", r["created_at"]),
            )
            # Do not quietly reduce the number purchased/requested: wait for full capacity.
            if len(rows) < count:
                return []
            selected = [self.slots[row["_id"]] for row in rows[:count]]
            account_ids = [slot.account_id for slot in selected]
            for slot in selected:
                slot.busy_job = job_id
            try:
                await self.store.db.accounts.update_many(
                    {"_id": {"$in": account_ids}}, {"$set": {"busy_job": job_id, "last_used_at": now()}}
                )
            except Exception:
                # No Telegram action has started. Clear every RAM reservation even
                # when Mongo acknowledged only part of the bulk write (or none).
                for slot in selected:
                    slot.busy_job = None
                with suppress(Exception):
                    await self.store.db.accounts.update_many(
                        {"_id": {"$in": account_ids}, "busy_job": job_id}, {"$unset": {"busy_job": ""}}
                    )
                raise
            return selected

    async def release(self, slots, job_id):
        async with self.lock:
            account_ids = []
            for slot in slots:
                if slot.busy_job == job_id:
                    slot.busy_job = None
                    account_ids.append(slot.account_id)
            if account_ids:
                # Clear all RAM slots before persistence: a failed metadata write
                # must not strand unrelated accounts as busy until restart.
                await self.store.db.accounts.update_many({"_id": {"$in": account_ids}, "busy_job": job_id}, {"$unset": {"busy_job": ""}})

    async def join_target(self, slot: Slot, link: TelegramLink, expected_chat_id: int, before=None):
        # Detection membership and manual work may overlap on one live identity.
        # Serialize the complete cap/day/gap mutation, not only the final RPC.
        async with slot.join_lock:
            return await self._join_target(slot, link, expected_chat_id, before)

    async def _join_target(self, slot, link, expected_chat_id, before):
        row = await self.store.db.accounts.find_one({"_id": slot.account_id})
        if not row or not row.get("enabled"):
            raise UserError("Account is disabled or removed.")
        if row.get("status") in AUTH_BLOCKED:
            raise UserError("This account needs sign-in again before joining.")
        if row.get("cooldown_until", now()) > now():
            raise UserError("Account is in Telegram FloodWait cooldown.")
        today = now().date().isoformat()
        if row.get("join_day") == today and row.get("join_count", 0) >= self.config.limits.account_joins_per_day:
            raise UserError("Account daily join safety cap reached.")
        last_join = row.get("last_join_at")
        if last_join:
            # Larger base gap + bigger random extra for safer, less detectable pacing.
            base = self.config.limits.account_join_gap_seconds
            extra = random.uniform(8.0, 35.0)
            delay = (base + extra) - (now() - last_join).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
        if before:
            await before()
        # A gap/authorization check may cross UTC midnight or a health change.
        # Re-read immediately before mutating the safety counter.
        row = await self.store.db.accounts.find_one({"_id": slot.account_id})
        if not row or not row.get("enabled") or row.get("status") in AUTH_BLOCKED:
            raise UserError("Account access changed; check health or sign in again.")
        if row.get("cooldown_until", now()) > now():
            raise UserError("Account is in Telegram FloodWait cooldown.")
        today = now().date().isoformat()
        if row.get("join_day") == today and row.get("join_count", 0) >= self.config.limits.account_joins_per_day:
            raise UserError("Account daily join safety cap reached.")
        # An attempted join counts too, so rejected links cannot bypass safety caps.
        if row.get("join_day") != today:
            await self.store.db.accounts.update_one({"_id": slot.account_id}, {"$set": {"join_day": today, "join_count": 0}})
        await self.store.db.accounts.update_one({"_id": slot.account_id}, {"$set": {"last_join_at": now()}, "$inc": {"join_count": 1}})
        try:
            if link.kind == "public":
                await self.gate.wait()
                if before:
                    await before()
                entity = await asyncio.wait_for(slot.client.get_entity("@" + link.value), 30)
                if utils.get_peer_id(entity) != expected_chat_id:
                    raise UserError("Target identity changed; refusing to join.")
                await self.rpc(slot, functions.channels.JoinChannelRequest(entity), before=before)
            else:
                checked = await self.rpc(slot, functions.messages.CheckChatInviteRequest(link.value), before=before)
                if isinstance(checked, types.ChatInviteAlready):
                    if utils.get_peer_id(checked.chat) != expected_chat_id:
                        raise UserError("Invite target identity mismatch.")
                    return "already_member"
                updates = await self.rpc(slot, functions.messages.ImportChatInviteRequest(link.value), before=before)
                chats = getattr(updates, "chats", [])
                if chats and not any(utils.get_peer_id(chat) == expected_chat_id for chat in chats):
                    raise UserError("Telegram returned an unexpected target.")
            return "joined"
        except errors.UserAlreadyParticipantError:
            return "already_member"
        except errors.InviteRequestSentError:
            return "request_sent"  # Successful join request, NOT an accepted membership.
        except errors.FloodWaitError as exc:
            await self.cooldown(slot.account_id, exc.seconds, slot=slot)
            raise

    async def ensure_member(self, slot, link, chat_id, before=None):
        # A positive membership result is cached only in this live session.
        # Do not burn another channel-join attempt on every auto polling pass.
        if chat_id in slot.forbidden_chats:
            raise UserError("Account was removed by a moderator; automatic retry is disabled.")
        if before:
            await before()
        if chat_id in slot.member_chats:
            return "already_member"
        result = await self.join_target(slot, link, chat_id, before=before)
        if result in {"joined", "already_member"}:
            slot.member_chats.add(chat_id)
        return result

    async def get_call(self, slot, chat_id):
        await self.gate.wait()
        entity = await slot.client.get_input_entity(chat_id)
        if isinstance(entity, types.InputPeerChannel):
            full = await self.rpc(slot, functions.channels.GetFullChannelRequest(entity))
        else:
            full = await self.rpc(slot, functions.messages.GetFullChatRequest(entity.chat_id))
        return getattr(full.full_chat, "call", None)

    async def calls(self, slot):
        if slot.closing or slot.disconnected:
            raise UserError("Account connection needs a health reload.")
        if not self.config.calls_enabled:
            raise UserError("Calls are disabled by this deployment.")
        if slot.call_client is None:
            from pytgcalls import PyTgCalls
            from pytgcalls.types import ChatUpdate, UpdatedGroupCallParticipant, GroupCallParticipant

            previous_handlers = handlers_snapshot(slot.client)
            app = PyTgCalls(slot.client, workers=1, cache_duration=30)
            if hasattr(app, "_binding"):
                slot.native_owner = NativeLifecycle(app, slot.client, previous_handlers, slot.account_id)

            @app.on_update()
            async def on_update(_, update):
                if isinstance(update, ChatUpdate):
                    if update.status & (ChatUpdate.Status.KICKED | ChatUpdate.Status.LEFT_GROUP):
                        slot.forbidden_chats.add(update.chat_id)
                        slot.member_chats.discard(update.chat_id)
                    if update.status & ChatUpdate.Status.CLOSED_VOICE_CHAT:
                        slot.closed_chats.add(update.chat_id)
                elif isinstance(update, UpdatedGroupCallParticipant):
                    if (
                        update.participant.user_id == int(slot.account_id)
                        and update.action in (GroupCallParticipant.Action.KICKED, GroupCallParticipant.Action.LEFT)
                        and update.chat_id not in slot.leaving_chats
                    ):
                        # Telegram may not explain why a participant left. Fail closed
                        # rather than interpreting a moderator removal as a network drop.
                        slot.forbidden_chats.add(update.chat_id)

            slot.call_client = app  # Cleanup must own even a partially started adapter.
            try:
                await asyncio.wait_for(app.start(), 30)
            except BaseException:
                await self.retire_call_transport(slot, "CallAdapterStartupUncertain")
                raise
        return slot.call_client

    async def assert_call_allowed(self, slot, chat_id):
        self.safety.require_allowed()
        row = await self.store.db.accounts.find_one({"_id": slot.account_id})
        if not row or not row.get("enabled"):
            raise UserError("Account is disabled or removed.")
        if slot.closing or slot.disconnected or self.slots.get(slot.account_id) is not slot:
            raise UserError("Account connection changed; native call setup was stopped.")
        if row.get("status") in AUTH_BLOCKED or row.get("authorization_block"):
            raise UserError("Saved authorization is blocked; native call setup was stopped.")
        if slot.connection_epoch and row.get("connection_epoch") != slot.connection_epoch:
            raise UserError("Saved authorization changed; the old native transport cannot be used.")
        if slot.session_generation and row.get("session_generation") != slot.session_generation:
            raise UserError("Saved authorization changed; the old native transport cannot be used.")
        if (row.get("cooldown_until") or now()) > now():
            raise UserError("Account is in Telegram FloodWait cooldown.")
        if chat_id in slot.forbidden_chats:
            raise UserError("Account was removed by a group/call moderator; rejoin is disabled.")

    async def join_call(self, slot, chat_id, invite_hash=None, before=None):
        from pytgcalls.types import GroupCallConfig

        await self.assert_call_allowed(slot, chat_id)
        app = await self.calls(slot)
        slot.leaving_chats.discard(chat_id)
        slot.closed_chats.discard(chat_id)
        await self.gate.wait()
        if before:
            await before()
        await self.assert_call_allowed(slot, chat_id)  # Pacing/callbacks can yield to disable, replacement or moderation.
        try:
            # No camera/mic publishing, no recording, and NEVER auto-create a call.
            slot.joining_chats.add(chat_id)
            await asyncio.wait_for(app.play(chat_id, None, GroupCallConfig(invite_hash=invite_hash, auto_start=False)), 45)
            await self.assert_call_allowed(slot, chat_id)  # A late native success cannot retain newly denied access.
            slot.joining_chats.discard(chat_id)
        except errors.FloodWaitError as exc:
            await self.cooldown(slot.account_id, exc.seconds, slot=slot)
            raise

    async def can_rejoin(self, slot, input_call):
        # Missing remote update must not be mistaken for transport loss.
        # Retry only while Telegram still lists this account in the SAME call.
        response = await self.rpc(
            slot, functions.phone.GetGroupParticipantsRequest(call=input_call, ids=[types.InputPeerSelf()], sources=[], offset="", limit=1)
        )
        return any(
            utils.get_peer_id(participant.peer) == int(slot.account_id) and not participant.left for participant in response.participants
        )

    async def in_call(self, slot, chat_id):
        return bool(slot.call_client and chat_id in await slot.call_client.calls)

    async def remote_cleanup_allowed(self, slot):
        if self.safety.blocked():
            return False
        connected = getattr(slot.client, "is_connected", None)
        if slot.disconnected or callable(connected) and not inspect.iscoroutinefunction(connected) and not connected():
            slot.disconnected = True
            return False  # Never invoke native MTProto leave after transport loss.
        try:
            row = await self.store.db.accounts.find_one({"_id": slot.account_id})
        except Exception:
            return False  # Unknown authority/wait state: local cleanup only.
        if not row or not row.get("enabled") or row.get("status") in AUTH_BLOCKED:
            return False
        if slot.connection_epoch and row.get("connection_epoch") != slot.connection_epoch:
            return False
        if slot.session_generation and row.get("session_generation") != slot.session_generation:
            return False
        return (row.get("cooldown_until") or now()) <= now()

    async def leave_call(self, slot, chat_id):
        slot.leaving_chats.add(chat_id)
        if slot.call_client:
            try:
                await asyncio.wait_for(slot.call_client.leave_call(chat_id), 15)
            except Exception as exc:
                from pytgcalls.exceptions import NotInCallError, NoActiveGroupCall, MTProtoClientNotConnected

                if isinstance(exc, (NotInCallError, NoActiveGroupCall)) and chat_id not in slot.joining_chats:
                    try:
                        if not await asyncio.wait_for(self.in_call(slot, chat_id), 5):
                            logger.debug("Call already absent; saved Telegram authorization unchanged; account=%s", slot.account_id)
                            return True
                    except Exception:
                        pass  # An uncertain cache is not proof of a clean leave.
                if isinstance(exc, errors.FloodWaitError):
                    await self.cooldown(slot.account_id, exc.seconds, slot=slot)
                elif isinstance(exc, FATAL_AUTH):
                    await self.set_status(slot.account_id, auth_status(exc), type(exc).__name__, slot=slot)
                if isinstance(exc, MTProtoClientNotConnected):
                    slot.disconnected = True
                    logger.info("Call transport offline; local cleanup required; account=%s error=%s", slot.account_id, type(exc).__name__)
                else:
                    logger.warning("Call leave failed; account=%s error=%s", slot.account_id, type(exc).__name__)
                return False
        return True

    async def safe_leave_call(self, slot, chat_id):
        if slot.call_client and not await self.remote_cleanup_allowed(slot):
            # No MTProto leave request during FloodWait, auth stop, removal or
            # uncertain DB ownership. Owned local native stop is still allowed.
            await self.retire_call_transport(slot, "CallCleanupOffline" if slot.disconnected else "CallCleanupCooldown")
            return
        left = await self.leave_call(slot, chat_id)
        try:
            remains = await asyncio.wait_for(self.in_call(slot, chat_id), 5)
        except Exception:
            remains = True  # An uncertain native transport must not be reused.
        if left is False or remains or chat_id in slot.joining_chats:
            await self.retire_call_transport(slot, "CallCleanupUncertain")

    async def retire_call_transport(self, slot, error_type):
        # Retire an uncertain local transport before this identity can be reused.
        # The encrypted session/key are preserved; normal health reload can attach
        # a fresh client only after the persisted offline cooldown.
        async with self.sync_lock:
            if self.slots.get(slot.account_id) is slot:
                await self.set_status(slot.account_id, "offline", error_type, slot=slot)
                await self.detach(slot.account_id)

    async def detach_current(self, slot):
        async with self.sync_lock:
            if self.slots.get(slot.account_id) is slot or self.retired.get(slot.account_id) is slot:
                await self.detach(slot.account_id)

    async def detach(self, account_id):
        task = self.cleanup_tasks.get(account_id)
        if task is None:
            slot = self.slots.pop(account_id, None) or self.retired.get(account_id)
            if not slot:
                return
            slot.closing = True
            self.account_guards.setdefault(account_id, set()).update(slot.forbidden_chats)
            self.retired[account_id] = slot
            task = asyncio.create_task(self.detach_slot(slot), name="transport-cleanup")
            self.cleanup_tasks[account_id] = task

            def done(task):
                self.cleanup_tasks.pop(account_id, None)
                if not task.cancelled():
                    error = task.exception()
                    if error:
                        logger.error("Owned transport cleanup failed; error=%s", type(error).__name__)

            task.add_done_callback(done)
        # A cancelled job/UI/health scan must not cancel the SDK disconnect and
        # orphan its network loops. Pool shutdown awaits these same owned tasks.
        await asyncio.shield(task)

    async def detach_slot(self, slot):
        account_id = slot.account_id
        okay = True
        checkpoint = self.checkpoint_tasks.get(id(slot.client))
        if checkpoint and checkpoint is not asyncio.current_task() and not checkpoint.done():
            checkpoint.cancel()
            await asyncio.gather(checkpoint, return_exceptions=True)
        try:
            if slot.call_client and await self.remote_cleanup_allowed(slot):
                try:
                    calls = await asyncio.wait_for(slot.call_client.calls, 5)
                    for chat_id in list(calls):
                        await self.leave_call(slot, chat_id)
                except Exception:
                    logger.exception("Call leave cleanup failed; account=%s", account_id)
            if slot.native_owner:
                slot.native_owner.quiesce()
                await slot.native_owner.drain()
                try:
                    okay = await slot.native_owner.stop_local()
                except Exception as exc:
                    okay = False
                    logger.warning("Native local cleanup failed; account=%s error=%s", account_id, type(exc).__name__)
        finally:
            try:
                okay = await self.disconnect_client(slot.client) and okay
                if slot.native_owner:
                    okay = await slot.native_owner.drain() and okay
                if slot.call_client:
                    await asyncio.to_thread(slot.call_client.executor.shutdown, wait=True, cancel_futures=True)
            except BaseException:
                okay = False
                raise
            finally:
                if okay and not (slot.native_owner and slot.native_owner.tasks):
                    self.retired.pop(account_id, None)
                    self.retired_retry_at.pop(account_id, None)
                else:
                    self.retired_retry_at[account_id] = time.monotonic() + 60
                    # Keep strong ownership and refuse replacement attachment of an
                    # identity whose previous local cleanup has not been proved.
                    self.retired[account_id] = slot
                    await self.set_status(account_id, "offline", "TransportCleanupPending", slot=slot)

    async def toggle(self, actor, account_id, enabled):
        async with self.sync_lock:
            async with self.lock:
                row = await self.store.db.accounts.find_one({"_id": account_id})
                if not row:
                    raise UserError("Account not found.")
                await self.access.can_manage_account(actor, row)
                if account_id in self.slots and self.slots[account_id].busy_job:
                    raise UserError("Account is busy. Cancel its active job first.")
                if enabled and (row.get("status") in RECOVERY_BLOCKED or row.get("authorization_block") in RECOVERY_BLOCKED):
                    raise UserError(recovery_hint(row))
                status = row.get("authorization_block") or (
                    row.get("status") if row.get("status") in AUTH_BLOCKED else "offline" if enabled else "disabled"
                )
                await self.store.db.accounts.update_one(
                    {"_id": account_id, **session_guard(row)},
                    {"$set": {"enabled": enabled, "status": status}, "$inc": {"account_revision": 1}},
                )
            if enabled:
                await self.attach(account_id)
                self.recovery_wake.set()
            else:
                await self.detach(account_id)
        await self.store.audit(actor, "account_enabled" if enabled else "account_disabled", account_id=account_id)

    async def remove(self, actor, account_id, logout=False):
        async with self.sync_lock:
            async with self.lock:
                row = await self.store.db.accounts.find_one({"_id": account_id})
                if not row:
                    raise UserError("Account not found.")
                await self.access.can_manage_account(actor, row)
                if account_id in self.slots and self.slots[account_id].busy_job:
                    raise UserError("Account is busy; cancel its job before removing it.")
                slot = self.slots.get(account_id)
                if logout and not slot:
                    raise UserError(
                        "No connected session is available to revoke. Use Telegram Settings → Devices, or choose local removal."
                    )
                await self.store.db.accounts.update_one(
                    {"_id": account_id, **session_guard(row)},
                    {"$set": {"enabled": False, "status": "disabled"}, "$inc": {"account_revision": 1}},
                )
            if logout and slot:
                try:
                    await self.gate.wait()
                    await asyncio.wait_for(slot.client.log_out(), 20)
                except Exception as exc:
                    raise UserError(
                        f"Account disabled for safety; session revocation failed ({type(exc).__name__}). Use Telegram Settings → Devices or choose local removal."
                    ) from None
            await self.detach(account_id)
            result = await self.store.db.accounts.delete_one({"_id": account_id, **session_guard(row)})
            if not result.deleted_count:
                raise UserError("Saved authorization changed during removal; newer saved data was not deleted. Refresh the account panel.")
            self.account_guards.pop(account_id, None)
        await self.store.audit(actor, "account_removed", account_id=account_id, logout_requested=logout)

    async def close(self):
        # One broken transport must not stop cleanup of other saved accounts.
        self.stopping = True
        self.recovery_wake.set()
        connecting = {task for task in self.attaching.values() if task is not asyncio.current_task()}
        for task in connecting:
            task.cancel()
        if connecting:
            await asyncio.gather(*connecting, return_exceptions=True)
        keys = set(self.slots) | set(self.retired)
        results = await asyncio.gather(*(self.detach(account_id) for account_id in keys), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Account shutdown cleanup failed; error=%s", type(result).__name__)
        if self.connection_tasks:
            await asyncio.wait(list(self.connection_tasks), timeout=20)
        for task in list(self.connection_tasks):
            task.cancel()
        await asyncio.gather(*list(self.connection_tasks), return_exceptions=True)
        for client in list(self.client_registry.values()):
            with suppress(Exception):
                await self.disconnect_client(client)
        if self.safety.cleanup_task and not self.safety.cleanup_task.done():
            await asyncio.gather(self.safety.cleanup_task, return_exceptions=True)
        if self.disconnects:
            await asyncio.wait([item[1] for item in self.disconnects.values()], timeout=15)
        if self.retired:
            logger.error("Shutdown has quarantined transports; count=%s", len(self.retired))
