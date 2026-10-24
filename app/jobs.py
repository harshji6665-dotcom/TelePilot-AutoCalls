from __future__ import annotations

import asyncio
from collections import Counter
from datetime import timedelta
import logging
import secrets
import random
from hashlib import sha256

from pymongo import ReturnDocument
from telethon import errors

from .plans import account_capacity_error, channel_capacity_error
from .accounts import FATAL_AUTH
from .session_state import auth_status
from .links import TelegramLink
from .security import UserError, Role
from .timeutils import now

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "partial", "failed", "cancelled"}
JOIN_SUCCESS = {"joined", "already_member", "request_sent"}


class JobEngine:
    def __init__(self, store, access, targets, pool, notifier, config):
        self.store, self.access, self.targets, self.pool, self.notifier, self.config = store, access, targets, pool, notifier, config
        self.active: dict[str, asyncio.Task] = {}
        self.create_lock = asyncio.Lock()
        self.recovery_lock = asyncio.Lock()
        self.recovered = False
        self.auto_wakeup = None
        self.stopping = False
        self.sleep = asyncio.sleep  # Injectable pacing clock for deterministic adapter tests.

    async def create(self, user_id, kind, target_id, link, count, run_at, minutes=None, request_key=None):
        # Share target registration/removal locks: a job cannot be inserted after
        # its target was removed between verification and persistence.
        async with self.targets.locks.get(user_id):
            return await self._create(user_id, kind, target_id, link, count, run_at, minutes, request_key)

    async def _create(self, user_id, kind, target_id, link, count, run_at, minutes, request_key):
        self.pool.safety.require_allowed()
        stable_id = sha256(f"{user_id}:{request_key}".encode()).hexdigest()[:24] if request_key else None
        if stable_id:
            previous = await self.store.db.jobs.find_one({"_id": stable_id, "user_id": user_id})
            if previous:
                return stable_id
        if await self.store.setting("maintenance", False):
            raise UserError("Maintenance mode is enabled. New jobs are paused.")
        if kind not in ("join", "call"):
            raise UserError("Invalid job type.")
        if kind == "call" and not self.config.calls_enabled:
            raise UserError("Call support is disabled on this host.")
        entitlement = await self.access.entitlement(user_id, at=run_at, kind=kind)
        if not 1 <= count <= min(entitlement["max_accounts"], self.config.limits.max_pool_accounts):
            raise account_capacity_error(entitlement)
        target = await self.targets.get(user_id, target_id, recheck=True)
        if await self.store.db.targets.count_documents({"user_id": user_id}) > entitlement["channel_limit"]:
            raise channel_capacity_error(entitlement, self.config)
        parsed = await self.targets.validate_link(target, link)
        if kind == "join":
            parsed = await self.targets.join_link(target)
        healthy = await self.store.db.accounts.count_documents({"enabled": True, "status": "healthy"})
        if count > healthy:
            raise UserError(f"Only {healthy} healthy signed-in accounts currently exist. Reduce account count.")
        if kind == "call" and not 5 <= (minutes or self.config.limits.max_call_minutes) <= self.config.limits.max_call_minutes:
            raise UserError(f"Call safety duration must be 5–{self.config.limits.max_call_minutes} minutes.")
        if run_at > now() + timedelta(days=90) or run_at < now() - timedelta(seconds=60):
            raise UserError("Invalid schedule. Choose now or a date up to 90 days ahead.")
        async with self.create_lock:
            if stable_id and await self.store.db.jobs.find_one({"_id": stable_id, "user_id": user_id}):
                return stable_id
            midnight = now().replace(hour=0, minute=0, second=0, microsecond=0)
            if (
                await self.store.db.jobs.count_documents({"user_id": user_id, "created_at": {"$gte": midnight}})
                >= self.config.limits.max_jobs_per_user_day
            ):
                raise UserError("Daily job safety limit reached (resets at UTC midnight).")
            if (
                await self.store.db.jobs.count_documents({"user_id": user_id, "status": {"$in": ["queued", "running"]}})
                >= self.config.limits.max_pending_jobs_per_user
            ):
                raise UserError("Too many active/queued jobs. Cancel or wait for an existing job.")
            job_id = stable_id or secrets.token_hex(6)
            await self.store.db.jobs.insert_one(
                {
                    "_id": job_id,
                    "user_id": user_id,
                    "kind": kind,
                    "target_id": target_id,
                    "chat_id": target["chat_id"],
                    "target_title": target["title"],
                    "link": {"kind": parsed.kind, "value": parsed.value, "invite_hash": parsed.invite_hash},
                    "join_policy": "public_direct_private_request" if kind == "join" else None,
                    "account_count": count,
                    "minutes": minutes or self.config.limits.max_call_minutes,
                    "run_at": run_at,
                    "original_run_at": run_at,
                    "start_deadline": run_at + timedelta(seconds=self.config.limits.max_start_delay_seconds),
                    "status": "queued",
                    "cancel_requested": False,
                    "created_at": now(),
                    "results": [],
                    "notification_pending": False,
                }
            )
            await self.store.audit(
                user_id, "job_created", job_id=job_id, kind=kind, chat_id=target["chat_id"], account_count=count, run_at=run_at
            )
        if self.auto_wakeup:
            self.auto_wakeup()
        return job_id

    async def cancel(self, actor, job_id):
        job = await self.store.db.jobs.find_one({"_id": job_id})
        if not job:
            raise UserError("Job not found.")
        if job["user_id"] != actor and await self.access.role(actor) == Role.USER:
            raise UserError("You can cancel only your own jobs.")
        if job["status"] in TERMINAL:
            raise UserError("This job has already ended.")
        await self.store.db.jobs.update_one({"_id": job_id}, {"$set": {"cancel_requested": True}})
        await self.store.audit(actor, "job_cancel_requested", job_id=job_id)

    async def allowed(self, job, recheck_target=False):
        self.pool.safety.require_allowed()
        row = await self.store.db.jobs.find_one({"_id": job["_id"]})
        if not row or row.get("cancel_requested"):
            raise UserError("Job cancelled.")
        entitlement = await self.access.entitlement(job["user_id"], kind=job["kind"])
        if job["account_count"] > entitlement["max_accounts"]:
            raise account_capacity_error(entitlement)
        if await self.store.db.targets.count_documents({"user_id": job["user_id"]}) > entitlement["channel_limit"]:
            raise channel_capacity_error(entitlement, self.config)
        if recheck_target:
            await self.targets.get(job["user_id"], job["target_id"], recheck=True)
        return entitlement

    async def finish(self, job_id, status, results=None, reason=None):
        fields = {"status": status, "finished_at": now(), "notification_pending": True, "purge_at": now() + timedelta(days=30)}
        if results is not None:
            for result in results:
                if result["status"] == "active":
                    result["status"] = "stopped"
            fields["results"] = results
        if reason:
            fields["reason"] = reason[:200]
        await self.store.db.jobs.update_one({"_id": job_id}, {"$set": fields, "$unset": {"worker": ""}})

    async def error_result(self, slot, exc):
        if isinstance(exc, errors.FloodWaitError):
            await self.pool.cooldown(slot.account_id, exc.seconds, slot=slot)
            return {"account_id": slot.account_id, "status": "cooldown", "error_type": type(exc).__name__, "wait_seconds": exc.seconds}
        if isinstance(exc, FATAL_AUTH):
            try:
                await self.pool.set_status(slot.account_id, auth_status(exc), type(exc).__name__, slot=slot)
            finally:
                await self.pool.detach_current(slot)
        elif isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            try:
                await self.pool.set_status(slot.account_id, "offline", type(exc).__name__, slot=slot)
            finally:
                await self.pool.detach_current(slot)
        result = {"account_id": slot.account_id, "status": "failed", "error_type": type(exc).__name__}
        if isinstance(exc, UserError):
            result["detail"] = str(exc)[:180]
        return result

    async def persist_results(self, job_id, results):
        await self.store.db.jobs.update_one({"_id": job_id}, {"$set": {"results": results, "heartbeat_at": now()}})

    async def process(self, job):
        slots, results = [], list(job.get("results", []))
        chat_id, job_id = job["chat_id"], job["_id"]
        try:
            await self.allowed(job, recheck_target=True)
            if job["kind"] == "join":
                target = await self.targets.get(job["user_id"], job["target_id"])
                resolved = await self.targets.join_link(target)
                job["link"] = {"kind": resolved.kind, "value": resolved.value, "invite_hash": resolved.invite_hash}
                await self.store.db.jobs.update_one(
                    {"_id": job_id}, {"$set": {"link": job["link"], "join_policy": "public_direct_private_request"}}
                )
            completed_ids = {r["account_id"] for r in results if r["status"] in JOIN_SUCCESS} if job["kind"] == "join" else set()
            count = job["account_count"] - len(completed_ids)
            if count <= 0:
                await self.finish(job_id, "completed", results)
                return
            if job.get("end_at") and job["end_at"] <= now() and job["kind"] == "call":
                await self.finish(job_id, "completed", results, "Original call safety deadline elapsed during restart.")
                return
            if now() >= job["start_deadline"] and not job.get("expected_call_id"):
                raise UserError("Job start deadline elapsed; no late joins were performed.")
            slots = await self.pool.reserve(job_id, count, exclude=completed_ids)
            if not slots:
                if now() >= job["start_deadline"]:
                    await self.finish(job_id, "failed", results, "Not enough healthy, free accounts before the start deadline.")
                else:
                    await self.store.db.jobs.update_one(
                        {"_id": job_id}, {"$set": {"status": "queued", "run_at": now() + timedelta(seconds=15)}, "$unset": {"worker": ""}}
                    )
                return
            link = TelegramLink(**job["link"])
            if job["kind"] == "join":
                for slot in slots:
                    await self.allowed(job)
                    try:
                        status = await self.pool.join_target(slot, link, chat_id, before=lambda: self.allowed(job, recheck_target=True))
                        results.append({"account_id": slot.account_id, "status": status, "at": now()})
                    except Exception as exc:
                        results.append(await self.error_result(slot, exc))
                    await self.persist_results(job_id, results)
                successes = sum(r["status"] in JOIN_SUCCESS for r in results)
                status = "completed" if successes == job["account_count"] else "partial" if successes else "failed"
                await self.finish(job_id, status, results)
            else:
                # A restart may reconnect different healthy accounts, never reset the original call/end deadline.
                results = []
                await self.run_call(job, slots, link, results)
        except asyncio.CancelledError:
            await self.store.db.jobs.update_one(
                {"_id": job_id, "status": "running"}, {"$set": {"status": "queued", "run_at": now()}, "$unset": {"worker": ""}}
            )
            raise
        except UserError as exc:
            current = await self.store.db.jobs.find_one({"_id": job_id})
            cancelled = (current or {}).get("cancel_requested", False)
            await self.finish(job_id, "cancelled" if cancelled else "failed", results, str(exc))
        except Exception as exc:
            logger.exception("Job worker failed; job=%s", job_id)
            await self.finish(job_id, "failed", results, type(exc).__name__)
        finally:
            if job["kind"] == "call":
                # Independent accounts leave concurrently; shutdown should not
                # multiply the per-client timeout by the requested account count.
                await asyncio.gather(*(self.pool.safe_leave_call(slot, chat_id) for slot in slots), return_exceptions=True)
            await self.pool.release(slots, job_id)

    async def run_call(self, job, slots, link, results):
        job_id, chat_id = job["_id"], job["chat_id"]
        if job.get("end_at") and job["end_at"] <= now():
            await self.finish(job_id, "completed", job.get("results", []), "Original call safety deadline elapsed during restart.")
            return
        ready = []
        for i, slot in enumerate(slots):
            await self.allowed(job)
            if i > 0:
                # Larger stagger between accounts to reduce simultaneous load and look less automated.
                await asyncio.sleep(random.uniform(6.0, 18.0))
            try:
                membership = await self.pool.join_target(slot, link, chat_id, before=lambda: self.allowed(job, recheck_target=True))
                if membership == "request_sent":
                    results.append({"account_id": slot.account_id, "status": "awaiting_approval"})
                else:
                    ready.append(slot)
            except Exception as exc:
                results.append(await self.error_result(slot, exc))
            await self.persist_results(job_id, results)
        if not ready:
            await self.finish(
                job_id, "failed", results, "Accounts could not access this group. Pending join requests need approval by its admins."
            )
            return
        call = None
        grace_until = min(job["start_deadline"], now() + timedelta(seconds=self.config.limits.call_start_grace_seconds))
        while not call:
            await self.allowed(job)
            call = await self.pool.get_call(ready[0], chat_id)
            if call:
                break
            if now() >= grace_until:
                raise UserError("No active group/channel voice-video chat before the start grace deadline.")
            await self.sleep(self.config.limits.call_poll_seconds)
        expected = job.get("expected_call_id") or call.id
        if expected != call.id:
            raise UserError("Original call ended/changed. A different call will NOT be joined automatically.")
        entitlement = await self.allowed(job)
        end_at = job.get("end_at") or now() + timedelta(minutes=job["minutes"])
        if entitlement.get("expires_at"):
            end_at = min(end_at, entitlement["expires_at"])
        await self.store.db.jobs.update_one({"_id": job_id}, {"$set": {"expected_call_id": expected, "end_at": end_at}})
        joined = []
        result_by_id = {}
        ever_joined = 0
        for i, slot in enumerate(ready):
            await self.allowed(job)
            if now() >= end_at:
                results.append({"account_id": slot.account_id, "status": "duration_elapsed"})
                continue
            # Larger stagger so multiple accounts do not join the same call almost together.
            if i > 0:
                await asyncio.sleep(random.uniform(5.0, 16.0))
            try:
                await self.pool.join_call(slot, chat_id, link.invite_hash, before=lambda: self.allowed(job, recheck_target=True))
                result = {"account_id": slot.account_id, "status": "active", "joined_at": now(), "rejoins": 0}
                joined.append(slot)
                ever_joined += 1
            except Exception as exc:
                result = await self.error_result(slot, exc)
            results.append(result)
            result_by_id[slot.account_id] = result
            await self.persist_results(job_id, results)
        if not joined:
            await self.finish(job_id, "failed", results, "No account established a WebRTC connection.")
            return
        last_verify = now()
        probe_failures = 0
        while now() < end_at:
            await self.allowed(job)
            if (now() - last_verify).total_seconds() >= 300:
                await self.allowed(job, recheck_target=True)
                last_verify = now()
            if any(chat_id in slot.closed_chats for slot in joined):
                break
            viable = [s for s in joined if result_by_id[s.account_id]["status"] == "active"]
            if not viable:
                break
            try:
                current_call = await self.pool.get_call(viable[0], chat_id)
                probe_failures = 0
                if not current_call or current_call.id != expected:
                    break
            except errors.FloodWaitError:
                probe_failures += 1
            except Exception:
                probe_failures += 1
            if probe_failures >= 5:
                raise UserError("Repeated Telegram call-health failures; stopped safely.")
            for slot in viable:
                result = result_by_id[slot.account_id]
                if chat_id in slot.forbidden_chats:
                    result["status"] = "removed_by_moderator"
                    continue
                if not await self.pool.in_call(slot, chat_id):
                    if result["rejoins"] >= self.config.limits.max_rejoin_attempts:
                        result["status"] = "disconnected"
                        continue
                    result["rejoins"] += 1
                    await self.sleep(min(60, 5 * 2 ** (result["rejoins"] - 1)))
                    await self.allowed(job)
                    if now() >= end_at:
                        result["status"] = "ended"
                        continue
                    # Re-check the SAME call before reconnecting; never bypass kicks/bans.
                    try:
                        current = await self.pool.get_call(slot, chat_id)
                        if not current or current.id != expected:
                            result["status"] = "ended"
                            continue
                        if not await self.pool.can_rejoin(slot, current):
                            result["status"] = "remote_removal"
                            continue
                        await self.pool.join_call(slot, chat_id, link.invite_hash, before=lambda: self.allowed(job, recheck_target=True))
                    except Exception as exc:
                        error = await self.error_result(slot, exc)
                        result["last_error_type"] = error["error_type"]
                        if isinstance(exc, FATAL_AUTH) or isinstance(exc, errors.FloodWaitError):
                            result["status"] = error["status"]
            await self.persist_results(job_id, results)
            await self.sleep(max(0, min(self.config.limits.call_poll_seconds, (end_at - now()).total_seconds())))
        for result in results:
            if result["status"] == "active":
                result["status"] = "ended"
        status = "completed" if ever_joined == job["account_count"] and all(r["status"] == "ended" for r in results) else "partial"
        await self.finish(job_id, status, results, "Call ended or configured safety/plan deadline reached.")

    async def recover(self):
        async with self.recovery_lock:
            if self.recovered:
                return
            await self.store.db.jobs.update_many(
                {"status": "running"}, {"$set": {"status": "queued", "run_at": now()}, "$unset": {"worker": ""}}
            )
            await self.store.db.accounts.update_many({}, {"$unset": {"busy_job": ""}})
            self.recovered = True

    async def run(self):
        # Runtime also calls recover BEFORE auto allocation/account startup.
        await self.recover()
        while not self.stopping:
            try:
                for job_id, task in list(self.active.items()):
                    if task.done():
                        try:
                            task.result()
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            logger.exception("Unhandled job completion; job=%s", job_id)
                        self.active.pop(job_id)
                # Cancellation works even during maintenance or without pool capacity.
                async for job in self.store.db.jobs.find({"status": "queued", "cancel_requested": True}).limit(100):
                    await self.finish(job["_id"], "cancelled", job.get("results", []), "Cancelled before execution.")
                if len(self.active) < self.config.limits.max_parallel_jobs and not await self.store.setting("maintenance", False):
                    job = await self.store.db.jobs.find_one_and_update(
                        {"status": "queued", "cancel_requested": False, "run_at": {"$lte": now()}},
                        {"$set": {"status": "running", "worker": self.store.instance, "heartbeat_at": now()}},
                        sort=[("run_at", 1)],
                        return_document=ReturnDocument.AFTER,
                    )
                    if job:
                        self.active[job["_id"]] = asyncio.create_task(self.process(job), name="job:" + job["_id"])
                await self.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler iteration failed")
                await self.sleep(5)

    async def close(self):
        self.stopping = True
        for task in self.active.values():
            task.cancel()
        if self.active:
            await asyncio.gather(*self.active.values(), return_exceptions=True)
        self.active.clear()


def job_summary(job):
    counts = Counter(r["status"] for r in job.get("results", []))
    return ", ".join(f"{name}: {count}" for name, count in sorted(counts.items())) or "No account results yet"
