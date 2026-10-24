from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import secrets
import logging
import random
from contextlib import suppress
from io import BytesIO

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pymongo import ReturnDocument
from telethon import errors
from telethon.sessions import StringSession

from .session_state import session_guard
from .accounts import Slot
from .security import UserError, digest, token, html
from .timeutils import now

logger = logging.getLogger(__name__)


class PoolFullError(UserError):
    """An actionable enrollment-capacity failure, not Telegram authentication."""

    def __init__(self, count, limit):
        self.count, self.limit = count, limit
        super().__init__(
            f"Account pool is full ({count}/{limit} saved). Ask the owner to raise MAX_POOL_ACCOUNTS up to 200 and redeploy. Existing accounts can still be re-authenticated; no need to delete good sessions."
        )


@dataclass
class LoginContext:
    context_id: str
    actor: int
    csrf: str
    browser_code: str
    expires_at: datetime
    reauth_id: str | None = None
    stage: str = "approval"
    client: object | None = None
    phone: str | None = None
    phone_code_hash: str | None = None
    attempts: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    completed_account: str | None = None
    transport: str = "browser"
    chat_id: int | None = None
    consent_accepted: bool = False
    method: str = "otp"
    qr: object | None = None
    qr_wait_task: asyncio.Task | None = None
    qr_message_id: int | None = None
    reauth_generation: str | None = None
    preserve_authorization: bool = False
    reauth_revision: int | None = None


