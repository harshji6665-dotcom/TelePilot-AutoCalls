"""Bounded, non-blocking staff health runs; never a real-call success claim."""

import asyncio
from contextlib import suppress
from copy import deepcopy
import logging
import secrets
import time

from pymongo.errors import PyMongoError
from aiogram.exceptions import TelegramRetryAfter

from .compat import local_compatibility
from .timeutils import now
from .live_diagnostics import observe_existing_call, health_evidence, REPORT_SETTING, bot_reference

logger = logging.getLogger(__name__)


class HealthChecks:
    def __init__(self, runtime):
        self.r = runtime
        self.task = None
        self.lock = asyncio.Lock()
        self.watchers = {}
        self.state = None
        self.last_notify = 0.0
        self.not_before = 0.0

    async def start(self, actor):
        await self.r.access.require_staff(actor)
        async with self.lock:
            if self.task and not self.task.done():
                return self.snapshot()
            if self.state and ((now() - self.state["started_at"]).total_seconds() < 30 or time.monotonic() < self.not_before):
                return self.snapshot()  # Reuse recent results instead of spamming API checks.
            self.watchers.clear()
            self.state = {
                "run_id": secrets.token_hex(8),
                "status": "running",
                "started_at": now(),
                "components": {},
                "accounts": [],
                "checked": 0,
                "total": None,
            }
            self.task = asyncio.create_task(self.run(), name="manual-health")
            self.task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            return self.snapshot()

    def snapshot(self):
        return deepcopy(self.state) if self.state else None

    def watch(self, actor, callback):
        if len(self.watchers) >= 64 and actor not in self.watchers:
            self.watchers.pop(next(iter(self.watchers)))
        self.watchers[actor] = callback

    async def notify(self, force=False):
        tick = time.monotonic()
        if not force and tick - self.last_notify < 3:
            return
        self.last_notify = tick
        for actor, callback in list(self.watchers.items()):
            try:
                keep = await callback(self.snapshot())
            except Exception:
                keep = False  # Includes UI FloodWait; check can still finish safely.
            if not keep:
                self.watchers.pop(actor, None)

    async def run(self):
        try:
            async with asyncio.timeout(self.r.config.limits.manual_health_timeout_seconds):
                try:
                    await asyncio.wait_for(self.r.store.client.admin.command("ping"), 5)
                    self.state["components"]["database"] = "connected"
                except Exception as exc:
                    self.state["components"]["database"] = "failed: " + type(exc).__name__
                    self.state["status"] = "failed"
                    return
                try:
                    me = await asyncio.wait_for(self.r.bot.get_me(), 10)
                    self.state["_bot_reference"] = bot_reference(me.id)
                    self.state["components"]["bot api"] = "connected"
                except Exception as exc:
                    self.state["components"]["bot api"] = "failed: " + type(exc).__name__
                    if isinstance(exc, TelegramRetryAfter):
                        self.not_before = time.monotonic() + exc.retry_after + 1
                workers_ok = self.r.ready and not self.r.stopping and all(not task.done() for task in self.r.tasks)
                self.state["components"]["workers"] = "running" if workers_ok else "not ready"
                self.state["components"]["account roster"] = (
                    "loading/checking in background" if getattr(self.r, "pool_loading", False) else "idle; see per-account results"
                )
                try:
                    local_compatibility(self.r.config.calls_enabled)
                    self.state["components"]["call adapter"] = (
                        "installed; no live call tested" if self.r.config.calls_enabled else "disabled on this host"
                    )
                except Exception as exc:
                    self.state["components"]["call adapter"] = "failed: " + type(exc).__name__
                auto = getattr(self.r, "auto_calls", None)
                if auto:
                    self.state["components"]["automatic calls"] = (
                        "disabled on this host"
                        if not self.r.config.auto_calls_enabled
                        else "failed: " + auto.last_error_type
                        if auto.last_error_type
                        else "running; live connection not independently tested"
                        if auto.runner and not auto.runner.done()
                        else "not started"
                    )
                await self.notify()

                async def progress(result, total):
                    self.state["accounts"].append(result)
                    self.state["checked"] += 1
                    self.state["total"] = total
                    await self.notify()

                await self.r.pool.scan_health(progress)
                if self.state["total"] is None:
                    self.state["total"] = 0
                self.state["call_observation"] = await observe_existing_call(self.r)
                observation = self.state["call_observation"]["status"]
                self.state["components"]["existing call sample"] = (
                    "native + Telegram self participant verified (1 sample)"
                    if observation == "verified"
                    else "not verified: " + observation
                )
                self.state["status"] = "complete"
        except TimeoutError:
            self.state["status"] = "partial"
            self.state["error_type"] = "TimeoutError"
        except asyncio.CancelledError:
            self.state["status"] = "stopped"
            raise
        except Exception as exc:
            self.state["status"] = "failed"
            self.state["error_type"] = type(exc).__name__
            if isinstance(exc, PyMongoError):
                self.state["components"]["database"] = "failed: " + type(exc).__name__
            logger.error("Manual health scan failed; error=%s", type(exc).__name__)
        finally:
            self.state["finished_at"] = now()
            try:
                await asyncio.wait_for(self.r.store.set_setting(REPORT_SETTING, health_evidence(self.r, self.state)), 3)
            except Exception as exc:
                logger.warning("Sanitized host verification export unavailable; error=%s", type(exc).__name__)
            await self.notify(force=True)

    async def close(self):
        self.watchers.clear()
        if self.task and not self.task.done():
            self.task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.task
