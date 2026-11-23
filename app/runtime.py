from __future__ import annotations

import asyncio
from contextlib import suppress, nullcontext
from datetime import timedelta
import logging
import signal
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
import uvicorn

from .accounts import AccountPool
from .bot import BotPanel
from .compat import Compatibility, local_compatibility
from . import __version__
from .config import load_config
from .jobs import JobEngine
from .logging_setup import configure_logging
from .login import LoginManager
from .notifier import Notifier
from .security import Vault, html
from .services import Access, Plans, Targets
from .store import Store
from .timeutils import now
from .web import build_web
from .ui import StyleRequests
from .health import HealthChecks
from .force_sub import ForceSubscriptions
from .auto_calls import AutoCalls

logger = logging.getLogger(__name__)


class ServiceStartupError(RuntimeError):
    """Authored operator diagnostics with no secret values."""


class ManagedServer(uvicorn.Server):
    def capture_signals(self):
        # Runtime owns SIGTERM/SIGINT, including during cloud startup/handover.
        return nullcontext()


class ErrorAlertHandler(logging.Handler):
    def __init__(self, notifier):
        super().__init__(logging.ERROR)
        self.notifier, self.loop, self.last = notifier, asyncio.get_running_loop(), 0.0

    def emit(self, record):
        if record.name == "app.notifier" or time.monotonic() - self.last < 60:
            return
        self.last = time.monotonic()
        error_type = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else "RuntimeError"
        text = f"<b>Runtime health alert</b>\n<blockquote>Component: {html(record.name)}\nError type: {html(error_type)}\nInspect sanitized JSON logs. Alerts are limited to once/minute.</blockquote>"

        def schedule():
            task = asyncio.create_task(self.notifier.owners(text, "runtime-error:" + now().isoformat()))
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

        self.loop.call_soon_threadsafe(schedule)