class LoginManager:
    """Transient, staff-bound account login; passwords/codes never enter storage/logs.

    Private-chat mode is explicitly less private than a trusted HTTPS/local flow.
    Telegram message deletion is best effort, not a zero-retention guarantee.
    """

    def __init__(self, store, access, pool, notifier, config):
        self.store, self.access, self.pool, self.notifier, self.config = store, access, pool, notifier, config
        self.contexts: dict[str, LoginContext] = {}
        self.by_id: dict[str, LoginContext] = {}
        self.issue_times: dict[int, datetime] = {}
        self.finish_lock = asyncio.Lock()
        self.issue_lock = asyncio.Lock()
        self.chat_contexts: dict[int, LoginContext] = {}
        self.account_claims: dict[str, str] = {}
        self.login_cooldowns: dict[int, datetime] = {}
        self.post_login_tasks: set[asyncio.Task] = set()
        self.stopping = False

    async def check_login_cooldown(self, actor):
        row = await self.store.db.users.find_one({"_id": actor}, {"login_cooldown_until": 1}) or {}
        until = max(self.login_cooldowns.get(actor, now()), row.get("login_cooldown_until", now()))
        if until > now():
            raise UserError(
                f"Telegram login cooldown is active. Wait at least {max(1, int((until - now()).total_seconds()) + 1)} seconds; no early retries are allowed."
            )

    async def record_login_floodwait(self, actor, seconds):
        until = now() + timedelta(seconds=max(1, seconds) + 1)
        self.login_cooldowns[actor] = until
        try:
            await self.store.db.users.update_one(
                {"_id": actor}, {"$set": {"login_cooldown_until": until}, "$setOnInsert": {"created_at": now()}}, upsert=True
            )
        except Exception:
            logger.exception("Could not persist login FloodWait; actor=%s (RAM cooldown remains active)", actor)

    async def capacity(self):
        count = await self.store.db.accounts.count_documents({})
        limit = self.config.limits.max_pool_accounts
        return {"saved": count, "limit": limit, "free": max(0, limit - count)}

    async def require_capacity(self):
        state = await self.capacity()
        if state["saved"] >= state["limit"]:
            raise PoolFullError(state["saved"], state["limit"])

    async def validate_start(self, actor, reauth_id=None):
        self.pool.safety.require_allowed()
        await self.access.require_staff(actor)
        await self.check_login_cooldown(actor)
        if not reauth_id:
            await self.require_capacity()
            return None
        row = await self.store.db.accounts.find_one({"_id": reauth_id})
        if not row:
            raise UserError("Account not found.")
        await self.access.can_manage_account(actor, row)
        if (row.get("cooldown_until") or now()) > now():
            raise UserError("Account cooldown is active. Keep the saved session and wait; sign-in cannot be used to bypass Telegram waits.")
        async with self.pool.lock:
            slot = self.pool.slots.get(reauth_id)
            if slot and slot.busy_job:
                raise UserError("Cancel this account's active job before re-authenticating.")
            if not row.get("session_generation"):
                updated = await self.store.db.accounts.find_one_and_update(
                    {"_id": reauth_id, **session_guard(row)},
                    {"$set": {"session_generation": secrets.token_hex(16)}},
                    return_document=ReturnDocument.AFTER,
                )
                row = updated or await self.store.db.accounts.find_one({"_id": reauth_id})
                if not row:
                    raise UserError("Account was removed. Start again from Accounts.")
        # OTP/QR consent/cancel/failure never disables or logs out the old session.
        return row

    async def begin_chat(self, actor, chat_id, reauth_id=None):
        if self.config.login_mode != "chat":
            raise UserError("Private-chat sign-in is disabled by LOGIN_MODE.")
        if chat_id != actor:
            raise UserError("Sign in only in your own private chat with this bot.")
        async with self.issue_lock:
            reauth_row = await self.validate_start(actor, reauth_id)
            if self.issue_times.get(actor, now() - timedelta(minutes=1)) > now() - timedelta(seconds=45):
                raise UserError("Wait 45 seconds before starting another sign-in. Slow realistic pacing protects accounts.")
            claim = self.account_claims.get(reauth_id) if reauth_id else None
            holder = self.by_id.get(claim) if claim else None
            if holder and holder.actor != actor:
                raise UserError("Another authorized operator already has a pending re-authentication for this account.")
            for key, old in list(self.contexts.items()):
                if old.actor == actor:
                    await self.close_context(key)
            await self.store.db.login_tickets.delete_many({"actor": actor})
            ctx = LoginContext(
                secrets.token_hex(12),
                actor,
                "",
                "",
                now() + timedelta(minutes=10),
                reauth_id,
                stage="consent",
                transport="chat",
                chat_id=chat_id,
                reauth_generation=(reauth_row or {}).get("session_generation"),
                reauth_revision=(reauth_row or {}).get("account_revision", 0) if reauth_row else None,
            )
            self.contexts["chat:" + str(actor)] = ctx
            self.by_id[ctx.context_id] = ctx
            self.chat_contexts[actor] = ctx
            if reauth_id:
                self.account_claims[reauth_id] = ctx.context_id
            self.issue_times[actor] = now()
            return ctx

    async def get_chat(self, actor, context_id):
        ctx = self.chat_contexts.get(actor)
        if not ctx or ctx.context_id != context_id or ctx.transport != "chat":
            raise UserError("Sign-in is unavailable/expired. Start a fresh sign-in from Accounts.")
        if ctx.expires_at <= now():
            await self.close_context("chat:" + str(actor))
            raise UserError("Sign-in expired after 10 minutes. Start again from Accounts.")
        try:
            await self.access.require_staff(actor)
        except UserError:
            await self.close_context("chat:" + str(actor))
            raise
        return ctx

    async def confirm_chat(self, actor, context_id, method="otp"):
        ctx = await self.get_chat(actor, context_id)
        if ctx.lock.locked():
            raise UserError("A sign-in operation is already running. Wait for its response.")
        async with ctx.lock:
            if ctx.stage != "consent" or method not in ("otp", "qr"):
                raise UserError("This consent button was already processed or is unavailable.")
            current = await self.validate_start(actor, ctx.reauth_id)
            if ctx.reauth_id and ctx.reauth_generation != (current or {}).get("session_generation"):
                raise UserError("This account was replaced after the dialog opened. Cancel and open its latest panel.")
            ctx.consent_accepted, ctx.method = True, method
            ctx.stage = "phone" if method == "otp" else "qr"
            await self.store.audit(actor, "login_chat_consent", method=method, reauthentication=bool(ctx.reauth_id))
            if method == "qr":
                try:
                    ctx.client = self.pool.make_client()
                    await asyncio.wait_for(ctx.client.connect(), 25)
                    ctx.qr = await asyncio.wait_for(ctx.client.qr_login(), 30)
                    lifetime = max(1, min(60, (ctx.qr.expires - now()).total_seconds()))
                    ctx.qr_wait_task = asyncio.create_task(ctx.qr.wait(timeout=lifetime), name="qr-signin:" + ctx.context_id)
                    # Consume exceptions without serializing their sensitive messages.
                    ctx.qr_wait_task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
                    await asyncio.sleep(0)  # Install the SDK update handler before displaying the QR.
                except Exception as exc:
                    logger.exception("QR sign-in initialization failed; actor=%s phase=qr", actor)
                    ctx.stage = "denied"
                    await self.discard_client(ctx)
                    if isinstance(exc, errors.FloodWaitError):
                        await self.record_login_floodwait(actor, exc.seconds)
                        raise UserError(f"Telegram requires waiting {exc.seconds} seconds. Do not retry before then.") from None
                    raise UserError(
                        f"QR sign-in failed ({type(exc).__name__}). Start again; inspect sanitized logs if it repeats."
                    ) from None
            return ctx

    def qr_image(self, ctx):
        if ctx.transport != "chat" or ctx.stage != "qr" or not ctx.qr:
            raise UserError("QR sign-in is unavailable.")
        import qrcode
        from qrcode.image.pure import PyPNGImage

        image = qrcode.make(ctx.qr.url, image_factory=PyPNGImage, box_size=8, border=4)
        output = BytesIO()
        image.save(output)
        return output.getvalue()

    async def check_qr(self, actor, context_id):
        ctx = await self.get_chat(actor, context_id)
        if ctx.lock.locked():
            raise UserError("A sign-in operation is already running.")
        async with ctx.lock:
            if ctx.stage != "qr" or not ctx.qr_wait_task:
                raise UserError("This QR step is no longer active.")
            if not ctx.qr_wait_task.done():
                raise UserError("QR approval has not arrived yet. Approve only your own sign-in in Telegram, then check again.")
            try:
                ctx.qr_wait_task.result()
                await self.finish(ctx)
            except errors.SessionPasswordNeededError:
                ctx.stage = "password"
            except Exception as exc:
                ctx.stage = "denied"
                await self.discard_client(ctx)
                if isinstance(exc, UserError):
                    raise
                if isinstance(exc, errors.FloodWaitError):
                    await self.record_login_floodwait(actor, exc.seconds)
                    raise UserError(f"Telegram requires waiting {exc.seconds} seconds. No early login retries are allowed.") from None
                logger.exception("QR sign-in completion failed; actor=%s phase=qr", actor)
                raise UserError(
                    f"QR expired/rejected or could not complete ({type(exc).__name__}). Start a fresh sign-in; no code/password was saved."
                ) from None
            finally:
                await self.delete_qr_message(ctx)
                ctx.qr = None
            return self.status(ctx)

    async def delete_qr_message(self, ctx):
        if ctx.qr_message_id and ctx.chat_id:
            with suppress(Exception):
                await self.notifier.bot.delete_message(ctx.chat_id, ctx.qr_message_id)
            ctx.qr_message_id = None

    async def cancel_actor(self, actor):
        for key, ctx in list(self.contexts.items()):
            if ctx.actor == actor:
                await self.close_context(key)

    async def create_ticket(self, actor, reauth_id=None):
        await self.access.require_staff(actor)
        if self.config.login_mode != "browser":
            raise UserError("Browser sign-in is disabled. Use the private-chat Sign in account panel.")
        await self.check_login_cooldown(actor)
        if not self.config.public_base_url:
            raise UserError("Set public_base_url to your HTTPS domain in config.json and deploy the TLS proxy before signing in accounts.")
        if self.issue_times.get(actor, now() - timedelta(minutes=1)) > now() - timedelta(seconds=20):
            raise UserError("Wait 20 seconds before requesting another login link.")
        reauth_row = await self.validate_start(actor, reauth_id)
        for cookie_hash, context in list(self.contexts.items()):
            if context.actor == actor:
                await self.close_context(cookie_hash)
        await self.store.db.login_tickets.delete_many({"actor": actor})
        secret = token()
        await self.store.db.login_tickets.insert_one(
            {
                "_id": digest(secret),
                "actor": actor,
                "reauth_id": reauth_id,
                "reauth_generation": (reauth_row or {}).get("session_generation"),
                "reauth_revision": (reauth_row or {}).get("account_revision", 0) if reauth_row else None,
                "expires_at": now() + timedelta(minutes=5),
                "used": False,
            }
        )
        self.issue_times[actor] = now()
        # Fragment is not sent to HTTP servers or proxy access logs.
        return self.config.public_base_url + "/login#token=" + secret

    async def exchange(self, secret):
        if self.config.login_mode != "browser":
            raise UserError("Browser sign-in is disabled.")
        ticket = await self.store.db.login_tickets.find_one_and_update(
            {"_id": digest(secret), "used": False, "expires_at": {"$gt": now()}},
            {"$set": {"used": True}},
            return_document=ReturnDocument.AFTER,
        )
        if not ticket:
            raise UserError("Login link is expired/already used. Request a fresh one inside the bot.")
        await self.access.require_staff(ticket["actor"])
        cookie, csrf = token(), token()
        ctx = LoginContext(
            secrets.token_hex(6),
            ticket["actor"],
            csrf,
            secrets.token_hex(3).upper(),
            now() + timedelta(minutes=10),
            ticket.get("reauth_id"),
            reauth_generation=ticket.get("reauth_generation"),
            reauth_revision=ticket.get("reauth_revision"),
        )
        self.contexts[digest(cookie)] = ctx
        self.by_id[ctx.context_id] = ctx
        buttons = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Approve this browser", callback_data="login:yes:" + ctx.context_id),
                    InlineKeyboardButton(text="Deny", callback_data="login:no:" + ctx.context_id),
                ]
            ]
        )
        try:
            await self.notifier.bot.send_message(
                ctx.actor,
                f"<b>🔐 Account sign-in approval</b>\n<blockquote>Browser code: <code>{ctx.browser_code}</code>\n"
                f"Site: {html(self.config.public_base_url)}\nApprove ONLY if this code matches the page you opened.\nApproval expires in 10 minutes. Never share this link/code.</blockquote>",
                reply_markup=buttons,
            )
        except Exception:
            await self.close_context(digest(cookie))
            raise UserError(
                "Could not send approval to your Telegram account. Unblock/start the bot and request a new login link."
            ) from None
        return cookie, csrf, ctx

    async def approve(self, actor, context_id, approved):
        await self.access.require_staff(actor)
        if self.config.login_mode != "browser":
            raise UserError("Browser sign-in is disabled. Use private-chat sign-in.")
        ctx = self.by_id.get(context_id)
        if not ctx or ctx.actor != actor or ctx.expires_at <= now():
            raise UserError("This approval is unavailable/expired or belongs to another admin.")
        async with ctx.lock:
            if ctx.stage != "approval":
                raise UserError("This approval was already processed.")
            ctx.stage = "phone" if approved else "denied"
        await self.store.audit(actor, "login_browser_approved" if approved else "login_browser_denied")

    async def get(self, cookie, csrf=None):
        ctx = self.contexts.get(digest(cookie or ""))
        if not ctx or ctx.expires_at <= now():
            raise UserError("Login session expired. Request a fresh link in the bot.")
        await self.access.require_staff(ctx.actor)
        if csrf is not None and not secrets.compare_digest(ctx.csrf, csrf):
            raise UserError("Invalid browser security token.")
        return ctx

    def status(self, ctx):
        return {
            "stage": ctx.stage,
            "browser_code": ctx.browser_code,
            "account_id": ctx.completed_account,
            "expires_at": ctx.expires_at.isoformat(),
            "actor_id": ctx.actor,
        }

    async def step(self, ctx, value):
        self.pool.safety.require_allowed()
        if ctx.transport == "chat" and ctx.lock.locked():
            raise UserError("A sign-in step is already running. Wait for the prompt before sending the next value.")
        async with ctx.lock:
            await self.access.require_staff(ctx.actor)
            if ctx.expires_at <= now():
                raise UserError("Login session expired.")
            if ctx.transport == "chat" and not ctx.consent_accepted:
                raise UserError("Confirm account ownership with the consent button before entering credentials.")
            if ctx.stage not in ("phone", "code", "password"):
                raise UserError("Use the current sign-in buttons and wait for a credential prompt.")
            ctx.attempts += 1
            if ctx.attempts > 8:
                ctx.stage = "denied"
                await self.discard_client(ctx)
                raise UserError("Too many attempts. Request a new link.")
            phase = ctx.stage
            try:
                if ctx.stage == "phone":
                    import re

                    phone = value.strip().replace(" ", "").replace("-", "")
                    if not re.fullmatch(r"\+[1-9]\d{6,14}", phone):
                        raise UserError("Use international format, e.g. +919876543210.")
                    # Dispose any prior unauthenticated client before requesting again.
                    await self.discard_client(ctx)
                    ctx.client = self.pool.make_client()
                    await asyncio.wait_for(ctx.client.connect(), 25)
                    # Human-like pause before requesting login code (reduces rate-limit / silent drops).
                    await asyncio.sleep(random.uniform(2.5, 6.5))
                    sent = await asyncio.wait_for(ctx.client.send_code_request(phone), 30)
                    delivery = type(getattr(sent, "type", None)).__name__
                    if delivery in ("SentCodeTypeSetUpEmailRequired", "SentCodeTypeFirebaseSms"):
                        ctx.stage = "denied"
                        raise UserError(
                            "Telegram requires an email/device verification flow this adapter does not implement. Use QR sign-in or Telegram's official authorized login flow; no protection is bypassed."
                        )
                    code_hash = getattr(sent, "phone_code_hash", None)
                    if not code_hash:
                        ctx.stage = "denied"
                        raise UserError(
                            "Telegram requires a login verification flow unsupported by this adapter. Use an eligible account or update the adapter."
                        )
                    ctx.phone, ctx.phone_code_hash, ctx.stage = phone, code_hash, "code"
                elif ctx.stage == "code":
                    value = value.strip()
                    if not value.isascii() or not value.isdigit() or not 4 <= len(value) <= 8:
                        raise UserError("Enter the numeric login code received from Telegram.")
                    try:
                        await asyncio.wait_for(ctx.client.sign_in(phone=ctx.phone, code=value, phone_code_hash=ctx.phone_code_hash), 30)
                    except errors.SessionPasswordNeededError:
                        ctx.stage = "password"
                    else:
                        await self.finish(ctx)
                elif ctx.stage == "password":
                    await asyncio.wait_for(ctx.client.sign_in(password=value), 30)
                    await self.finish(ctx)
            except errors.PhoneCodeInvalidError:
                raise UserError("Incorrect OTP. Check Telegram's latest login code; limited retries remain.") from None
            except errors.PasswordHashInvalidError:
                raise UserError("Incorrect 2FA password. Limited retries remain.") from None
            except errors.PhoneCodeExpiredError:
                ctx.stage = "denied"
                raise UserError(
                    "OTP expired. Telegram can invalidate codes sent in chats. Start a fresh sign-in and use the QR alternative or a trusted official flow; do not disguise/reuse codes to bypass protections."
                ) from None
            except errors.FloodWaitError as exc:
                ctx.stage = "denied"
                await self.record_login_floodwait(ctx.actor, exc.seconds)
                raise UserError(f"Telegram requires waiting {exc.seconds} seconds. Do not retry before that time.") from None
            except (errors.PhoneNumberInvalidError, errors.PhoneNumberBannedError) as exc:
                ctx.stage = "denied"
                raise UserError(f"Telegram rejected this phone number ({type(exc).__name__}).") from None
            except UserError:
                # If authorization succeeded but storage/ownership validation failed,
                # do not leave a newly authorized orphan session behind.
                if ctx.client and ctx.stage in ("code", "password"):
                    with suppress(Exception):
                        if await asyncio.wait_for(ctx.client.is_user_authorized(), 5):
                            ctx.stage = "denied"
                raise
            except Exception as exc:
                logger.exception("Account sign-in failed; actor=%s phase=%s transport=%s", ctx.actor, phase, ctx.transport)
                ctx.stage = "denied"
                raise UserError(
                    f"Telegram login failed at {phase} ({type(exc).__name__}). Start a fresh sign-in; inspect sanitized logs/API credentials/network if it repeats. No code/password was saved by the application."
                ) from None
            finally:
                value = ""  # No credential is persisted; Python cannot guarantee memory zeroization.
                if ctx.stage == "denied":
                    await self.discard_client(ctx)
                elif ctx.stage == "complete" and ctx.client:
                    await ctx.client.disconnect()
                    ctx.client = None
                    ctx.phone = ctx.phone_code_hash = None
            return self.status(ctx)

    async def finish(self, ctx):
        async with self.finish_lock:
            await self.access.require_staff(ctx.actor)
            me = await asyncio.wait_for(ctx.client.get_me(), 20)
            if not me or me.bot:
                raise UserError("Only your own Telegram user accounts are supported, not bot accounts.")
            await self.access.require_staff(ctx.actor)
            if ctx.expires_at <= now():
                raise UserError("Sign-in expired before saving. Start a fresh sign-in.")
            account_id = str(me.id)
            if ctx.reauth_id and ctx.reauth_id != account_id:
                await ctx.client.log_out()
                ctx.stage = "denied"
                raise UserError("Wrong account: re-authentication must use the original Telegram user ID.")
            previous = await self.store.db.accounts.find_one({"_id": account_id})
            if previous:
                await self.access.can_manage_account(ctx.actor, previous)
                if not ctx.reauth_id:
                    await ctx.client.log_out()
                    ctx.stage = "denied"
                    raise UserError("This account is already registered. Use its Re-authenticate control instead.")
            else:
                if ctx.reauth_id:
                    raise UserError("Account was removed during sign-in; this dialog cannot recreate it.")
                try:
                    await self.require_capacity()
                except PoolFullError:
                    ctx.stage = "denied"
                    with suppress(Exception):
                        await asyncio.wait_for(ctx.client.log_out(), 10)
                    raise
            ciphertext = self.pool.vault.encrypt(StringSession.save(ctx.client.session))
            name = " ".join(filter(None, [me.first_name, me.last_name]))[:80]
            generation = secrets.token_hex(16)
            fields = {
                "telegram_id": me.id,
                "name": name,
                "phone_hint": (ctx.phone or getattr(me, "phone", None) or (previous or {}).get("phone_hint", ""))[-4:],
                "session_ciphertext": ciphertext,
                "session_generation": generation,
                "session_saved_at": now(),
                "enabled": True,
                "status": "offline",
                "added_by": (previous or {}).get("added_by", ctx.actor),
                "updated_at": now(),
                "recovery_failures": 0,
                "last_error_type": None,
            }
            # New enrollments never wait for a large health roster. Replacements
            # serialize only their short commit/swap, after successful login.
            if previous:
                async with self.pool.sync_lock:
                    async with self.pool.lock:
                        await self.commit_saved(ctx, account_id, fields, previous)
            else:
                async with self.pool.lock:
                    await self.commit_saved(ctx, account_id, fields, None)
            ctx.completed_account, ctx.stage = account_id, "complete"
            # The temporary login transport has strong pool ownership before the
            # Mongo write. No replacement may attach until its real cleanup ends.
            with suppress(Exception):
                await self.pool.detach(account_id)
            ctx.client = None
            ctx.phone = ctx.phone_code_hash = None
            # Saved means committed in Mongo, not "wait for the entire pool's
            # health scan". Queue owned background attach; the UI can reply now.
            self.schedule_attach(account_id)
            try:
                await self.store.audit(
                    ctx.actor,
                    "account_authenticated",
                    account_id=account_id,
                    reauthentication=bool(ctx.reauth_id),
                    transport=ctx.transport,
                    method=ctx.method,
                )
                await self.notifier.enqueue(
                    ctx.actor,
                    f"<b>Account saved securely</b>\n<blockquote>Telegram ID: <code>{account_id}</code>\nEncrypted session stored in MongoDB. Open Accounts to view health.</blockquote>",
                    "account-login:" + ctx.context_id,
                )
            except Exception:
                logger.exception("Account saved but post-login health/audit/notification needs retry; account=%s", account_id)

    async def commit_saved(self, ctx, account_id, fields, previous):
        self.pool.safety.require_allowed()
        await self.access.require_staff(ctx.actor)
        if ctx.expires_at <= now():
            raise UserError("Sign-in expired before saving; the original saved session is unchanged.")
        current = await self.store.db.accounts.find_one({"_id": account_id})
        if previous:
            if not current:
                raise UserError("Account was removed during sign-in; no saved data was recreated.")
            await self.access.can_manage_account(ctx.actor, current)
            expected_generation = ctx.reauth_generation or previous.get("session_generation")
            if expected_generation and current.get("session_generation") != expected_generation:
                raise UserError("A newer authorization was already saved. This stale dialog cannot replace it.")
            revision = ctx.reauth_revision if ctx.reauth_revision is not None else previous.get("account_revision", 0)
            if current.get("account_revision", 0) != revision:
                raise UserError("Staff changed this account during sign-in. The original saved state is retained; reopen the latest panel.")
            fields["account_revision"] = revision + 1
            old = self.pool.slots.get(account_id)
            if old and old.busy_job:
                raise UserError(
                    "Account became busy during sign-in; cancel the job before replacing its session. The old session is unchanged."
                )
            await self.pool.detach(account_id)
        elif current:
            raise UserError("This account was registered while sign-in was pending. Use its current panel.")
        if account_id in self.pool.retired:
            raise UserError(
                "Previous transport cleanup is not confirmed. Saved authorization is unchanged; safe cleanup will retry automatically."
            )
        # Transfer before storage: even a lost Mongo acknowledgement or caller
        # cancellation cannot orphan/revoke a possibly committed authorization.
        transport = Slot(
            account_id,
            ctx.client,
            closing=True,
            session_generation=fields["session_generation"],
            session_ciphertext=fields["session_ciphertext"],
        )
        self.pool.retired[account_id] = transport
        ctx.preserve_authorization = True
        try:
            if previous:
                result = await self.store.db.accounts.update_one(
                    {"_id": account_id, **session_guard(current)},
                    {
                        "$set": fields,
                        "$unset": {
                            "connection_epoch": "",
                            "next_recovery_at": "",
                            "authorization_block": "",
                            "authorization_error_type": "",
                        },
                    },
                )
                if not result.matched_count:
                    # An acknowledged zero-match is definitively not a commit.
                    ctx.preserve_authorization = False
                    raise UserError("Saved authorization changed or was removed. The stale replacement was not committed.")
            else:
                await self.store.db.accounts.insert_one(dict(fields, _id=account_id, created_at=now()))
        except BaseException as exc:
            # Check the primary for a lost acknowledgement. If this read also
            # fails/doesn't confirm it, NEVER log_out a possibly saved key.
            confirmed = None
            with suppress(Exception):
                confirmed = await self.store.db.accounts.find_one({"_id": account_id, "session_generation": fields["session_generation"]})
            if confirmed:
                ctx.preserve_authorization = True
            else:
                self.pool.recovery_wake.set()
                if ctx.preserve_authorization and not isinstance(exc, asyncio.CancelledError):
                    logger.warning("Account save confirmation uncertain; authorization not revoked; error=%s", type(exc).__name__)
                    raise UserError(
                        "Session save could not be confirmed. No possibly saved authorization was logged out. Check Accounts and MongoDB before requesting another OTP; keep the original database/encryption key."
                    ) from None
                raise

    def schedule_attach(self, account_id):
        if self.stopping:
            return
        task = asyncio.create_task(self.attach_saved(account_id), name="post-login-health:" + account_id)
        self.post_login_tasks.add(task)
        task.add_done_callback(self.post_login_tasks.discard)

    async def attach_saved(self, account_id):
        try:
            async with self.pool.sync_lock:
                if not self.stopping:
                    await self.pool.attach(account_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Saved account health load needs retry; account=%s", account_id)

    async def discard_client(self, ctx):
        if ctx.qr_wait_task and not ctx.qr_wait_task.done():
            ctx.qr_wait_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await ctx.qr_wait_task
        await self.delete_qr_message(ctx)
        ctx.qr = None
        if ctx.client:
            try:
                if (
                    not ctx.completed_account
                    and not ctx.preserve_authorization
                    and await asyncio.wait_for(ctx.client.is_user_authorized(), 5)
                ):
                    await asyncio.wait_for(ctx.client.log_out(), 10)
            except Exception:
                pass
            finally:
                with suppress(Exception):
                    owned = next((item for item in self.pool.retired.values() if item.client is ctx.client), None)
                    if owned:
                        await self.pool.detach(owned.account_id)
                    else:
                        await self.pool.disconnect_client(ctx.client, timeout=10)
                ctx.client = None
        ctx.phone = ctx.phone_code_hash = None

    async def close_context(self, cookie_hash):
        ctx = self.contexts.pop(cookie_hash, None)
        if ctx:
            async with ctx.lock:
                await self.discard_client(ctx)
                ctx.stage = "denied"
            self.by_id.pop(ctx.context_id, None)
            if self.chat_contexts.get(ctx.actor) is ctx:
                self.chat_contexts.pop(ctx.actor, None)
            if ctx.reauth_id and self.account_claims.get(ctx.reauth_id) == ctx.context_id:
                self.account_claims.pop(ctx.reauth_id, None)

    async def cleanup(self):
        for cookie_hash, ctx in list(self.contexts.items()):
            from .security import Role

            if ctx.expires_at <= now() or await self.access.role(ctx.actor) == Role.USER:
                await self.close_context(cookie_hash)

    async def close(self):
        self.stopping = True
        for task in self.post_login_tasks:
            task.cancel()
        if self.post_login_tasks:
            await asyncio.gather(*self.post_login_tasks, return_exceptions=True)
        self.post_login_tasks.clear()
        for cookie_hash in list(self.contexts):
            await self.close_context(cookie_hash)
