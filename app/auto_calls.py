"""Opt-in authorized call watching and fair, exclusive allocation of idle accounts.

A channel is one allocation unit, not a user. Manual jobs have priority. This
never creates a call, resets its safety deadline, publishes media or evades kicks.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import suppress
from datetime import timedelta
from hashlib import sha256
import logging
import time

from pymongo.errors import DuplicateKeyError
from telethon import errors

from .accounts import FATAL_AUTH
from .session_state import auth_status
from .links import parse_link
from .plans import channel_capacity_error
from .security import UserError, html
from .timeutils import now

logger = logging.getLogger(__name__)


def fair_shares(capacity, caps, current=None):
    """Capped water filling. Keep a feasible remainder holder to avoid churn."""
    current = current or {}
    shares = {key: 0 for key in sorted(caps)}
    for _ in range(max(0, min(capacity, sum(caps.values())))):
        eligible = [key for key in shares if shares[key] < caps[key]]
        if not eligible:
            break
        chosen = min(eligible, key=lambda key: (shares[key], -(current.get(key, 0) > shares[key]), key))
        shares[chosen] += 1
    return shares


def session_id(chat_id, call_id):
    return sha256(f"auto:{chat_id}:{call_id}".encode()).hexdigest()[:24]


class AutoCalls:
    def __init__(self, runtime):
        self.r = runtime
        self.assignments = defaultdict(dict)
        self.sessions = {}
        self.config_lock = asyncio.Lock()
        self.connect_limit = asyncio.Semaphore(runtime.config.limits.auto_parallel_connects)
        self.wake = asyncio.Event()
        self.cycle = self.runner = None
        self.stopping = False
        self.last_error_type = None
        self.last_cycle_at = None
        self.probe_cursor = 0
        self.bot_not_before = 0.0

    async def recover(self):
        # The singleton runtime invokes this before any auto worker starts.
        # Preserve call IDs/deadlines/blocked accounts, never resume fake RAM ownership.
        await self.r.store.db.auto_sessions.update_many({}, {"$set": {"assigned_count": 0}})
        await self.r.store.db.targets.update_many(
            {"auto_call.enabled": True}, {"$set": {"auto_call.assigned_count": 0, "auto_call.state": "waiting for scan"}}
        )

    async def set_enabled(self, user_id, target_ids, enabled):
        if not isinstance(enabled, bool):
            raise UserError("Use an on/off automatic-call setting.")
        target_ids = sorted(set(target_ids))
        if not target_ids:
            raise UserError("Save a channel/group first.")
        async with self.r.access.target_locks.get(user_id):
            async with self.config_lock:
                if enabled:
                    if not self.r.config.calls_enabled or not self.r.config.auto_calls_enabled:
                        raise UserError("Automatic calls are disabled on this host.")
                    plan = await self.r.access.entitlement(user_id, kind="call")
                    if await self.r.store.db.targets.count_documents({"user_id": user_id}) > plan["channel_limit"]:
                        raise channel_capacity_error(plan, self.r.config)
                rows = await self.r.store.db.targets.find({"user_id": user_id, "_id": {"$in": target_ids}}).to_list(length=100)
                if len(rows) != len(target_ids):
                    raise UserError("Select only your own saved channels.")
                if enabled:
                    count = await self.r.store.db.targets.count_documents({"auto_call.enabled": True, "_id": {"$nin": target_ids}})
                    if count + len(rows) > self.r.config.limits.max_auto_channels:
                        raise UserError(f"Auto watching is limited to {self.r.config.limits.max_auto_channels} channels on this host.")
                    chat_ids = [row["chat_id"] for row in rows]
                    if len(chat_ids) != len(set(chat_ids)) or await self.r.store.db.targets.count_documents(
                        {"chat_id": {"$in": chat_ids}, "auto_call.enabled": True, "_id": {"$nin": target_ids}}
                    ):
                        raise UserError("This chat already has automatic mode under another saved target. Ask the owner to resolve it.")
                await self.r.store.audit(user_id, "auto_call_setting_authorized", target_ids=target_ids, enabled=enabled)
                try:
                    await self.r.store.db.targets.update_many(
                        {"user_id": user_id, "_id": {"$in": target_ids}},
                        {
                            "$set": {
                                "auto_call.enabled": enabled,
                                "auto_call.changed_at": now(),
                                "auto_call.state": "waiting for scan" if enabled else "disabled; leaving if busy",
                            }
                        },
                    )
                except DuplicateKeyError:
                    raise UserError(
                        "A duplicate chat was enabled concurrently. Refresh automatic calls and ask the owner to resolve it."
                    ) from None
        self.wake.set()

    async def allowed(self, target, control=False):
        self.r.pool.safety.require_allowed()
        if self.stopping or self.r.stopping or not self.r.ready or not getattr(self.r, "leader", True):
            raise UserError("Service is stopping or not ready.")
        if not self.r.config.calls_enabled or not self.r.config.auto_calls_enabled:
            raise UserError("Automatic calls are disabled on this host.")
        fresh = await self.r.targets.get(target["user_id"], target["_id"], recheck=control)
        if not fresh.get("auto_call", {}).get("enabled") or fresh["chat_id"] != target["chat_id"]:
            raise UserError("Automatic calls were disabled or the target changed.")
        plan = await self.r.access.entitlement(target["user_id"], kind="call")
        if await self.r.store.db.targets.count_documents({"user_id": target["user_id"]}) > plan["channel_limit"]:
            raise channel_capacity_error(plan, self.r.config)
        return plan

    async def target_status(self, target, state, sid=None, error_type=None):
        fields = {"auto_call.state": state, "auto_call.last_checked_at": now(), "auto_call.last_error_type": error_type}
        if sid:
            fields["auto_call.session_id"] = sid
        await self.r.store.db.targets.update_one({"_id": target["_id"], "user_id": target["user_id"]}, {"$set": fields})

    async def account_rows(self):
        rows = await self.r.store.db.accounts.find(
            {
                "enabled": True,
                "status": "healthy",
                "$or": [{"cooldown_until": {"$lte": now()}}, {"cooldown_until": {"$exists": False}}],
            }
        ).to_list(length=self.r.config.limits.max_pool_accounts)
        return {row["_id"]: row for row in rows if row["_id"] in self.r.pool.slots}

    async def detect(self, target, healthy):
        plan = await self.allowed(target, control=True)
        candidates = [
            self.r.pool.slots[key]
            for key in sorted(healthy)
            if not self.r.pool.slots[key].busy_job or self.r.pool.slots[key].busy_job.startswith("auto:")
        ]
        candidates = [slot for slot in candidates if target["chat_id"] not in slot.forbidden_chats]
        if not candidates:
            raise UserError("No healthy account is free for detection. Manual tasks have priority.")
        # Prefer an already assigned/member account, otherwise spread detector setup
        # across the pool so one account does not burn every group-join safety slot.
        seed = int(sha256(str(target["chat_id"]).encode()).hexdigest()[:8], 16) % len(candidates)
        candidates = candidates[seed:] + candidates[:seed]
        candidates.sort(key=lambda slot: target["chat_id"] not in slot.member_chats)
        slot = candidates[0]
        try:
            try:
                call = await self.r.pool.get_call(slot, target["chat_id"])
            except (ValueError, errors.ChannelPrivateError):
                # A private chat without a cached access hash needs the managed invite.
                # Never use a busy manual-job account or arbitrary private invite here.
                result = await self.r.pool.ensure_member(
                    slot, parse_link(target["call_link"]), target["chat_id"], before=lambda: self.allowed(target, control=True)
                )
                if result == "request_sent":
                    raise UserError("Detector membership is awaiting approval; this is not a joined account.")
                call = await self.r.pool.get_call(slot, target["chat_id"])
        except (errors.FloodWaitError, *FATAL_AUTH) as exc:
            await self.error_account(slot, exc)
            if isinstance(exc, FATAL_AUTH):
                await self.r.pool.detach_current(slot)
            raise
        return call, plan

    async def ensure_session(self, target, call, plan):
        sid = session_id(target["chat_id"], call.id)
        row = await self.r.store.db.auto_sessions.find_one({"_id": sid})
        window = timedelta(minutes=self.r.config.limits.max_call_minutes)
        fresh_deadline = now() + window
        if not row:
            midnight = now().replace(hour=0, minute=0, second=0, microsecond=0)
            count = await self.r.store.db.auto_sessions.count_documents({"user_id": target["user_id"], "created_at": {"$gte": midnight}})
            if count >= self.r.config.limits.max_auto_sessions_per_user_day:
                raise UserError("Automatic-call daily safety cap reached; new calls wait until UTC midnight.")
            saved = target.get("auto_call", {})
            # Reuse prior deadline only when it is still in the future. An expired
            # last_deadline from an earlier failed/boot cycle must not permanently
            # lock the same live call_id out of joining.
            prior = saved.get("last_deadline") if saved.get("last_call_id") == call.id else None
            if prior is not None and getattr(prior, "tzinfo", None) is None:
                from datetime import UTC as _UTC

                prior = prior.replace(tzinfo=_UTC)
            deadline = prior if prior and prior > now() else fresh_deadline
            row = {
                "_id": sid,
                "chat_id": target["chat_id"],
                "call_id": call.id,
                "user_id": target["user_id"],
                "target_id": target["_id"],
                "title": target["title"][:100],
                "created_at": now(),
                "deadline": deadline,
                "terminal": False,
                "status": "waiting for accounts",
                "assigned_count": 0,
                "blocked_accounts": [],
                "purge_at": now() + timedelta(days=90),
            }
            await self.r.store.db.auto_sessions.update_one({"_id": sid}, {"$setOnInsert": row}, upsert=True)
            row = await self.r.store.db.auto_sessions.find_one({"_id": sid})
            await self.r.notifier.enqueue(
                target["user_id"],
                f"<b>automatic call detected</b>\n<blockquote>Channel · {html(target['title'][:64])}\nHealthy free accounts are shared fairly, within your plan cap. Manual tasks have priority. Mic/camera stay off.</blockquote>",
                "auto-detected:" + sid + ":" + str(target["user_id"]),
            )
        if row["target_id"] != target["_id"]:
            if self.assignments.get(sid) or row.get("assigned_count"):
                raise UserError("Previous auto target is still leaving. Try again shortly.")
            await self.r.store.db.auto_sessions.update_one(
                {"_id": sid}, {"$set": {"target_id": target["_id"], "user_id": target["user_id"]}}
            )
            row.update(target_id=target["_id"], user_id=target["user_id"])

        deadline = row.get("deadline")
        if deadline is not None and getattr(deadline, "tzinfo", None) is None:
            from datetime import UTC as _UTC

            deadline = deadline.replace(tzinfo=_UTC)
            row["deadline"] = deadline

        # If this call never got a successful join (assigned_count=0) but was
        # marked terminal / expired during empty-pool boots, reopen one window.
        never_joined = not row.get("assigned_count") and not self.assignments.get(sid)
        expired = not deadline or deadline <= now()
        if (row.get("terminal") or expired) and never_joined:
            deadline = fresh_deadline
            row["deadline"] = deadline
            row["terminal"] = False
            row["status"] = "waiting for accounts"
            row["blocked_accounts"] = []
            await self.r.store.db.auto_sessions.update_one(
                {"_id": sid},
                {
                    "$set": {
                        "deadline": deadline,
                        "terminal": False,
                        "status": "waiting for accounts",
                        "blocked_accounts": [],
                    }
                },
            )
            logger.info("Auto-call session reopened; sid=%s reason=never_joined_expired", sid)
        elif expired:
            await self.terminal(sid, "safety duration reached")
            logger.info("Auto-call session skipped; sid=%s reason=safety_duration_reached", sid)
            await self.r.store.db.targets.update_one(
                {"_id": target["_id"], "auto_call.enabled": True},
                {"$set": {"auto_call.state": "safety duration reached; start a new call", "auto_call.session_id": sid}},
            )
            return None
        elif row.get("terminal"):
            logger.info("Auto-call session skipped; sid=%s reason=terminal", sid)
            return None

        await self.r.store.db.targets.update_one(
            {"_id": target["_id"], "auto_call.enabled": True},
            {"$set": {"auto_call.last_call_id": call.id, "auto_call.last_deadline": row["deadline"], "auto_call.session_id": sid}},
        )
        row.update(
            target=target,
            cap=min(plan["max_accounts"], self.r.config.limits.max_pool_accounts),
            last_verified=now(),
            blocked_accounts=set(row.get("blocked_accounts", [])),
        )
        self.sessions[sid] = row
        return sid

    async def terminal(self, sid, reason):
        await self.r.store.db.auto_sessions.update_one({"_id": sid}, {"$set": {"terminal": True, "status": reason}})
        if sid in self.sessions:
            self.sessions[sid]["terminal"] = True

    async def error_account(self, slot, exc):
        if isinstance(exc, errors.FloodWaitError):
            await self.r.pool.cooldown(slot.account_id, exc.seconds, slot=slot)
        elif isinstance(exc, FATAL_AUTH):
            await self.r.pool.set_status(slot.account_id, auth_status(exc), type(exc).__name__, slot=slot)

    async def block(self, sid, account_id, error_type):
        session = self.sessions.get(sid)
        if session:
            session["blocked_accounts"].add(account_id)
        await self.r.store.db.auto_sessions.update_one(
            {"_id": sid}, {"$addToSet": {"blocked_accounts": account_id}, "$set": {"last_error_type": error_type}}
        )

    async def drop(self, sid, key):
        slot = self.assignments.get(sid, {}).get(key)
        if not slot:
            return
        session = self.sessions.get(sid) or await self.r.store.db.auto_sessions.find_one({"_id": sid})
        try:
            if session:
                await self.r.pool.safe_leave_call(slot, session["chat_id"])
        finally:
            try:
                await self.r.pool.release([slot], "auto:" + sid)
            finally:
                self.assignments[sid].pop(key, None)

    async def manual_demand(self):
        """Leave headroom for due jobs and suppress auto on a manual-call chat."""
        demand, occupied = 0, set()
        rows = (
            await self.r.store.db.jobs.find(
                {
                    "status": {"$in": ["queued", "running"]},
                    "cancel_requested": False,
                    "run_at": {"$lte": now() + timedelta(seconds=15)},
                }
            )
            .sort("run_at", 1)
            .limit(100)
            .to_list(length=100)
        )
        queue_room = max(0, self.r.config.limits.max_parallel_jobs - len(self.r.jobs.active))
        for job in rows:
            if job.get("end_at") and job["end_at"] <= now():
                continue
            if not job.get("expected_call_id") and job["start_deadline"] <= now():
                continue
            try:
                plan = await self.r.access.entitlement(job["user_id"], kind=job["kind"])
                if job["account_count"] > plan["max_accounts"]:
                    continue
            except UserError:
                continue
            if job["status"] == "queued":
                if queue_room <= 0:
                    continue
                queue_room -= 1
            held = sum(slot.busy_job == job["_id"] for slot in self.r.pool.slots.values())
            completed = (
                sum(item["status"] in {"joined", "already_member", "request_sent"} for item in job.get("results", []))
                if job["kind"] == "join"
                else 0
            )
            demand += max(0, job["account_count"] - held - completed)
            if job["kind"] == "call":
                occupied.add(job["chat_id"])
        return demand, occupied

    async def connect(self, sid, slot):
        try:
            async with self.connect_limit:
                await self._connect(sid, slot)
        finally:
            if slot.busy_job == "auto:" + sid and slot.account_id not in self.assignments[sid]:
                session = self.sessions.get(sid) or await self.r.store.db.auto_sessions.find_one({"_id": sid})
                try:
                    if session:
                        await self.r.pool.safe_leave_call(slot, session["chat_id"])
                finally:
                    await self.r.pool.release([slot], "auto:" + sid)

    async def _connect(self, sid, slot):
        session = self.sessions[sid]
        target, chat_id = session["target"], session["chat_id"]
        kept = False
        try:
            await self.allowed(target, control=True)
            if await self.r.store.setting("maintenance", False):
                raise UserError("Maintenance is enabled.")
            link = parse_link(target["call_link"])
            membership = await self.r.pool.ensure_member(
                slot, link, chat_id, before=lambda: self.allowed(target, control=True)
            )
            if membership == "request_sent":
                raise UserError("Membership is awaiting approval.")

            async def before():
                await self.allowed(target, control=True)
                if self.stopping or now() >= session["deadline"] or await self.r.store.setting("maintenance", False):
                    raise UserError("Automatic-call authorization/deadline changed.")
                current = await self.r.pool.get_call(slot, chat_id)
                if not current or current.id != session["call_id"]:
                    raise UserError("Original call ended or changed; rescan before joining.")

            # Pass invite_hash (voicechat/videochat token) exactly like manual jobs.
            # Missing hash is a common cause of detect-ok / assigned=0 on hashed calls.
            await self.r.pool.join_call(slot, chat_id, link.invite_hash, before=before)
            await self.allowed(target)  # Disable/expiry during a native join cannot keep the connection.
            if not await self.r.pool.in_call(slot, chat_id):
                raise UserError("Native call connection was not confirmed.")
            if now() >= session["deadline"]:
                raise UserError("Automatic-call safety duration elapsed.")
            self.assignments[sid][slot.account_id] = slot
            kept = True
            logger.info("Auto-call join ok; sid=%s account=%s chat=%s", sid, slot.account_id, chat_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.error_account(slot, exc)
            # Do not immediately rotate failed/banned/kicked identities back into
            # the same call on every poll. A new call has a new bounded block set.
            detail = str(exc)[:160] if isinstance(exc, UserError) else type(exc).__name__
            logger.warning(
                "Auto-call join failed; sid=%s account=%s error=%s detail=%s",
                sid,
                slot.account_id,
                type(exc).__name__,
                detail,
            )
            await self.block(sid, slot.account_id, type(exc).__name__)
        finally:
            if not kept:
                try:
                    await self.r.pool.safe_leave_call(slot, chat_id)
                finally:
                    await self.r.pool.release([slot], "auto:" + sid)

    async def reconcile(self, active):
        healthy = await self.account_rows()
        manual_need, occupied = await self.manual_demand()
        # Keep only actual, healthy, same-call connections; never call a metadata
        # reservation a successful connection. A remote disappearance is fail closed.
        for sid, accounts in list(self.assignments.items()):
            session = self.sessions.get(sid)
            for key, slot in list(accounts.items()):
                invalid = sid not in active or not session or key not in healthy or slot.busy_job != "auto:" + sid
                invalid = invalid or (session and (session["chat_id"] in occupied or now() >= session["deadline"]))
                if not invalid:
                    try:
                        present = await self.r.pool.in_call(slot, session["chat_id"])
                        if session["chat_id"] in slot.forbidden_chats or session["chat_id"] in slot.closed_chats or not present:
                            await self.block(sid, key, "RemoteRemovalOrDisconnect")
                            invalid = True
                    except Exception:
                        invalid = True
                if invalid:
                    await self.drop(sid, key)
        active = {sid for sid in active if self.sessions[sid]["chat_id"] not in occupied}
        healthy = await self.account_rows()
        eligible = {key for key in healthy if not self.r.pool.slots[key].busy_job or self.r.pool.slots[key].busy_job.startswith("auto:")}
        capacity = max(0, len(eligible) - manual_need)
        caps = {}
        for sid in active:
            session = self.sessions[sid]
            possible = sum(
                key not in session["blocked_accounts"] and session["chat_id"] not in self.r.pool.slots[key].forbidden_chats
                for key in eligible
            )
            caps[sid] = min(session["cap"], possible)
        desired = fair_shares(capacity, caps, {sid: len(self.assignments[sid]) for sid in active})
        logger.info(
            "Auto-call reconcile; active=%s eligible=%s capacity=%s manual_need=%s desired=%s caps=%s",
            len(active),
            len(eligible),
            capacity,
            manual_need,
            {k: desired.get(k, 0) for k in active},
            {k: caps.get(k, 0) for k in active},
        )
        # Finish all excess/ended departures BEFORE any replacement reservation.
        for sid, accounts in list(self.assignments.items()):
            excess = max(0, len(accounts) - desired.get(sid, 0))
            for key in sorted(accounts, reverse=True)[:excess]:
                await self.drop(sid, key)
        for sid in sorted(active, key=lambda key: (len(self.assignments[key]), key)):
            session = self.sessions[sid]
            need = desired[sid] - len(self.assignments[sid])
            if need <= 0:
                continue
            await self.allowed(session["target"])
            available = await self.r.pool.available()
            excluded = session["blocked_accounts"] | {
                key for key, slot in self.r.pool.slots.items() if session["chat_id"] in slot.forbidden_chats
            }
            count = min(need, sum(row["_id"] not in excluded for row in available))
            if count <= 0:
                logger.info(
                    "Auto-call no free accounts after exclude; sid=%s need=%s available=%s excluded=%s",
                    sid,
                    need,
                    len(available),
                    len(excluded),
                )
                continue
            slots = await self.r.pool.reserve("auto:" + sid, count, exclude=excluded)
            if not slots:
                logger.info("Auto-call reserve empty; sid=%s count=%s", sid, count)
                continue
            try:
                await asyncio.gather(*(self.connect(sid, slot) for slot in slots))
            finally:
                # Cancellation can arrive before a gather child enters its
                # try/finally. The reservation-owning parent covers that window.
                for slot in slots:
                    if slot.busy_job == "auto:" + sid and slot.account_id not in self.assignments[sid]:
                        try:
                            await self.r.pool.safe_leave_call(slot, session["chat_id"])
                        finally:
                            await self.r.pool.release([slot], "auto:" + sid)
        for sid, session in list(self.sessions.items()):
            count = len(self.assignments[sid])
            state = "active" if count else "waiting for free accounts" if sid in active else "paused"
            fields = {"assigned_count": count}
            if not session.get("terminal"):
                fields["status"] = state
            await self.r.store.db.auto_sessions.update_one({"_id": sid}, {"$set": fields})
            await self.r.store.db.targets.update_one(
                {"_id": session["target_id"], "auto_call.session_id": sid},
                {"$set": {"auto_call.assigned_count": count, "auto_call.state": state, "auto_call.session_id": sid}},
            )
            if count:
                await self.r.notifier.enqueue(
                    session["user_id"],
                    f"<b>automatic call joined</b>\n<blockquote>Channel · {html(session['title'])}\nConnected now · {count}\nThe share changes when other calls start/end or manual tasks need capacity.</blockquote>",
                    "auto-joined:" + sid + ":" + str(session["user_id"]),
                )
        # Ended sessions still need zeroed persisted ownership for staff correction.
        for sid in list(self.assignments):
            if not self.assignments[sid]:
                await self.r.store.db.auto_sessions.update_one({"_id": sid}, {"$set": {"assigned_count": 0}})
                self.assignments.pop(sid, None)
                if self.sessions.get(sid, {}).get("terminal"):
                    self.sessions.pop(sid, None)

    async def tick(self):
        if not self.r.config.auto_calls_enabled or not self.r.config.calls_enabled or await self.r.store.setting("maintenance", False):
            reason = (
                "auto_calls_enabled=false"
                if not self.r.config.auto_calls_enabled
                else "calls_enabled=false"
                if not self.r.config.calls_enabled
                else "maintenance=on"
            )
            logger.warning("Automatic-call cycle skipped; reason=%s", reason)
            await self.quiesce()
            return
        # Only wait when NOTHING is connected yet (cold boot). Periodic health
        # scans also flip pool_loading; those must not pause live auto-calls.
        if getattr(self.r, "pool_loading", False) and not self.r.pool.slots:
            logger.info("Automatic-call cycle deferred; account pool still loading")
            return
        healthy = await self.account_rows()
        rows = (
            await self.r.store.db.targets.find({"auto_call.enabled": True})
            .sort("_id", 1)
            .limit(self.r.config.limits.max_auto_channels)
            .to_list(length=self.r.config.limits.max_auto_channels)
        )
        enabled = {row["_id"] for row in rows}
        for sid, session in list(self.sessions.items()):
            if session["target_id"] not in enabled:
                self.sessions.pop(sid, None)
        active, definitive, denied = set(), set(), set()
        detected = 0
        probe_errors = 0
        if rows:
            shift = self.probe_cursor % len(rows)
            rows = rows[shift:] + rows[:shift]
            self.probe_cursor += 1  # Long/partial scans do not always skip the last channel.
        deadline = time.monotonic() + self.r.config.limits.auto_detection_budget_seconds
        for target in rows:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or time.monotonic() < self.bot_not_before:
                break
            try:
                async with asyncio.timeout(min(remaining, self.r.config.limits.auto_probe_timeout_seconds)):
                    call, plan = await self.detect(target, healthy)
                definitive.add(target["_id"])
                for old_sid, session in list(self.sessions.items()):
                    if session["target_id"] == target["_id"] and (not call or session["call_id"] != call.id):
                        await self.terminal(old_sid, "call ended or replaced")
                if call:
                    detected += 1
                    sid = await self.ensure_session(target, call, plan)
                    if sid:
                        active.add(sid)
                        await self.target_status(target, "call detected", sid)
                    else:
                        await self.target_status(target, "safety duration reached; waiting for a new call")
                else:
                    await self.target_status(target, "waiting for a call")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                probe_errors += 1
                if isinstance(exc, UserError):
                    denied.add(target["_id"])  # Explicit authorization failure is not a transient network probe.
                if hasattr(exc, "retry_after"):
                    self.bot_not_before = time.monotonic() + exc.retry_after + 1
                logger.warning(
                    "Auto-call probe failed; target=%s error=%s detail=%s",
                    target.get("_id"),
                    type(exc).__name__,
                    str(exc)[:120] if isinstance(exc, UserError) else type(exc).__name__,
                )
                await self.target_status(
                    target, "check delayed" if not isinstance(exc, UserError) else str(exc)[:140], error_type=type(exc).__name__
                )
        # A temporary probe failure is not proof that a call ended. Retain only
        # recently confirmed, still-authorized connections; stale ones leave.
        for sid, session in list(self.sessions.items()):
            if sid in active or session.get("terminal"):
                continue
            if session["target_id"] in definitive or session["target_id"] in denied or now() >= session["deadline"]:
                continue
            try:
                plan = await self.allowed(session["target"])
                session["cap"] = min(plan["max_accounts"], self.r.config.limits.max_pool_accounts)
                if (now() - session["last_verified"]).total_seconds() <= self.r.config.limits.auto_stale_seconds:
                    active.add(sid)
            except UserError:
                pass
        await self.reconcile(active)
        assigned = sum(len(accounts) for accounts in self.assignments.values())
        logger.info(
            "Automatic-call cycle; targets=%s healthy_accounts=%s calls_detected=%s active_sessions=%s assigned=%s probe_errors=%s",
            len(rows),
            len(healthy),
            detected,
            len(active),
            assigned,
            probe_errors,
        )
        self.last_cycle_at, self.last_error_type = now(), None

    async def quiesce(self):
        results = await asyncio.gather(
            *(self.drop(sid, key) for sid, slots in list(self.assignments.items()) for key in list(slots)), return_exceptions=True
        )
        for error in results:
            if isinstance(error, Exception):
                logger.warning("Auto-call departure failed; error=%s", type(error).__name__)
        await self.r.store.db.auto_sessions.update_many({}, {"$set": {"assigned_count": 0}})
        await self.r.store.db.targets.update_many(
            {"auto_call.enabled": True}, {"$set": {"auto_call.assigned_count": 0, "auto_call.state": "paused / service restarting"}}
        )

    async def run(self):
        self.runner = asyncio.current_task()
        try:
            while not self.stopping:
                self.wake.clear()
                self.cycle = asyncio.create_task(self.tick(), name="auto-call-cycle")
                changed = asyncio.create_task(self.wake.wait(), name="auto-config-change")
                try:
                    done, _ = await asyncio.wait([self.cycle, changed], return_when=asyncio.FIRST_COMPLETED)
                    if changed in done and not self.cycle.done():
                        self.cycle.cancel()
                    with suppress(asyncio.CancelledError):
                        await self.cycle
                except asyncio.CancelledError:
                    self.cycle.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await self.cycle
                    raise
                except Exception as exc:
                    self.last_error_type = type(exc).__name__
                    logger.exception("Automatic-call cycle failed; error=%s", type(exc).__name__)
                    with suppress(Exception):
                        await self.quiesce()
                finally:
                    changed.cancel()
                    with suppress(asyncio.CancelledError):
                        await changed
                    self.cycle = None
                if self.wake.is_set():
                    continue
                with suppress(TimeoutError):
                    await asyncio.wait_for(self.wake.wait(), self.r.config.limits.auto_call_poll_seconds)
        finally:
            with suppress(Exception):
                await self.quiesce()

    async def close(self):
        self.stopping = True
        self.wake.set()
        if self.runner and self.runner is not asyncio.current_task() and not self.runner.done():
            self.runner.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.runner
        with suppress(Exception):
            await self.quiesce()