class Runtime:
    def __init__(self, config):
        self.config = config
        self.store = Store(config)
        self.store.lease_fence_enabled = True
        self.bot = Bot(config.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.bot.session.middleware(StyleRequests(config))
        self.dp = Dispatcher(storage=MemoryStorage())
        self.access = Access(self.store, config)
        self.notifier = Notifier(self.store, self.bot, config)
        self.pool = AccountPool(self.store, self.access, Vault(config.session_encryption_key.get_secret_value()), self.notifier, config)
        self.login = LoginManager(self.store, self.access, self.pool, self.notifier, config)
        self.pool.safety.on_pause = self.abort_pending_logins
        self.plans = Plans(self.store, self.access, self.notifier, config)
        self.compat = Compatibility(self.store, self.notifier, config)
        self.targets = self.jobs = None
        self.force_subs = self.auto_calls = None
        self.tasks = []
        self.ready = self.stopping = False
        self.stop_event = asyncio.Event()
        self.server = None
        self.error_handler = None
        self.leader = False
        self.pool_loading = True
        self.health = HealthChecks(self)

    async def abort_pending_logins(self):
        for key in list(self.login.contexts):
            await self.login.close_context(key)

    async def lease_monitor(self):
        while not self.stopping:
            if not self.store.lease_valid():
                self.store.fence()
                self.ready = False
                self.stop_event.set()
                logger.error("Runtime ownership deadline reached; account socket writes fenced")
                return
            await asyncio.sleep(1)

    async def periodic(self):
        last_compat = now() - timedelta(hours=self.config.compatibility_check_hours)
        while not self.stopping:
            try:
                await self.login.cleanup()
                await self.plans.expire()
                if (now() - last_compat).total_seconds() >= self.config.compatibility_check_hours * 3600:
                    await self.compat.check()
                    last_compat = now()
                await asyncio.sleep(15)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Maintenance health-check iteration failed")
                await asyncio.sleep(15)

    async def account_health(self):
        # Full identity health probes retain the configured interval. A cheap
        # wakeable tick recovers only failed transports/checkpoints in between.
        # pool_loading is only for cold boot (initial sync). Do not flip it here
        # or auto-calls freeze for minutes on every health_interval scan.
        next_scan = 0.0
        while not self.stopping:
            full = asyncio.get_running_loop().time() >= next_scan
            try:
                if full:
                    await self.pool.sync()
                    next_scan = asyncio.get_running_loop().time() + self.config.limits.health_interval_seconds
                else:
                    await self.pool.recover_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Account recovery iteration failed; saved authorizations retained")
                if full:
                    next_scan = asyncio.get_running_loop().time() + 15
            await self.pool.wait_for_recovery(min(15, max(0.1, next_scan - asyncio.get_running_loop().time())))

    async def lease_heartbeat(self):
        while not self.stopping:
            await asyncio.sleep(20)
            if self.stopping:
                return
            try:
                if not await self.store.acquire_leader():
                    raise RuntimeError("Leadership lost")
            except Exception:
                # Fail closed. No bot/jobs remain active without a singleton Mongo lease.
                logger.exception("Runtime lease lost; shutting down safely")
                self.store.fence()
                self.ready = False
                self.stop_event.set()
                return

    async def start_http(self):
        # Bring liveness up before a slow account reload or singleton handover.
        # The web API stays locked until the bot, DB and workers are ready.
        self.server = ManagedServer(
            uvicorn.Config(
                build_web(self),
                host="0.0.0.0",
                port=self.config.http_port,
                log_level="warning",
                log_config=None,
                access_log=False,
                timeout_graceful_shutdown=10,
                proxy_headers=True,
                forwarded_allow_ips="*",
            )
        )
        task = asyncio.create_task(self.server.serve(), name="http")
        self.tasks.append(task)
        async with asyncio.timeout(20):
            while not self.server.started:
                if task.done():
                    raise ServiceStartupError("HTTP server failed to start. Check PORT and bind permissions.")
                if self.stop_event.is_set():
                    raise ServiceStartupError("Startup interrupted.")
                await asyncio.sleep(0.05)
        logger.info("HTTP listener ready; port=%s (automation remains locked until startup completes)", self.config.http_port)

    async def wait_for_leader(self):
        deadline = time.monotonic() + self.config.startup_lease_timeout_seconds
        announced = False
        while not self.leader:
            if self.stop_event.is_set() or any(task.done() for task in self.tasks):
                raise ServiceStartupError("Startup interrupted before singleton lease acquisition.")
            self.leader = await self.store.acquire_leader()
            if self.leader:
                return
            if time.monotonic() >= deadline:
                raise ServiceStartupError(
                    "Another runtime still holds this bot/database lease. Stop duplicate deployments; use one replica and retry after the old lease expires."
                )
            if not announced:
                logger.info("Waiting for previous runtime to release singleton lease; no Telegram account clients have started")
                announced = True
            await asyncio.sleep(2)

    async def start(self):
        local_compatibility(self.config.calls_enabled)
        await self.start_http()
        try:
            await self.store.initialize()
        except Exception as exc:
            raise ServiceStartupError(
                f"MongoDB initialization failed ({type(exc).__name__}). Check MONGO_URI, database access, DNS/network allowlist and credentials."
            ) from None
        await self.wait_for_leader()
        self.tasks.append(asyncio.create_task(self.lease_heartbeat(), name="lease"))
        self.tasks.append(asyncio.create_task(self.lease_monitor(), name="lease-monitor"))
        await self.pool.safety.initialize()
        await self.store.migrate_plans()
        try:
            me = await self.bot.get_me()
        except Exception as exc:
            raise ServiceStartupError(
                f"Telegram bot startup failed ({type(exc).__name__}). Check BOT_TOKEN and outbound Telegram access."
            ) from None
        self.targets = Targets(self.store, self.bot, self.access, me.id)
        self.jobs = JobEngine(self.store, self.access, self.targets, self.pool, self.notifier, self.config)
        self.force_subs = ForceSubscriptions(self.store, self.bot, self.access, me.id, self.config)
        self.access.force_subs = self.force_subs
        self.auto_calls = AutoCalls(self)
        self.access.auto_wakeup = self.jobs.auto_wakeup = self.auto_calls.wake.set
        await self.jobs.recover()
        await self.auto_calls.recover()
        self.dp.include_router(BotPanel(self).router)
        await self.bot.delete_webhook(drop_pending_updates=False)
        await self.bot.set_my_commands(
            [
                BotCommand(command=c, description=d)
                for c, d in [
                    ("start", "Open panel"),
                    ("plan", "View Premium plan"),
                    ("targets", "Manage authorized targets"),
                    ("jobs", "View and cancel jobs"),
                    ("auto", "Automatic call settings and status"),
                    ("autostop", "Turn off all your automatic calls"),
                    ("id", "Show your user ID"),
                    ("help", "Help and commands"),
                    ("cancel", "Cancel form and return home"),
                ]
            ]
        )
        # A heartbeat already protects the lease throughout Bot API/account startup.
        if self.stop_event.is_set():
            raise RuntimeError("Startup interrupted or singleton lease lost during account loading")
        self.error_handler = ErrorAlertHandler(self.notifier)
        logging.getLogger().addHandler(self.error_handler)
        # Bot polling first so /start and /diag respond during account load.
        self.tasks.append(
            asyncio.create_task(
                self.dp.start_polling(
                    self.bot, handle_signals=False, close_bot_session=False, allowed_updates=["message", "callback_query"]
                ),
                name="bot-polling",
            )
        )
        self.tasks.append(asyncio.create_task(self.notifier.run(), name="notifications"))
        self.ready = True
        # Load the account roster BEFORE auto-calls/jobs so probes do not run
        # against an empty in-memory pool (healthy_accounts=0 false negatives).
        try:
            await self.pool.sync()
        except Exception as exc:
            logger.warning("Initial account pool sync failed; error=%s", type(exc).__name__)
        self.pool_loading = False
        saved = await self.store.db.accounts.count_documents({})
        enabled = await self.store.db.accounts.count_documents({"enabled": True})
        healthy_slots = sum(1 for slot in self.pool.slots.values() if not slot.disconnected and not slot.closing)
        safety = "paused" if self.pool.safety.paused else "ok"
        logger.info(
            "TelePilot started; version=%s accounts_saved=%s enabled=%s connected=%s session_safety=%s",
            __version__,
            saved,
            enabled,
            healthy_slots,
            safety,
        )
        self.tasks.extend(
            [
                asyncio.create_task(self.jobs.run(), name="scheduler"),
                asyncio.create_task(self.auto_calls.run(), name="auto-calls"),
                asyncio.create_task(self.periodic(), name="maintenance"),
                asyncio.create_task(self.account_health(), name="account-health"),
            ]
        )
        hint = (
            "No connected user accounts yet. Owner: open the bot private chat → Accounts → Sign in."
            if healthy_slots == 0
            else f"{healthy_slots} account(s) connected in memory."
        )
        await self.notifier.owners(
            "<b>TelePilot is online</b>\n"
            f"<blockquote>Bot workers are online. Saved accounts: {saved}, enabled: {enabled}, connected now: {healthy_slots}. "
            f"Session safety: {html(safety)}. {html(hint)} "
            "Use /sessionguard, /diag and /health for details. Original encrypted data is retained.</blockquote>",
            "startup:" + self.store.instance,
        )

    async def wait(self):
        stopper = asyncio.create_task(self.stop_event.wait(), name="stop-event")
        done, _ = await asyncio.wait([stopper, *self.tasks], return_when=asyncio.FIRST_COMPLETED)
        stopper.cancel()
        for task in done:
            if task is not stopper and not self.stopping:
                if task.exception():
                    logger.error(
                        "Critical service task failed; task=%s",
                        task.get_name(),
                        exc_info=(type(task.exception()), task.exception(), task.exception().__traceback__),
                    )
                else:
                    logger.warning("Critical service task stopped; task=%s", task.get_name())

    async def close(self):
        self.stopping, self.ready = True, False
        if self.error_handler:
            logging.getLogger().removeHandler(self.error_handler)
        if self.server:
            self.server.should_exit = True
        await self.health.close()
        if self.auto_calls:
            await self.auto_calls.close()
        # Stop periodic lifecycle changes before disconnecting the account pool.
        for task in self.tasks:
            if task.get_name() in {"maintenance", "account-health"}:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
        if self.jobs:
            await self.jobs.close()
        await self.login.close()
        with suppress(Exception):
            await self.pool.close()
        self.notifier.stopping = True
        # Let Uvicorn deliver ASGI lifespan.shutdown instead of immediately
        # cancelling its task and producing a false cleanup traceback on an
        # otherwise healthy idle deployment. HTTP draining is separately bounded.
        http_tasks = {task for task in self.tasks if task.get_name() == "http" and not task.done()}
        if http_tasks:
            _, pending = await asyncio.wait(http_tasks, timeout=15)
            if pending:
                logger.warning("HTTP graceful shutdown deadline exceeded; cancelling server")
                if self.server:
                    self.server.force_exit = True
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.store.fence()
        cleanup_confirmed = not (self.pool.retired or self.pool.disconnects or self.pool.cleanup_tasks or self.pool.client_registry)
        if self.leader and cleanup_confirmed:
            with suppress(Exception):
                await self.store.release_leader()
        elif self.leader:
            logger.error("Unconfirmed account cleanup; singleton lease not released for immediate handover")
        await self.dp.storage.close()
        await self.bot.session.close()
        await self.store.close()


async def main():
    config = load_config()
    configure_logging(config)
    runtime = Runtime(config)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, runtime.stop_event.set)
    try:
        await runtime.start()
        await runtime.wait()
    finally:
        await runtime.close()
