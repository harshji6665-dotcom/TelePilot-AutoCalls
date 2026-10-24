"""Fleet-wide fail-closed protection for confirmed duplicated authorization.

This is operational containment, not recovery of an invalidated Telegram key.
It does not erase credentials, reauthenticate, rotate IPs or inspect key bytes.
"""

import asyncio
from contextlib import suppress
import secrets

from .security import UserError
from .timeutils import now

SAFETY_SETTING = "session_safety"
DUPLICATE_QUERY = {"$or": [{"authorization_error_type": "AuthKeyDuplicatedError"}, {"last_error_type": "AuthKeyDuplicatedError"}]}
PAUSE_MESSAGE = "Session safety stop: Telegram rejected a duplicated authorization. Stop every other worker/session copy and review deployments before the owner resumes. Invalidated keys need authorized sign-in afterward; no saved data was deleted."


class SessionSafety:
    def __init__(self, pool):
        self.pool, self.store = pool, pool.store
        self.paused = False
        self.epoch = None
        self.reason = None
        self.lock = asyncio.Lock()
        self.cleanup_task = None
        self.on_pause = None

    def blocked(self):
        return self.paused or bool(self.store and getattr(self.store, "lease_fence_enabled", False) and not self.store.lease_valid())

    def require_allowed(self):
        if self.paused:
            raise UserError(PAUSE_MESSAGE)
        if self.store and getattr(self.store, "lease_fence_enabled", False) and not self.store.lease_valid():
            raise UserError("Runtime ownership is not current. Account work is stopped before another session can be used.")

    def check_wire(self):
        # Synchronous check immediately before actual socket writes, including
        # packets queued before expiry and SDK-internal reconnect traffic.
        if self.blocked():
            raise ConnectionError("Telegram account transport fenced by runtime/session safety")

    def freeze(self, reason="duplicate_authorization"):
        self.paused, self.reason, self.epoch = True, reason, secrets.token_hex(12)
        for slot in list(self.pool.slots.values()):
            slot.disconnected = True
            if slot.native_owner:
                with suppress(Exception):
                    slot.native_owner.quiesce()
        for client in list(self.pool.client_registry.values()):
            owner = getattr(client, "_telepilot_transport", None)
            if owner:
                with suppress(Exception):
                    owner.quiesce()
        self.pool.recovery_wake.set()

    async def initialize(self):
        state = await self.store.setting(SAFETY_SETTING, {})
        if state.get("paused"):
            self.paused, self.epoch, self.reason = True, state.get("epoch"), "duplicate_authorization"
            return
        # Old releases already store the confirmed error. An explicit reviewed
        # acknowledgement is necessary once; never silently retry those keys.
        duplicate = await self.store.db.accounts.find_one(DUPLICATE_QUERY, {"_id": 0, "last_health_at": 1}, sort=[("last_health_at", -1)])
        reviewed = state.get("reviewed_at")
        latest = duplicate.get("last_health_at") if duplicate else None
        if duplicate is not None and (not reviewed or latest and latest > reviewed):
            # Also recover a crash between the per-account auth-stop write and
            # the separate fleet-pause write; an old acknowledgement is not a
            # licence to ignore a NEW confirmed duplicate event.
            self.freeze("existing_duplicate_authorizations")
            await self.persist()

    async def persist(self):
        try:
            async with self.lock:
                if not self.paused:
                    return
                await self.store.set_setting(
                    SAFETY_SETTING, {"paused": True, "epoch": self.epoch, "reason": "duplicate_authorization", "paused_at": now()}
                )
        finally:
            self.schedule_cleanup()
        await self.pool.notifier.owners(
            "<b>session safety stop</b>\n<blockquote>Telegram reported a duplicated authorization. All account traffic is paused before more saved keys are used. Stop other copies and review /sessionguard before new sign-ins. Invalidated keys need new authorized login; original encrypted records/key/database were not deleted.</blockquote>",
            "session-safety:" + self.epoch,
        )

    def schedule_cleanup(self):
        if self.cleanup_task and not self.cleanup_task.done():
            return
        self.cleanup_task = asyncio.create_task(self.quarantine(), name="session-safety-cleanup")
        self.cleanup_task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)

    async def quarantine(self):
        # Do not run while a status-write caller still holds the lifecycle lock.
        async with self.pool.sync_lock:
            connecting = {task for tasks in self.pool.client_connect_tasks.values() for task in tasks if task is not asyncio.current_task()}
            for task in connecting:
                task.cancel()
            if connecting:
                await asyncio.gather(*connecting, return_exceptions=True)
            for key in list(set(self.pool.slots) | set(self.pool.retired)):
                await self.pool.detach(key)  # remote cleanup is blocked while paused
            for client in list(self.pool.client_registry.values()):
                await self.pool.disconnect_client(client)
        if self.on_pause:
            await self.on_pause()

    async def resume(self, actor, epoch):
        await self.pool.access.require_staff(actor, owner_only=True)
        async with self.lock:
            state = await self.store.setting(SAFETY_SETTING, {})
            if not self.paused or not epoch or state.get("epoch") != epoch or self.epoch != epoch:
                raise UserError("Safety state changed. Refresh and review the current incident.")
            if (
                self.pool.slots
                or self.pool.retired
                or self.pool.client_registry
                or self.pool.cleanup_tasks
                or self.pool.connection_tasks
                or any(not task.done() for task in self.pool.attaching.values())
            ):
                raise UserError("Local transport cleanup is not confirmed. Keep safety paused and wait for owned cleanup.")
            if self.cleanup_task and not self.cleanup_task.done():
                raise UserError("Safety cleanup is still running. Refresh after it finishes.")
            if getattr(self.store, "lease_fence_enabled", False) and not self.store.lease_valid():
                raise UserError("Current singleton ownership is not confirmed. Resume is blocked.")
            # Audit BEFORE allowing traffic. Lost acknowledgements fail closed.
            await self.store.audit(actor, "session_safety_resume_authorized", reviewed_single_runtime=True, incident=epoch)
            result = await self.store.db.settings.update_one(
                {"_id": SAFETY_SETTING, "value.paused": True, "value.epoch": epoch},
                {"$set": {"value.paused": False, "value.reviewed_at": now(), "value.reviewed_by": actor}},
            )
            if not result.matched_count:
                raise UserError("A newer safety incident arrived. Nothing was resumed; refresh and review it.")
            if self.epoch != epoch:
                await self.store.set_setting(
                    SAFETY_SETTING, {"paused": True, "epoch": self.epoch, "reason": "duplicate_authorization", "paused_at": now()}
                )
                raise UserError("A newer safety incident arrived during confirmation. Nothing was resumed.")
            self.paused = False
            self.reason = None
        self.pool.recovery_wake.set()
        # Deliberately no clearing of per-account revoked/banned/auth flags.
