from __future__ import annotations

from datetime import timedelta
from contextlib import suppress
import json
import logging
import secrets
import time

from aiogram import BaseMiddleware, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, BufferedInputFile, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .jobs import job_summary
from .login import PoolFullError
from .plans import (
    normalized_plan,
    effective_plan,
    feature_allowed,
    feature_label,
    FEATURE_PLANS,
    UNLIMITED,
    quota_label,
    channel_capacity_error,
    account_capacity_error,
)
from .plan_ui import PlanUI
from .health import HealthChecks
from .force_sub import ForceSubscriptions, SubscriptionRequired
from .auto_calls import AutoCalls
from .automation_ui import AutomationUI
from .start_photo import StartPhotoUI
from .session_safety_ui import SessionSafetyUI
from .session_state import RECOVERY_BLOCKED, recovery_hint
from .diagnostics import result_explanation, error_overview
from .security import Role, UserError, html
from .timeutils import now, display_time, parse_schedule
from .ui import Panels

logger = logging.getLogger(__name__)


class Input(StatesGroup):
    target = State()
    link = State()
    count = State()
    duration = State()
    schedule = State()
    confirm = State()
    grant = State()
    grant_user = State()
    grant_feature = State()
    grant_days = State()
    grant_channels = State()
    grant_accounts = State()
    grant_mode = State()
    grant_confirm = State()
    correction_user = State()
    correction_reason = State()
    correction_confirm = State()
    revoke = State()
    add_admin = State()
    remove_admin = State()
    banner = State()
    chat_signin = State()
    force_sub_input = State()
    force_sub_confirm = State()
    auto_confirm = State()


def keyboard(*rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=text, **({"url": value[4:]} if value.startswith("url:") else {"callback_data": value}))
                for text, value in row
            ]
            for row in rows
        ]
    )


HOME = keyboard([("🏠 Home", "nav:home")])


async def delete_private_input(message):
    # Best effort only: Telegram/bot chats are not E2E and may retain copies.
    try:
        delete = getattr(message, "delete", None)
        if delete:
            await delete()
    except Exception:
        pass  # Never log an input, deletion failure or credential-bearing event.


class Guard(BaseMiddleware):
    def __init__(self, runtime, panels, gate=None):
        self.r, self.ui, self.gate = runtime, panels, gate

    async def __call__(self, handler, event, data):
        message = event.message if isinstance(event, CallbackQuery) else event
        if not message or not event.from_user:
            return
        if message.chat.type != ChatType.PRIVATE:
            if isinstance(event, Message) and event.text and event.text.split()[0].split("@")[0] == "/chatid":
                await message.answer(
                    f"Chat ID: <code>{message.chat.id}</code>\nAdd this bot as admin with Invite Users permission, then register this ID in a private chat."
                )
            return
        cleanup = secret = False
        raw, delivered = message, False
        message = self.ui.wrap(message, event.from_user.id)
        command = ""
        try:
            if isinstance(event, CallbackQuery):
                # ACK only clears the spinner; errors are rendered below, never
                # hidden behind a second already-answered callback popup.
                with suppress(TelegramAPIError):
                    await event.answer()
                data["callback_acknowledged"] = True
            else:
                secret = event.from_user.id in self.r.login.chat_contexts
                if secret:
                    await delete_private_input(raw)
                state = data.get("state")
                active_form = await state.get_state() if state else None
                if active_form == Input.chat_signin.state and not secret:
                    secret = True
                    await delete_private_input(raw)
                cleanup = secret or (self.r.config.ui_clean_inputs and (active_form or (raw.text or "").startswith("/")))
            await self.r.store.touch_user(event.from_user.id, getattr(event.from_user, "username", None))
            subscriptions = getattr(self.r, "force_subs", None)
            command = (getattr(raw, "text", None) or "").split(maxsplit=1)
            command = command[0].split("@")[0].lower() if command else ""
            callback = (getattr(event, "data", None) or "") if isinstance(event, CallbackQuery) else ""
            exempt = command in {"/help", "/id", "/chatid", "/cancel", "/autostop", "/diag"}
            exempt = exempt or callback in {"fs:check", "nav:help", "nav:rules", "contact:admin", "auto:off_all"}
            exempt = exempt or callback.startswith(("auto:off:", "job:cancel:"))
            if subscriptions and not exempt:
                await subscriptions.require(event.from_user.id)
            result = await handler(event, data)
            delivered = True
            return result
        except SubscriptionRequired as exc:
            if self.gate:
                try:
                    await self.gate(
                        message,
                        event.from_user.id,
                        exc.rows,
                        exc.error_type,
                        fresh=not isinstance(event, CallbackQuery) and command == "/start",
                    )
                    delivered = True
                except Exception:
                    logger.warning("Membership panel unavailable; actor=%s", event.from_user.id)
                    if self.ui.cooldowns.get(event.from_user.id, 0) <= time.monotonic():
                        try:
                            controls = keyboard(
                                *[[("join " + row["title"][:30], "url:" + row["join_url"])] for row in exc.rows],
                                [("check membership", "fs:check")],
                            )
                            await raw.answer(
                                "Join the required channels/groups, then check membership. The previous screen could not be edited.",
                                parse_mode=None,
                                reply_markup=controls,
                            )
                            delivered = True
                        except Exception:
                            pass
            else:
                await message.answer(str(exc), reply_markup=HOME)
                delivered = True
        except UserError as exc:
            try:
                controls = (
                    keyboard([("accounts", "accounts:0"), ("pool capacity", "staff:capacity")])
                    if isinstance(event, CallbackQuery)
                    and (getattr(event, "data", "") or "").startswith(("account:", "signin:"))
                    and await self.r.access.role(event.from_user.id) != Role.USER
                    else HOME
                )
                await message.answer(f"<blockquote>{html(exc)}</blockquote>", reply_markup=controls)
                delivered = True
            except Exception:
                # A broken edit must not hide the error. Never send early during
                # a known Telegram rate pause, and do not re-ACK an answered query.
                if self.ui.cooldowns.get(event.from_user.id, 0) <= time.monotonic():
                    try:
                        await raw.answer(str(exc), parse_mode=None, reply_markup=HOME)
                        delivered = True
                    except Exception:
                        pass
        except Exception as exc:
            incident = secrets.token_hex(4)
            logger.exception("Bot action failed; incident=%s user=%s", incident, event.from_user.id)
            # User recovery must NOT depend on a successful owner outbox/database write.
            try:
                if self.ui.cooldowns.get(event.from_user.id, 0) <= time.monotonic():
                    await raw.answer(f"Temporary screen error. Try /start again. Incident: {incident}", parse_mode=None, reply_markup=HOME)
                    delivered = True
            except Exception:
                logger.warning("User error response unavailable; incident=%s", incident)
            try:
                await self.r.notifier.owners(
                    f"<b>Runtime error</b>\n<blockquote>Incident: <code>{incident}</code>\nType: {html(type(exc).__name__)}\nSee sanitized JSON logs.</blockquote>",
                    "error:" + incident,
                )
            except Exception:
                logger.warning("Owner error notice unavailable; incident=%s", incident)
        finally:
            # Never make a failed ordinary /start look successful by deleting it first.
            if cleanup and not secret and delivered:
                await delete_private_input(raw)


class BotPanel(PlanUI, AutomationUI, StartPhotoUI, SessionSafetyUI):
    Input = Input
    keyboard = staticmethod(keyboard)

    def __init__(self, runtime):
        self.r = runtime
        self.ui = Panels(runtime)
        if not getattr(runtime, "force_subs", None):
            runtime.force_subs = ForceSubscriptions(runtime.store, runtime.bot, runtime.access, runtime.targets.bot_id, runtime.config)
        runtime.access.force_subs = runtime.force_subs
        if not getattr(runtime, "auto_calls", None):
            runtime.auto_calls = AutoCalls(runtime)
        runtime.access.auto_wakeup = runtime.auto_calls.wake.set
        runtime.jobs.auto_wakeup = runtime.auto_calls.wake.set
        if not getattr(runtime, "health", None):
            runtime.health = HealthChecks(runtime)
        self.router = Router(name="panel")
        self.router.message.outer_middleware(Guard(runtime, self.ui, self.force_gate))
        self.router.callback_query.outer_middleware(Guard(runtime, self.ui, self.force_gate))
        self.router.message.register(self.on_message)
        self.router.callback_query.register(self.on_callback)

    async def home(self, message, user_id, with_image=False):
        role = await self.r.access.role(user_id)
        user = await self.r.store.db.users.find_one({"_id": user_id}) or {}
        premium = user.get("plan", {}).get("expires_at")
        label = role.value.title() if role != Role.USER else "Premium" if premium and premium > now() else "Free"
        healthy = (
            0 if self.r.pool.safety.blocked() else await self.r.store.db.accounts.count_documents({"enabled": True, "status": "healthy"})
        )
        text = f"<b>✦ telepilot</b>\n\n<blockquote>access · <b>{html(label)}</b>\nready accounts · <b>{healthy}</b>\ntimezone · <code>{html(self.r.config.timezone)}</code></blockquote>\n\nchoose a button below. Use only accounts and channels you own or may manage."
        if self.r.pool.safety.blocked():
            text += "\n\n<blockquote>Account automation is paused for session/runtime safety. Contact the owner; staff can inspect /sessionguard. Saved data has not been deleted.</blockquote>"
        plan = normalized_plan(user.get("plan"), self.r.config) if role == Role.USER else await self.r.access.entitlement(user_id)
        active = bool(premium and premium > now())
        automation = []
        if role != Role.USER or (active and feature_allowed(plan, "join")):
            automation.append(("📥 join channels", "new:join"))
        if self.r.config.calls_enabled and (role != Role.USER or (active and feature_allowed(plan, "call"))):
            automation.append(("🎧 join a call", "new:call"))
        rows = ([automation] if automation else []) + [
            [("🗓 my tasks", "jobs:mine:0"), ("💎 my plan", "nav:plan")],
            [("🔒 my channels", "targets:0"), ("❓ help", "nav:help")],
            [self.contact_button()],
        ]
        if (
            self.r.config.calls_enabled
            and self.r.config.auto_calls_enabled
            and (role != Role.USER or (active and feature_allowed(plan, "call")))
        ):
            rows.insert(1 if automation else 0, [("⚡ automatic calls", "auto:home:0")])
        if role != Role.USER:
            rows.append([("⚙️ manage bot", "nav:staff")])
        markup = keyboard(*rows)
        # An explicit start replaces BOTH visible parts (photo above text).
        # Optional media is bounded and never hides the text/error response.
        if with_image:
            await self.send_start_photo(message, user_id)
        if with_image and self.r.config.ui_edit_panels:
            await message.answer(text, reply_markup=markup, fresh=True)
        else:
            await message.answer(text, reply_markup=markup)

    def contact_button(self):
        username = self.r.config.admin_username or self.r.config.support_username
        return ("💬 contact admin", "url:https://t.me/" + username if username else "contact:admin")

    async def plan(self, message, user_id):
        role = await self.r.access.role(user_id)
        user = await self.r.store.db.users.find_one({"_id": user_id}) or {}
        plan = normalized_plan(user.get("plan"), self.r.config)
        active = bool(plan.get("expires_at") and plan["expires_at"] > now())
        saved = await self.r.store.db.targets.count_documents({"user_id": user_id})
        text = f"<b>💎 my plan</b>\n<blockquote>User · <code>{user_id}</code>\nStatus · {'premium' if active else 'free / expired'}\nFeatures · {html(feature_label(plan['feature_plan'])) if active else 'none'}\nUntil · {html(display_time(plan.get('expires_at'), self.r.config.timezone))}\nChannels/groups · {saved} / {quota_label(plan, 'channels') if active else 'no active allowance'}\nAccounts per task · {quota_label(plan, 'accounts') if active else 0}</blockquote>\n\n"
        text += "Unlimited is a plan quota, not unlimited host resources: current and future healthy pool accounts are eligible within operational ceilings. Manual tasks keep their reviewed count; automatic calls rebalance fairly. Only included features are available. Saved channels stay locked after expiry and renewal; users cannot remove or replace them. Contact an admin for corrections or upgrades. Payments are handled manually."
        if role != Role.USER:
            text += "\nStaff have separate, config-limited test access."
        await message.answer(text, reply_markup=keyboard([self.contact_button()], [("🏠 home", "nav:home")]))

    async def help(self, message):
        await message.answer(
            "<b>❓ quick guide</b>\n\n"
            "<blockquote>① contact admin and choose a plan: channels only, calls only or both. Your plan also sets channel slots and accounts per task.\n"
            "② add this bot as an admin in your channel/group with invite permission. Open my channels, then add its @username or chat ID. Use <code>/chatid</code> there to find the ID.\n"
            "③ check before saving: that channel becomes locked. Only an owner/admin can correct it. Expiry or renewal does not free the slot.\n"
            "④ choose your available feature, accounts and time. Review and confirm. Track or stop it in my tasks.\n"
            "⑤ for automatic calls, enable your saved channels once. The bot watches active calls and shares free accounts fairly within plan caps. Manual tasks have priority. Turn it off in automatic calls or use /autostop.</blockquote>\n\n"
            "Use <code>/cancel</code> or <code>/start</code> to start over. Staff use <code>/signin</code> for owned accounts and <code>/premiumhelp</code> for plan examples.",
            reply_markup=keyboard([self.contact_button()], [("📋 limits & safety", "nav:rules")], [("🏠 home", "nav:home")]),
        )

    async def rules(self, message):
        await message.answer(
            "<b>📋 limits & safety</b>\n\n"
            "<blockquote>Public targets use direct join. Private targets use the saved request invite. If Telegram still requires approval, request sent means not joined yet.\n"
            "Calls are group/channel voice or video chats only. Mic and camera stay off. No recording. <code>t.me/call/...</code> conferences are not supported.\n"
            "A call stops when it ends, your plan ends, you cancel, or the selected time limit is reached.\n"
            "Telegram waits, bans and removals are respected. No bypass or no-ban promise.</blockquote>\n\n"
            "<b>account sign-in</b>\nBot chats are not end-to-end encrypted. Read the ownership/privacy notice first. Codes may expire in chat; QR is an alternative.\n"
            "Premium payments are handled by an owner/admin, not this bot.",
            reply_markup=keyboard([("← quick guide", "nav:help")], [("🏠 home", "nav:home")]),
        )

    async def staff(self, message, user_id):
        role = await self.r.access.require_staff(user_id)
        rows = [
            [("➕ add account", "account:add"), ("📱 accounts", "accounts:0")],
            [("💎 give premium", "staff:grant"), ("🚫 remove premium", "staff:revoke")],
            [("👥 users", "users:0"), ("🗓 all tasks", "jobs:all:0")],
            [("📊 overview", "staff:stats"), ("🩺 check health", "staff:health")],
            [("🔒 channel corrections", "staff:channels"), ("📖 premium examples", "staff:premium_help")],
            [("🔔 required subscriptions", "fs:view"), ("⚡ auto overview", "staff:auto_overview")],
            [("📦 pool capacity", "staff:capacity"), ("session safety", "sg:view")],
        ]
        if role == Role.OWNER:
            rows.extend(
                [
                    [("➕ Add admin", "owner:add_admin"), ("➖ Remove admin", "owner:remove_admin")],
                    [("👑 Admin list", "owner:admins"), ("🖼 start photo", "owner:photo")],
                    [("🧾 Audit", "owner:audit"), ("🔄 Compatibility", "owner:updates")],
                    [("🧰 Toggle maintenance", "owner:maintenance")],
                ]
            )
        rows.append([("🏠 User panel", "nav:home")])
        await message.answer(
            f"<b>🛠 {html(role.value.title())} panel</b>\n<blockquote>Admins: plans, own account sessions, job moderation, statistics.\nOwners additionally manage admins, all accounts, banner, maintenance and audit.\nNo panel exposes session strings, OTPs, passwords or API secrets.</blockquote>",
            reply_markup=keyboard(*rows),
        )

    async def accounts(self, message, user_id, page):
        role = await self.r.access.require_staff(user_id)
        page = max(0, page)
        rows = await self.r.store.db.accounts.find({}).sort("created_at", -1).skip(page * 8).limit(8).to_list(length=8)
        capacity = await self.r.login.capacity()
        lines, buttons = [], [[("➕ sign in account", "account:add"), ("pool capacity", "staff:capacity")]]
        for account in rows:
            manageable = role == Role.OWNER or account["added_by"] == user_id
            lines.append(
                f"<code>{account['_id']}</code> · {html(account['status'])} · {'busy' if account.get('busy_job') else 'idle'} · {'enabled' if account['enabled'] else 'disabled'}"
            )
            if manageable:
                buttons.append([(f"{account.get('name') or account['_id']} · {account['status']}", "account:view:" + account["_id"])])
        if page:
            buttons.append([("← Previous", f"accounts:{page - 1}")])
        if len(rows) == 8:
            buttons.append([("Next →", f"accounts:{page + 1}")])
        buttons.append([("⚙️ manage", "nav:staff")])
        await message.answer(
            f"<b>📱 account pool</b>\nSaved · {capacity['saved']} / {capacity['limit']}\n<blockquote>"
            + ("\n".join(lines) or "No accounts yet. Add your first account from the manage menu.")
            + "</blockquote>\nAdmins can manage only the accounts they added.",
            reply_markup=keyboard(*buttons),
        )

    async def account(self, message, user_id, account_id):
        account = await self.r.store.db.accounts.find_one({"_id": account_id})
        if not account:
            raise UserError("Account not found.")
        await self.r.access.can_manage_account(user_id, account)
        rows = [
            [
                ("Disable" if account["enabled"] else "Enable", "account:toggle:" + account_id),
                ("sign in again", "account:reauth:" + account_id),
            ],
            [("Remove…", "account:remove:" + account_id)],
            [("← Accounts", "accounts:0")],
        ]
        if account.get("enabled") and account.get("session_ciphertext") and account.get("status") not in RECOVERY_BLOCKED:
            rows.insert(1, [("reconnect saved session", "account:recover:" + account_id)])
        text = (
            f"<b>📱 {html(account.get('name', account_id))}</b>\n<blockquote>ID: <code>{account_id}</code>\nPhone: ••••{html(account.get('phone_hint', ''))}\n"
            f"Status: {html(account['status'])}\nAdded by: <code>{account['added_by']}</code>\nBusy job: {html(account.get('busy_job', '—'))}\n"
            f"Last health: {html(display_time(account.get('last_health_at'), self.r.config.timezone))}\n"
            f"Cooldown until: {html(display_time(account.get('cooldown_until'), self.r.config.timezone))}\nNext recovery: {html(display_time(account.get('next_recovery_at'), self.r.config.timezone))}\nError type: <code>{html(account.get('last_error_type') or '—')}</code>\n{html(recovery_hint(account))}</blockquote>"
        )
        await message.answer(text, reply_markup=keyboard(*rows))

    async def capacity(self, message, actor, blocked=False):
        await self.r.access.require_staff(actor)
        state = await self.r.login.capacity()
        loading = getattr(self.r, "pool_loading", False)
        await message.answer(
            f"<b>{'account pool is full' if blocked else 'account pool capacity'}</b>\n"
            f"<blockquote>Saved accounts · <b>{state['saved']} / {state['limit']}</b>\nFree sign-in slots · <b>{state['free']}</b>\nPool check · {'loading in background' if loading else 'normal'}</blockquote>\n"
            "Owners can raise the deployment setting up to 200. Existing private config may still contain the old 20-account value. Set this non-secret service variable and rebuild/redeploy:\n"
            "<pre>MAX_POOL_ACCOUNTS=200</pre>"
            "Or edit <code>limits.max_pool_accounts</code> in your external config.json. Env takes priority. This is a saved-account capacity, not a Telegram guarantee or a change to purchased plan limits. Keep the original encryption key/database. Re-authentication of saved accounts remains available when full.",
            reply_markup=keyboard(
                [("try add account", "account:add"), ("accounts", "accounts:0")],
                [("refresh capacity", "staff:capacity")],
                [("← manage", "nav:staff")],
            ),
        )

    async def login_link(self, message, user_id, account_id=None, state=None):
        try:
            await self._login_link(message, user_id, account_id, state)
        except PoolFullError:
            await self.capacity(message, user_id, blocked=True)

    async def _login_link(self, message, user_id, account_id=None, state=None):
        if self.r.config.login_mode == "chat":
            if not state or message.chat.type != ChatType.PRIVATE or message.chat.id != user_id:
                raise UserError("Use account sign-in only in your own private bot chat.")
            ctx = await self.r.login.begin_chat(user_id, message.chat.id, account_id)
            await state.clear()
            await state.set_state(Input.chat_signin)
            await state.update_data(login_context_id=ctx.context_id)  # Never phone/code/password.
            await self.chat_prompt(message, state, ctx)
            return
        url = await self.r.login.create_ticket(user_id, account_id)
        await message.answer(
            "<b>🔐 Sign in your own Telegram account</b>\n<blockquote>This grants your self-hosted service full access to the account session. Only use accounts you own and have authorized.\n"
            "Open the HTTPS page, compare/approve its browser code here, then enter phone → OTP → 2FA there. Never send OTP/password in bot chat.\nLink is one-use and expires in 5 minutes.\nRe-authentication keeps the old saved session until successful, authorized replacement. Canceling does not disable it.</blockquote>",
            reply_markup=keyboard([("Open secure sign-in", "url:" + url)], [("← Accounts", "accounts:0")]),
        )

    async def chat_prompt(self, message, state, ctx):
        cancel = keyboard([("Cancel sign-in", "signin:cancel:" + ctx.context_id)])
        if ctx.stage == "consent":
            await message.answer(
                "<b>🔐 Sign in your own Telegram account · private chat</b>\n"
                "<blockquote>This self-hosted service gets full access to the saved account session. Use only accounts you own and explicitly authorize.\n"
                "Bot chats are NOT end-to-end encrypted. The service operator and Telegram may access/retain chat contents; deleting messages is best effort.\n"
                "Phone/OTP/2FA stay out of application logs, MongoDB and FSM storage; your session is encrypted in MongoDB. Never forward someone else's codes.\n"
                "Telegram may expire login codes shared in chats. QR approval avoids posting a login code; it can still require 2FA. No protections are bypassed.\n"
                "This dialog expires in 10 minutes. Re-authentication keeps the old saved account until a successful replacement; canceling does not disable it. /cancel to stop.</blockquote>",
                reply_markup=keyboard(
                    [("I own it · Phone → OTP", "signin:otp:" + ctx.context_id)],
                    [("I own it · QR alternative", "signin:qr:" + ctx.context_id)],
                    [("Cancel", "signin:cancel:" + ctx.context_id)],
                ),
            )
        elif ctx.stage == "phone":
            await message.answer(
                "<b>1 / 3 · Phone number</b>\n<blockquote>Send your owned account's international phone number, e.g. +919876543210.\n"
                "You can also share your own phone contact. The input message is deleted best effort. /cancel to stop.</blockquote>",
                reply_markup=cancel,
            )
        elif ctx.stage == "code":
            await message.answer(
                "<b>2 / 3 · Telegram login code</b>\n<blockquote>Enter the latest numeric code delivered by Telegram, only for this sign-in. Do not forward the service message.\n"
                "If Telegram expires a code shared in chat, cancel and use QR; do not disguise codes to bypass protection. /cancel to stop.</blockquote>",
                reply_markup=cancel,
            )
        elif ctx.stage == "password":
            await message.answer(
                "<b>3 / 3 · Two-step verification</b>\n<blockquote>Send your account's exact 2FA password as a separate text message. Spaces and leading / are preserved.\n"
                "The message is deleted best effort and never saved by the application. Bot chats are not E2E. /cancel to stop.</blockquote>",
                reply_markup=ForceReply(force_reply=True, input_field_placeholder="2FA password; /cancel to stop"),
            )
        elif ctx.stage == "qr":
            if self.r.config.ui_edit_panels:
                await message.answer(
                    "<b>🔐 qr sign-in</b>\n<blockquote>Scan the private QR photo below with Telegram → Settings → Devices. Only approve your own sign-in. Then tap check approval. Never share this QR.</blockquote>",
                    reply_markup=keyboard(
                        [("check approval", "signin:check:" + ctx.context_id)], [("cancel sign-in", "signin:cancel:" + ctx.context_id)]
                    ),
                )
            photo = await message.answer_photo(
                BufferedInputFile(self.r.login.qr_image(ctx), filename="telegram-signin-qr.png"),
                caption="<b>🔐 Own-account QR sign-in</b>\n<blockquote>Approve ONLY a sign-in you initiated to this self-hosted service. Use your official Telegram app's Settings → Devices → Link Desktop Device, or the Telegram approval link below.\n"
                "This QR is a short-lived sign-in secret: do not share/forward it. After approval, tap Check approval. 2FA may follow.</blockquote>",
                reply_markup=keyboard(
                    [("Approve in Telegram", "url:" + ctx.qr.url)],
                    [("Check approval", "signin:check:" + ctx.context_id)],
                    [("Cancel", "signin:cancel:" + ctx.context_id)],
                ),
            )
            message_id = getattr(photo, "message_id", None)
            if isinstance(message_id, int):
                ctx.qr_message_id = message_id
        elif ctx.stage == "complete":
            account_id = ctx.completed_account
            await self.r.login.cancel_actor(ctx.actor)  # Releases dialog only; saved session is NOT revoked.
            await state.clear()
            await message.answer(
                f"<b>✅ Account saved</b>\n<blockquote>Telegram ID: <code>{html(account_id)}</code>\nEncrypted session is stored in MongoDB. Check account health below.</blockquote>",
                reply_markup=keyboard([("View account", "account:view:" + account_id)], [("Accounts", "accounts:0")]),
            )
        else:
            await self.r.login.cancel_actor(ctx.actor)
            await state.clear()
            await message.answer("Sign-in stopped. Start again from Accounts.", reply_markup=keyboard([("Accounts", "accounts:0")]))

    async def chat_input(self, message, state):
        uid = message.from_user.id
        await delete_private_input(message)
        data = await state.get_data()
        raw = message.text if message.text is not None else ""
        if raw.strip().split("@", 1)[0].lower() == "/cancel":
            await self.r.login.cancel_actor(uid)
            await state.clear()
            await message.answer(
                "Sign-in cancelled. Unstored authorized sessions are revoked best effort.",
                reply_markup=keyboard([("Accounts", "accounts:0")]),
            )
            return
        ctx = None
        try:
            if message.chat.type != ChatType.PRIVATE or message.chat.id != uid:
                raise UserError("Use your own private bot chat for sign-in.")
            ctx = await self.r.login.get_chat(uid, data.get("login_context_id"))
            if getattr(message, "forward_origin", None):
                raise UserError("Forwarded credentials are not accepted. Use only your own authorized sign-in.")
            if ctx.stage == "consent":
                raise UserError("Confirm ownership with a consent button first; do not enter a credential yet.")
            if ctx.stage == "qr":
                raise UserError("Approve the QR in Telegram, then tap Check approval; no OTP is needed for this QR step.")
            contact = getattr(message, "contact", None)
            if ctx.stage == "phone" and contact:
                if getattr(contact, "user_id", uid) != uid:
                    raise UserError("Only your own shared contact is accepted. For another account you own, type its number manually.")
                raw = "+" + contact.phone_number.lstrip("+")
            if not raw or len(raw) > 512:
                raise UserError("Send one text value (maximum 512 characters). No photos/documents are accepted as credentials.")
            await self.r.login.step(ctx, raw)
        except UserError as exc:
            terminal = not ctx or ctx.stage in ("denied", "complete")
            if terminal:
                await self.r.login.cancel_actor(uid)
                await state.clear()
            markup = (
                keyboard([("Accounts", "accounts:0")]) if terminal else keyboard([("Cancel sign-in", "signin:cancel:" + ctx.context_id)])
            )
            await message.answer("<blockquote>" + html(exc) + "</blockquote>", reply_markup=markup)
            return
        finally:
            raw = ""  # Not a guarantee of Python/Telegram memory erasure.
        await self.chat_prompt(message, state, ctx)

    async def targets(self, message, user_id, page=0):
        page = max(0, min(100, page))
        role = await self.r.access.role(user_id)
        user = await self.r.store.db.users.find_one({"_id": user_id}) or {}
        plan = normalized_plan(user.get("plan"), self.r.config)
        active = role != Role.USER or bool(plan.get("expires_at") and plan["expires_at"] > now())
        limit = self.r.config.limits.max_channels_per_user if role != Role.USER else effective_plan(plan, self.r.config)["channel_limit"]
        allowance = str(limit) if role != Role.USER else quota_label(plan, "channels")
        count = await self.r.store.db.targets.count_documents({"user_id": user_id})
        rows = (
            await self.r.store.db.targets.find({"user_id": user_id})
            .sort([("created_at", 1), ("_id", 1)])
            .skip(page * 8)
            .limit(8)
            .to_list(length=8)
        )
        buttons = [[("➕ add channel", "target:add")]] if active and count < limit else []
        lines = []
        for target in rows:
            lines.append(f"🔒 {html(target['title'][:50])} · <code>{target['chat_id']}</code>")
            if role != Role.USER:
                buttons.append([("remove " + target["title"][:30], "target:remove:" + target["_id"])])
        nav = []
        if page:
            nav.append(("← previous", f"targets:{page - 1}"))
        if (page + 1) * 8 < count:
            nav.append(("next →", f"targets:{page + 1}"))
        if nav:
            buttons.append(nav)
        buttons.extend([[self.contact_button()], [("🏠 home", "nav:home")]])
        await message.answer(
            f"<b>🔒 my saved channels</b>\nSlots · {count} / {allowance if active else 'plan expired'} (host ceiling: {self.r.config.limits.max_channels_per_user})\n<blockquote>"
            + ("\n".join(lines) or "No channels saved yet.")
            + "</blockquote>\nChannel/group choices are permanent for users. An owner/admin can make an audited correction. Get an active plan before adding a new channel.",
            reply_markup=keyboard(*buttons),
        )

    async def users(self, message, user_id, page):
        await self.r.access.require_staff(user_id)
        page = max(0, page)
        rows = await self.r.store.db.users.find({}).sort("created_at", -1).skip(page * 8).limit(8).to_list(length=8)
        lines, buttons = [], []
        for user in rows:
            plan = user.get("plan", {})
            active = plan.get("expires_at") and plan["expires_at"] > now()
            lines.append(
                f"<code>{user['_id']}</code> · {'Premium' if active else 'Free'} · {html(display_time(plan.get('expires_at'), self.r.config.timezone))}"
            )
            buttons.append([(f"Plan {user['_id']}", f"plan:edit:{user['_id']}"), ("Revoke…", f"plan:revoke:{user['_id']}")])
        if page:
            buttons.append([("← Previous", f"users:{page - 1}")])
        if len(rows) == 8:
            buttons.append([("Next →", f"users:{page + 1}")])
        buttons.append([("⚙️ manage", "nav:staff")])
        await message.answer(
            "<b>👥 users</b>\n<blockquote>" + ("\n".join(lines) or "No users.") + "</blockquote>", reply_markup=keyboard(*buttons)
        )

    async def jobs(self, message, user_id, scope, page):
        if scope == "all":
            await self.r.access.require_staff(user_id)
        elif scope != "mine":
            raise UserError("Invalid jobs view.")
        query = {} if scope == "all" else {"user_id": user_id}
        page = max(0, page)
        jobs = await self.r.store.db.jobs.find(query).sort("created_at", -1).skip(page * 6).limit(6).to_list(length=6)
        buttons, lines = [], []
        for job in jobs:
            lines.append(
                f"<code>{job['_id']}</code> · {html(job['kind'])} · {html(job['status'])}\n{html(job['target_title'][:64])} · {html(display_time(job['original_run_at'], self.r.config.timezone))}\n{html(job_summary(job))}"
            )
            buttons.append([("Details " + job["_id"], "job:view:" + job["_id"])])
        if page:
            buttons.append([("← Previous", f"jobs:{scope}:{page - 1}")])
        if len(jobs) == 6:
            buttons.append([("Next →", f"jobs:{scope}:{page + 1}")])
        buttons.append([("🏠 Home", "nav:home")])
        await message.answer(
            "<b>🗓 Jobs & schedules</b>\n<blockquote>" + ("\n\n".join(lines) or "No jobs yet.") + "</blockquote>",
            reply_markup=keyboard(*buttons),
        )

    async def job(self, message, user_id, job_id):
        job = await self.r.store.db.jobs.find_one({"_id": job_id})
        if not job or (job["user_id"] != user_id and await self.r.access.role(user_id) == Role.USER):
            raise UserError("Job unavailable.")
        rows = []
        if job["status"] in ("queued", "running"):
            rows.append([("Cancel this job", "job:cancel:" + job_id)])
        rows.append([("Refresh", "job:view:" + job_id), ("My jobs", "jobs:mine:0")])
        text = f"<b>Job <code>{job_id}</code></b>\n<blockquote>Type: {html(job['kind'])}\nStatus: {html(job['status'])}\nTarget: {html(job['target_title'][:64])}\nAccounts: {job['account_count']}\nStart: {html(display_time(job['original_run_at'], self.r.config.timezone))}\nEnd cap: {html(display_time(job.get('end_at'), self.r.config.timezone))}\n{html(job_summary(job))}\n{html(job.get('reason', ''))}</blockquote>"
        results = job.get("results", [])
        overview = error_overview(results)
        if overview:
            text += "\n<b>error types</b>\n<pre>" + html(overview[:650]) + "</pre>"
        if await self.r.access.role(user_id) != Role.USER:
            failures = [
                row
                for row in results
                if row.get("error_type") or row.get("last_error_type") or row["status"] in {"request_sent", "awaiting_approval"}
            ]
            details = []
            for result in (failures or results)[:8]:
                details.append(
                    f"<code>{html(result['account_id'])}</code> · {html(result['status'])}"
                    + (
                        f" · <code>{html(result.get('error_type') or result.get('last_error_type'))}</code>"
                        if result.get("error_type") or result.get("last_error_type")
                        else ""
                    )
                    + "\n"
                    + html(result_explanation(result))
                )
            text += "\n<blockquote>" + ("\n\n".join(details) or "No account results yet.") + "</blockquote>"
            if len(results) > 8:
                text += "\nShowing up to 8 priority results; error counts cover all accounts."
        await message.answer(text, reply_markup=keyboard(*rows))

    async def begin_job(self, message, user_id, kind, state):
        await self.r.access.entitlement(user_id, kind=kind)
        if kind == "call" and not self.r.config.calls_enabled:
            raise UserError("Calls are disabled on this host.")
        if not await self.r.store.db.targets.count_documents({"user_id": user_id}):
            raise UserError("Add your channel in my channels first.")
        await state.clear()
        await state.update_data(kind=kind, draft_created=now(), draft_key=secrets.token_hex(12))
        await self.choose_targets(message, user_id, kind, state)

    async def choose_targets(self, message, user_id, kind, state, page=0):
        data = await self.draft(state)
        if data["kind"] != kind:
            raise UserError("This task form is old. Start again.")
        await self.r.access.entitlement(user_id, kind=kind)
        page = max(0, min(100, page))
        targets = (
            await self.r.store.db.targets.find({"user_id": user_id})
            .sort([("created_at", 1), ("_id", 1)])
            .skip(page * 8)
            .limit(8)
            .to_list(length=8)
        )
        total = await self.r.store.db.targets.count_documents({"user_id": user_id})
        buttons = [[(t["title"][:50], f"choose:{kind}:{t['_id']}")] for t in targets]
        nav = []
        if page:
            nav.append(("← previous", f"choices:{kind}:{page - 1}"))
        if (page + 1) * 8 < total:
            nav.append(("next →", f"choices:{kind}:{page + 1}"))
        if nav:
            buttons.append(nav)
        buttons.append([("cancel", "nav:home")])
        await message.answer("<b>choose your saved channel/group</b>", reply_markup=keyboard(*buttons))

    async def draft(self, state):
        data = await state.get_data()
        if not data.get("draft_created") or data["draft_created"] < now() - timedelta(minutes=15):
            await state.clear()
            raise UserError("Job form expired. Start again from Home.")
        return data

    async def count_prompt(self, message, user_id, state):
        data = await self.draft(state)
        entitlement = await self.r.access.entitlement(user_id, kind=data["kind"])
        healthy = await self.r.store.db.accounts.count_documents({"enabled": True, "status": "healthy"})
        cap = min(entitlement["max_accounts"], healthy, self.r.config.limits.max_pool_accounts)
        if not cap:
            raise UserError("No ready accounts yet. Ask an owner or admin to add an account or sign in again.")
        await state.set_state(Input.count)
        values = sorted({1, min(3, cap), cap})
        await message.answer(
            f"<b>how many accounts?</b>\n<blockquote>Up to {cap} accounts are ready. If they are busy, your task waits.</blockquote>\nSend a number or choose below:",
            reply_markup=keyboard([(str(n), f"count:{n}") for n in values], [("Cancel", "nav:home")]),
        )

    async def set_count(self, message, user_id, state, value):
        data = await self.draft(state)
        entitlement = await self.r.access.entitlement(user_id, kind=data["kind"])
        if not 1 <= value <= entitlement["max_accounts"]:
            raise account_capacity_error(entitlement)
        await state.update_data(count=value)
        if data["kind"] == "call":
            await state.set_state(Input.duration)
            cap = self.r.config.limits.max_call_minutes
            values = sorted({min(30, cap), min(60, cap), cap})
            await message.answer(
                f"<b>How long should we stay?</b>\n<blockquote>Stay until the call ends, but at most the selected minutes (and never past Premium expiry). Max {cap} minutes. Mic/camera off.</blockquote>\nType minutes or choose:",
                reply_markup=keyboard([(f"{n} min", f"duration:{n}") for n in values], [("Cancel", "nav:home")]),
            )
        else:
            await self.schedule_prompt(message, state)

    async def schedule_prompt(self, message, state):
        await state.set_state(Input.schedule)
        await message.answer(
            f"<b>When should this run?</b>\n<blockquote>Timezone: {html(self.r.config.timezone)}. Queues and Telegram limits may delay the exact start.</blockquote>",
            reply_markup=keyboard([("Run now", "schedule:now"), ("Schedule…", "schedule:later")], [("Cancel", "nav:home")]),
        )

    async def confirm(self, message, user_id, state, run_at):
        data = await self.draft(state)
        target = await self.r.targets.get(user_id, data["target_id"])
        await self.r.access.entitlement(user_id, at=run_at, kind=data["kind"])
        await state.update_data(run_at=run_at)
        await state.set_state(Input.confirm)
        await message.answer(
            f"<b>review your task</b>\n<blockquote>Type: {html(data['kind'])}\nTarget: {html(target['title'][:64])}\nAccounts: {data['count']}\nStart: {html(display_time(run_at, self.r.config.timezone))}\n"
            f"Call cap: {data.get('minutes', '—')} minutes\nOnly owner/admin-authorized pool accounts will be used.\nJoin requests require target-admin approval. No guaranteed membership or call attendance.</blockquote>",
            reply_markup=keyboard([("✅ confirm task", "job:confirm")], [("Cancel", "nav:home")]),
        )

    async def stats(self, message, user_id):
        await self.r.access.require_staff(user_id)
        users = await self.r.store.db.users.count_documents({})
        premium = await self.r.store.db.users.count_documents({"plan.expires_at": {"$gt": now()}})
        accounts = await self.r.store.db.accounts.count_documents({})
        active = await self.r.store.db.jobs.count_documents({"status": {"$in": ["queued", "running"]}})
        failed = await self.r.store.db.outbox.count_documents({"status": "failed"})
        await message.answer(
            f"<b>📊 Service statistics</b>\n<blockquote>Users: {users}\nActive Premium: {premium}\nAccounts: {accounts}\nAvailable now: {len(await self.r.pool.available())}\nQueued/running jobs: {active}\nFailed notifications: {failed}\nMaintenance: {await self.r.store.setting('maintenance', False)}</blockquote>",
            reply_markup=keyboard([("⚙️ manage", "nav:staff")]),
        )

    async def audit(self, message, user_id):
        await self.r.access.require_staff(user_id, owner_only=True)
        rows = await self.r.store.db.audit.find({}).sort("created_at", -1).limit(12).to_list(length=12)
        entries = []
        for row in rows:
            details = json.dumps(row.get("details", {}), default=str, ensure_ascii=True)
            if len(details) > 220:
                details = details[:220] + "…"
            entries.append(
                f"{html(display_time(row['created_at'], self.r.config.timezone))} · <code>{row['actor']}</code> · <code>{html(row['action'])}</code>\n<pre>{html(details)}</pre>"
            )
        await message.answer(
            "<b>recent audit events</b>\n" + ("\n".join(entries[:10]) or "<blockquote>No events.</blockquote>"),
            reply_markup=keyboard([("⚙️ manage", "nav:staff")]),
        )

    async def grant_input(self, message, user_id, text, target=None):
        await self.r.access.require_staff(user_id)
        parts = [part.lower() for part in text.split()]
        features, channels = None, None
        try:
            if target is None:
                target = int(parts.pop(0))
            days = int(parts.pop(0))
            if parts and parts[0] in FEATURE_PLANS:
                features = parts.pop(0)
                channels = parts.pop(0)
            cap = parts.pop(0) if parts and (parts[0].isascii() and parts[0].isdigit() or parts[0] == UNLIMITED) else None
            mode = parts.pop(0) if parts else "set"
            if parts:
                raise ValueError
        except (ValueError, IndexError):
            raise UserError("Use /premiumhelp for the format and examples, or use give premium buttons.") from None
        expires = await self.r.plans.grant(user_id, target, days, cap, mode, features, channels)
        user = await self.r.store.db.users.find_one({"_id": target})
        plan = user["plan"]
        await message.answer(
            f"<b>premium saved</b>\n<blockquote>User · <code>{target}</code>\nFeatures · {html(feature_label(plan['feature_plan']))}\nLocked channels · {quota_label(plan, 'channels')}\nAccounts per task · {quota_label(plan, 'accounts')}\nUntil · {html(display_time(expires, self.r.config.timezone))}</blockquote>\nOwner/user notices are queued.",
            reply_markup=keyboard([("← manage", "nav:staff")]),
        )

    def health_text(self, report):
        title = {
            "running": "checking health…",
            "complete": "health check finished",
            "partial": "health check partly finished",
            "failed": "health check failed",
            "stopped": "health check stopped",
        }[report["status"]]
        lines = [f"{html(name)} · {html(value)}" for name, value in report["components"].items()]
        accounts = report["accounts"][-12:]
        text = f"<b>🩺 {title}</b>\n<blockquote>" + ("\n".join(lines) or "Starting database and Bot API checks…") + "</blockquote>\n"
        text += f"\nAccounts reviewed · {report['checked']} / {report['total'] if report['total'] is not None else 'reading'}\n"
        text += (
            "<blockquote>"
            + (
                "\n".join(f"<code>{row['account_id']}</code> · {html(row['status'])} · {html(row['check'])}" for row in accounts)
                or "No account results yet."
            )
            + "</blockquote>\n"
        )
        if report.get("error_type"):
            text += "Error type · <code>" + html(report["error_type"]) + "</code>\n"
        text += "Busy accounts skip full identity probes; one existing managed call may be observed read-only. Disabled/cooldown accounts stay protected. Installed adapter alone is not a live-call pass. Refresh if updates pause."
        return text, keyboard([("refresh results", "staff:health_refresh"), ("run check", "staff:health")], [("← manage", "nav:staff")])

    async def health(self, message, user_id, start=True):
        await self.r.access.require_staff(user_id)
        report = await self.r.health.start(user_id) if start or not self.r.health.state else self.r.health.snapshot()
        text, markup = self.health_text(report)
        if not self.r.config.ui_edit_panels:
            await message.answer(text, reply_markup=markup)
            return
        anchor = getattr(message, "raw", message)
        view = "health:" + report["run_id"]
        await self.ui.render(anchor, user_id, text, reply_markup=markup, view_key=view)
        if report["status"] == "running":

            async def update(state):
                await self.r.access.require_staff(user_id)
                body, controls = self.health_text(state)
                result = await self.ui.render(anchor, user_id, body, reply_markup=controls, view_key=view, expected_view=view)
                return bool(result and state["status"] == "running")

            self.r.health.watch(user_id, update)
            # A zero-account scan may finish before watcher registration.
            latest = self.r.health.snapshot()
            if not await update(latest):
                self.r.health.watchers.pop(user_id, None)

    async def on_callback(self, q: CallbackQuery, state: FSMContext, callback_acknowledged=False):
        if not callback_acknowledged:
            with suppress(TelegramBadRequest, TelegramRetryAfter):
                await q.answer()  # Direct/test invocation; normal routing was acknowledged by Guard.
        async with self.ui.actions.get(q.from_user.id):
            await self._on_callback(q, state)

    async def _on_callback(self, q: CallbackQuery, state: FSMContext):
        message, uid, parts = self.ui.wrap(q.message, q.from_user.id), q.from_user.id, (q.data or "").split(":")
        action = parts[0]
        if uid in self.r.login.chat_contexts and action != "signin":
            await self.r.login.cancel_actor(uid)
            await state.clear()
        if action == "sg":
            await self.session_safety_callback(message, uid, parts, state)
        elif action == "signin":
            if len(parts) != 3 or message.chat.type != ChatType.PRIVATE or message.chat.id != uid:
                raise UserError("Invalid/private sign-in button.")
            ctx = await self.r.login.get_chat(uid, parts[2])
            if parts[1] == "cancel":
                await self.r.login.cancel_actor(uid)
                await state.clear()
                with suppress(TelegramBadRequest):
                    await message.edit_reply_markup(reply_markup=None)
                await message.answer("Sign-in cancelled.", reply_markup=keyboard([("Accounts", "accounts:0")]))
                return
            try:
                if parts[1] in ("otp", "qr"):
                    ctx = await self.r.login.confirm_chat(uid, parts[2], parts[1])
                    with suppress(TelegramBadRequest):
                        await message.edit_reply_markup(reply_markup=None)
                elif parts[1] == "check":
                    await self.r.login.check_qr(uid, parts[2])
                    with suppress(TelegramBadRequest):
                        await message.edit_reply_markup(reply_markup=None)
                else:
                    raise UserError("Unknown sign-in operation.")
            except PoolFullError:
                await self.r.login.cancel_actor(uid)
                await state.clear()
                await self.capacity(message, uid, blocked=True)
                return
            except UserError as exc:
                terminal = ctx.stage in ("denied", "complete")
                if terminal:
                    await self.r.login.cancel_actor(uid)
                    await state.clear()
                await message.answer(
                    "<blockquote>" + html(exc) + "</blockquote>",
                    reply_markup=keyboard([("Accounts", "accounts:0")])
                    if terminal
                    else keyboard([("Check approval", "signin:check:" + ctx.context_id), ("Cancel", "signin:cancel:" + ctx.context_id)])
                    if ctx.stage == "qr"
                    else keyboard([("Cancel", "signin:cancel:" + ctx.context_id)]),
                )
                return
            await self.chat_prompt(message, state, ctx)
        elif action in {"fs", "auto"}:
            await self.automation_callback(message, uid, parts, state)
        elif action == "nav":
            await state.clear()
            if parts[1] == "home":
                await self.home(message, uid)
            elif parts[1] == "plan":
                await self.plan(message, uid)
            elif parts[1] == "staff":
                await self.staff(message, uid)
            elif parts[1] == "help":
                await self.help(message)
            elif parts[1] == "rules":
                await self.rules(message)
        elif action == "login":
            await self.r.login.approve(uid, parts[2], parts[1] == "yes")
            await message.edit_reply_markup(reply_markup=None)
            await message.answer("Browser approved. Continue on your HTTPS page." if parts[1] == "yes" else "Login denied.")
        elif action == "accounts":
            await self.accounts(message, uid, int(parts[1]))
        elif action == "account":
            await self.r.access.require_staff(uid)
            operation = parts[1]
            if operation == "add":
                await self.login_link(message, uid, state=state)
            elif operation == "view":
                await self.account(message, uid, parts[2])
            elif operation == "reauth":
                await self.login_link(message, uid, parts[2], state=state)
            elif operation == "recover":
                await self.r.pool.request_recovery(uid, parts[2])
                await self.account(message, uid, parts[2])
            elif operation == "toggle":
                row = await self.r.store.db.accounts.find_one({"_id": parts[2]})
                if not row:
                    raise UserError("Account not found.")
                await self.r.pool.toggle(uid, parts[2], not row["enabled"])
                await self.account(message, uid, parts[2])
            elif operation == "remove":
                row = await self.r.store.db.accounts.find_one({"_id": parts[2]})
                if not row:
                    raise UserError("Account not found.")
                await self.r.access.can_manage_account(uid, row)
                await message.answer(
                    "<b>Remove account?</b>\n<blockquote>Local removal deletes the encrypted session here but does not revoke it in Telegram. Revoke + remove also logs out the currently connected session. You can always revoke in Telegram Settings → Devices.</blockquote>",
                    reply_markup=keyboard(
                        [("Local removal", "account:delete:" + parts[2]), ("Revoke + remove", "account:logout:" + parts[2])],
                        [("Cancel", "account:view:" + parts[2])],
                    ),
                )
            elif operation in ("delete", "logout"):
                await self.r.pool.remove(uid, parts[2], logout=operation == "logout")
                await self.accounts(message, uid, 0)
        elif action == "targets":
            await self.targets(message, uid, int(parts[1]))
        elif action == "target":
            if parts[1] == "add":
                entitlement = await self.r.access.entitlement(uid)
                if await self.r.store.db.targets.count_documents({"user_id": uid}) >= entitlement["channel_limit"]:
                    raise channel_capacity_error(entitlement, self.r.config)
                await state.clear()
                await state.set_state(Input.target)
                await message.answer(
                    "<b>add a channel or group</b>\n<blockquote>Add this bot as an admin and allow invites. Then send the channel's @username or chat ID. Use <code>/chatid</code> there to find the ID.</blockquote>",
                    reply_markup=HOME,
                )
            elif parts[1] == "remove":
                await self.r.access.require_staff(uid)
                await self.r.targets.get(uid, parts[2])
                await message.answer(
                    "Remove target and revoke its managed links?",
                    reply_markup=keyboard([("Confirm removal", "target:delete:" + parts[2])], [("Cancel", "targets:0")]),
                )
            elif parts[1] == "delete":
                await self.r.targets.remove(uid, parts[2])
                await self.targets(message, uid)
        elif action == "users":
            await self.users(message, uid, int(parts[1]))
        elif action == "plan":
            await self.r.access.require_staff(uid)
            target = int(parts[2])
            if parts[1] == "edit":
                await self.plan_setup(message, uid, state, target)
            elif parts[1] == "revoke":
                await message.answer(
                    f"Revoke Premium for <code>{target}</code> and cancel its jobs?",
                    reply_markup=keyboard([("Confirm revoke", f"plan:revoked:{target}")], [("Cancel", "users:0")]),
                )
            elif parts[1] == "revoked":
                await self.r.plans.revoke(uid, target)
                await message.answer("Plan revoked; notifications queued.", reply_markup=HOME)
        elif action == "grant":
            await self.grant_callback(message, uid, state, parts)
        elif action == "tfix":
            await self.correction_callback(message, uid, state, parts)
        elif action == "contact":
            username = self.r.config.admin_username or self.r.config.support_username
            await message.answer(
                "<b>contact admin</b>\n"
                + (
                    f"Message @{html(username)} for plans, payment and channel corrections."
                    if username
                    else "The admin contact is not set yet. Ask the bot owner to set ADMIN_USERNAME in the service environment."
                ),
                reply_markup=keyboard([self.contact_button()] if username else [("home", "nav:home")]),
            )
        elif action == "jobs":
            await self.jobs(message, uid, parts[1], int(parts[2]))
        elif action == "job":
            if parts[1] == "confirm":
                if await state.get_state() != Input.confirm.state:
                    raise UserError("This screen is old. Open home and start again.")
                data = await self.draft(state)
                job_id = await self.r.jobs.create(
                    uid,
                    data["kind"],
                    data["target_id"],
                    data["link"],
                    data["count"],
                    now() if data.get("immediate") else data["run_at"],
                    data.get("minutes"),
                    request_key=data.get("draft_key"),
                )
                await state.clear()
                await self.job(message, uid, job_id)
            elif parts[1] == "view":
                await self.job(message, uid, parts[2])
            elif parts[1] == "cancel":
                await self.r.jobs.cancel(uid, parts[2])
                await message.answer("Task stopping. Accounts will leave at the next safe check.", reply_markup=HOME)
        elif action == "new":
            await self.begin_job(message, uid, parts[1], state)
        elif action == "choices":
            await self.choose_targets(message, uid, parts[1], state, int(parts[2]))
        elif action == "choose":
            data = await self.draft(state)
            if data["kind"] != parts[1]:
                raise UserError("Wrong job form. Start again.")
            await self.r.access.entitlement(uid, kind=data["kind"])
            await self.r.targets.get(uid, parts[2], recheck=True)
            await state.update_data(target_id=parts[2])
            await state.set_state(Input.link)
            await message.answer(
                "<b>choose the saved target</b>\n<blockquote>Channel tasks directly join a current public @username; private targets use this bot's request invite. Calls use the saved call invite. You can also send the selected target's own public link.</blockquote>",
                reply_markup=keyboard([("use saved target", "link:managed")], [("Cancel", "nav:home")]),
            )
        elif action == "link":
            if await state.get_state() != Input.link.state:
                raise UserError("Link form unavailable.")
            data = await self.draft(state)
            target = await self.r.targets.get(uid, data["target_id"])
            if data["kind"] == "join":
                route = await self.r.targets.join_link(target)
                link = "https://t.me/" + route.value if route.kind == "public" else target["request_link"]
            else:
                link = target["call_link"]
            await state.update_data(link=link)
            await self.count_prompt(message, uid, state)
        elif action == "count":
            if await state.get_state() != Input.count.state:
                raise UserError("Count form unavailable.")
            await self.set_count(message, uid, state, int(parts[1]))
        elif action == "duration":
            if await state.get_state() != Input.duration.state:
                raise UserError("Duration form unavailable.")
            minutes = int(parts[1])
            if not 5 <= minutes <= self.r.config.limits.max_call_minutes:
                raise UserError("Invalid call duration.")
            await state.update_data(minutes=minutes)
            await self.schedule_prompt(message, state)
        elif action == "schedule":
            if await state.get_state() != Input.schedule.state:
                raise UserError("Schedule form unavailable.")
            await state.update_data(immediate=parts[1] == "now")
            if parts[1] == "now":
                await self.confirm(message, uid, state, now())
            else:
                await message.answer(
                    f"Send <code>YYYY-MM-DD HH:MM</code> in {html(self.r.config.timezone)}, e.g. <code>{(now() + timedelta(days=1)).astimezone(__import__('zoneinfo').ZoneInfo(self.r.config.timezone)).strftime('%Y-%m-%d %H:%M')}</code>."
                )
        elif action in ("staff", "owner"):
            operation = parts[1]
            if action == "staff" and operation not in {
                "grant",
                "revoke",
                "stats",
                "health",
                "health_refresh",
                "channels",
                "premium_help",
                "auto_overview",
                "capacity",
            }:
                raise UserError("Owner-only action.")
            await self.r.access.require_staff(uid, owner_only=action == "owner")
            mapping = {
                "revoke": Input.revoke,
                "add_admin": Input.add_admin,
                "remove_admin": Input.remove_admin,
            }
            if operation == "capacity":
                await self.capacity(message, uid)
            elif operation == "grant":
                await self.plan_setup(message, uid, state)
            elif operation == "premium_help":
                await state.clear()
                await self.premium_help(message, uid)
            elif operation == "channels":
                await state.clear()
                await state.set_state(Input.correction_user)
                await message.answer(
                    "<b>channel corrections</b>\nSend the customer's numeric user ID. Staff changes need a reason and confirmation.",
                    reply_markup=keyboard([("cancel", "nav:staff")]),
                )
            elif operation in {"photo", "photo_on", "photo_off", "photo_preview", "photo_reset", "banner"}:
                await self.photo_action(message, uid, operation, state)
            elif operation in mapping:
                await state.clear()
                await state.set_state(mapping[operation])
                prompt = (
                    "Send a photo (not a URL). It will replace the /start image. /resetphoto restores the supplied default."
                    if operation == "banner"
                    else "Send the target Telegram user ID. /cancel to stop."
                )
                await message.answer(prompt)
            elif operation == "auto_overview":
                await state.clear()
                await self.auto_overview(message, uid)
            elif operation == "stats":
                await self.stats(message, uid)
            elif operation in ("health", "health_refresh"):
                await self.health(message, uid, start=operation == "health")
            elif operation == "audit":
                await self.audit(message, uid)
            elif operation == "admins":
                admins = await self.r.store.db.admins.find({}).to_list(length=100)
                await message.answer(
                    "<b>Owner IDs</b>\n"
                    + html(", ".join(map(str, self.r.config.owner_ids)))
                    + "\n<b>Admin IDs</b>\n"
                    + html(", ".join(str(a["_id"]) for a in admins) or "None"),
                    reply_markup=HOME,
                )
            elif operation == "maintenance":
                enabled = not await self.r.store.setting("maintenance", False)
                await self.r.store.set_setting("maintenance", enabled)
                await self.r.store.audit(uid, "maintenance", enabled=enabled)
                await message.answer(
                    f"Maintenance: {enabled}. New/queued jobs pause; manual calls stay bounded and automatic calls leave/pause.",
                    reply_markup=HOME,
                )
            elif operation == "updates":
                report = await self.r.compat.check(notify=False)
                await message.answer(
                    "<b>Compatibility / updates</b>\n<blockquote>"
                    + html(report[:3400])
                    + "</blockquote>\nUpdates are alerts only, never auto-installed into live sessions.",
                    reply_markup=HOME,
                )
        else:
            raise UserError("This button is old. Open /start for the current menu.")

    async def on_message(self, message: Message, state: FSMContext):
        async with self.ui.actions.get(message.from_user.id):
            await self._on_message(message, state)

    async def _on_message(self, message: Message, state: FSMContext):
        message = self.ui.wrap(message, message.from_user.id)
        if await state.get_state() == Input.chat_signin.state:
            ctx = self.r.login.chat_contexts.get(message.from_user.id)
            command = (message.text or "").strip().split("@", 1)[0].lower()
            # Escape hatch: diagnostics/help/cancel must not be swallowed as OTP/2FA input.
            if command in {"/diag", "/help", "/id", "/chatid", "/cancel"}:
                await self.r.login.cancel_actor(message.from_user.id)
                await state.clear()
            elif command in {"/start", "/panel"} and (not ctx or ctx.stage != "password"):
                await self.r.login.cancel_actor(message.from_user.id)
                await state.clear()
            else:
                await self.chat_input(message, state)
                return  # Exact slash-prefixed 2FA passwords are still NOT staff commands.
        uid, text = message.from_user.id, (message.text or "").strip()
        if text.startswith("/"):
            pieces = text.split(maxsplit=1)
            command = pieces[0].split("@")[0].lower()
            args = pieces[1] if len(pieces) > 1 else ""
            if command in ("/start", "/panel", "/cancel"):
                await state.clear()
                await self.home(message, uid, with_image=command == "/start")
                return
            if command == "/auto":
                await state.clear()
                await self.auto_home(message, uid)
                return
            if command == "/autostop":
                ids = [row["_id"] for row in await self.r.store.db.targets.find({"user_id": uid}).to_list(length=100)]
                if ids:
                    await self.r.auto_calls.set_enabled(uid, ids, False)
                await state.clear()
                await self.auto_home(message, uid)
                return
            if command == "/help":
                await self.help(message)
                return
            if command in ("/id", "/chatid"):
                await message.answer(f"User ID: <code>{uid}</code>\nChat ID: <code>{message.chat.id}</code>")
                return
            if command == "/diag":
                # Always answer; never hang behind staff-only routing or a slow pool query.
                try:
                    role = await self.r.access.role(uid)
                    if role == Role.USER:
                        await message.answer(
                            "<blockquote>Owner/admin access required for /diag. Your user ID: "
                            f"<code>{uid}</code></blockquote>"
                        )
                        return
                    saved = await self.r.store.db.accounts.count_documents({})
                    enabled = await self.r.store.db.accounts.count_documents({"enabled": True})
                    healthy_db = await self.r.store.db.accounts.count_documents({"enabled": True, "status": "healthy"})
                    connected = sum(1 for slot in self.r.pool.slots.values() if not slot.disconnected and not slot.closing)
                    free = sum(
                        1
                        for slot in self.r.pool.slots.values()
                        if not slot.disconnected and not slot.closing and not slot.busy_job
                    )
                    auto_targets = await self.r.store.db.targets.count_documents({"auto_call.enabled": True})
                    assigned = sum(len(accounts) for accounts in self.r.auto_calls.assignments.values())
                    maintenance = await self.r.store.setting("maintenance", False)
                    safety = "paused" if self.r.pool.safety.paused else "ok"
                    cycle = self.r.auto_calls.last_cycle_at
                    cycle_text = cycle.isoformat() if hasattr(cycle, "isoformat") else str(cycle or "never")
                    await message.answer(
                        "<b>runtime diagnostics</b>\n"
                        f"<blockquote>ready · {self.r.ready}\n"
                        f"leader · {getattr(self.r, 'leader', False)}\n"
                        f"pool_loading · {getattr(self.r, 'pool_loading', False)}\n"
                        f"maintenance · {maintenance}\n"
                        f"calls_enabled · {self.r.config.calls_enabled}\n"
                        f"auto_calls_enabled · {self.r.config.auto_calls_enabled}\n"
                        f"session_safety · {html(safety)}\n"
                        f"accounts saved/enabled/healthy_db/connected/free · "
                        f"{saved}/{enabled}/{healthy_db}/{connected}/{free}\n"
                        f"auto targets enabled · {auto_targets}\n"
                        f"auto sessions assigned · {assigned}\n"
                        f"last auto cycle · {html(cycle_text)}\n"
                        f"last auto error · {html(self.r.auto_calls.last_error_type or 'none')}</blockquote>\n"
                        "If free=0 while connected&gt;0: accounts are busy on jobs/calls.\n"
                        "If healthy_db&gt;connected: wait for pool finish or /health.\n"
                        "InviteHashExpiredError: refresh the invite link on that target."
                    )
                except Exception as exc:
                    logger.exception("diag failed; error=%s", type(exc).__name__)
                    await message.answer(f"<blockquote>diag error: {html(type(exc).__name__)}</blockquote>")
                return
            if command == "/plan":
                await self.plan(message, uid)
                return
            if command == "/targets":
                await state.clear()
                await self.targets(message, uid)
                return
            if command == "/jobs":
                await self.jobs(message, uid, "mine", 0)
                return
            await self.r.access.require_staff(uid)
            if command == "/forcesub":
                await state.clear()
                await self.force_list(message, uid)
                return
            if command in ("/login", "/signin"):
                await self.login_link(message, uid, state=state)
                return
            if command == "/premium":
                await self.grant_input(message, uid, args)
                return
            if command == "/revoke":
                if not args.isdigit():
                    raise UserError("Use /revoke USER_ID.")
                await self.r.plans.revoke(uid, int(args))
                await message.answer("Premium revoked; jobs cancelled and notifications queued.")
                return
            if command == "/accounts":
                await self.accounts(message, uid, 0)
                return
            if command == "/users":
                await self.users(message, uid, 0)
                return
            if command == "/stats":
                await self.stats(message, uid)
                return
            if command == "/premiumhelp":
                await state.clear()
                await self.premium_help(message, uid)
                return
            if command == "/sessionguard":
                await state.clear()
                await self.session_safety(message, uid, state)
                return
            if command == "/health":
                await self.health(message, uid)
                return
            await self.r.access.require_staff(uid, owner_only=True)
            if command == "/forcesubadd":
                if args:
                    await self.force_add_review(message, uid, state, args)
                else:
                    await self.force_add_prompt(message, uid, state)
                return
            if command == "/forcesubremove":
                if not args.lstrip("-").isdigit():
                    raise UserError("Use /forcesubremove CHAT_ID; review before confirming.")
                await self.automation_callback(message, uid, ["fs", "remove", args], state)
                return
            if command in ("/addadmin", "/deladmin"):
                if not args.isdigit():
                    raise UserError(f"Use {command} USER_ID.")
                await (self.r.access.add_admin(uid, int(args)) if command == "/addadmin" else self.r.access.remove_admin(uid, int(args)))
                await message.answer("Admin role updated.")
                return
            if command == "/setphoto":
                await self.photo_prompt(message, uid, state)
                return
            if command == "/startphoto":
                if args not in {"", "on", "off"}:
                    raise UserError("Use /startphoto, /startphoto on or /startphoto off.")
                await self.photo_action(message, uid, "photo_" + args if args else "photo", state)
                return
            if command == "/resetphoto":
                await self.photo_action(message, uid, "photo_reset", state)
                return
            if command == "/audit":
                await self.audit(message, uid)
                return
            if command == "/maintenance":
                if args not in ("on", "off"):
                    raise UserError("Use /maintenance followed by the plain word on or off.")
                await self.r.store.set_setting("maintenance", args == "on")
                await self.r.store.audit(uid, "maintenance", enabled=args == "on")
                await message.answer(f"Maintenance {args}.")
                return
            if command == "/updates":
                await message.answer("<blockquote>" + html((await self.r.compat.check(notify=False))[:3400]) + "</blockquote>")
                return
            raise UserError("Unknown command. Use /help.")
        if await self.automation_message(message, uid, state, text):
            return
        if await self.grant_message(message, uid, state, text):
            return
        if await self.correction_message(message, uid, state, text):
            return
        current = await state.get_state()
        data = await state.get_data()
        if current == Input.target.state:
            await self.r.targets.register(uid, text)
            await state.clear()
            await self.targets(message, uid)
        elif current == Input.link.state:
            data = await self.draft(state)
            target = await self.r.targets.get(uid, data["target_id"])
            await self.r.targets.validate_link(target, text)
            await state.update_data(link=text)
            await self.count_prompt(message, uid, state)
        elif current == Input.count.state:
            if not text.isdigit():
                raise UserError("Send a positive account count.")
            await self.set_count(message, uid, state, int(text))
        elif current == Input.duration.state:
            await self.draft(state)
            if not text.isdigit() or not 5 <= int(text) <= self.r.config.limits.max_call_minutes:
                raise UserError("Send a permitted duration in minutes.")
            await state.update_data(minutes=int(text))
            await self.schedule_prompt(message, state)
        elif current == Input.schedule.state:
            await state.update_data(immediate=False)
            await self.confirm(message, uid, state, parse_schedule(text, self.r.config.timezone))
        elif current == Input.grant.state:
            await self.grant_input(message, uid, text, data.get("plan_target"))
            await state.clear()
        elif current == Input.revoke.state:
            if not text.isdigit():
                raise UserError("Send USER_ID.")
            await self.r.plans.revoke(uid, int(text))
            await state.clear()
            await message.answer("Premium revoked; notifications queued.", reply_markup=HOME)
        elif current in (Input.add_admin.state, Input.remove_admin.state):
            if not text.isdigit():
                raise UserError("Send USER_ID.")
            await (
                self.r.access.add_admin(uid, int(text)) if current == Input.add_admin.state else self.r.access.remove_admin(uid, int(text))
            )
            await state.clear()
            await message.answer("Admin role updated.", reply_markup=HOME)
        elif current == Input.banner.state:
            await self.accept_photo(message, uid, state)
        else:
            await message.answer(
                "Open /start and choose a button. Enter login details only during your own active account sign-in.",
                reply_markup=HOME,
            )
