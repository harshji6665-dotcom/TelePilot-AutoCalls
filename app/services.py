import asyncio
import secrets
from hashlib import sha256

from .plans import normalized_plan, effective_plan, feature_allowed, FEATURE_PLANS, UNLIMITED, quota_choice, channel_capacity_error

from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest

from .links import parse_link
from .security import Role, UserError
from .timeutils import now, plan_expiry
from .ui import KeyedLocks
from contextlib import suppress


class Access:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.target_locks = KeyedLocks()
        self.force_subs = None
        self.auto_wakeup = None

    async def role(self, user_id: int) -> Role:
        if user_id in self.config.owner_ids:
            return Role.OWNER
        if await self.store.db.admins.find_one({"_id": user_id}):
            return Role.ADMIN
        return Role.USER

    async def require_staff(self, user_id: int, owner_only=False):
        role = await self.role(user_id)
        if role == Role.USER or (owner_only and role != Role.OWNER):
            raise UserError("Owner-only action." if owner_only else "Owner/admin access required.")
        return role

    async def can_manage_account(self, user_id, account):
        role = await self.require_staff(user_id)
        if role != Role.OWNER and account["added_by"] != user_id:
            raise UserError("Admins can manage only accounts they personally added.")

    async def entitlement(self, user_id: int, at=None, kind=None):
        if await self.role(user_id) != Role.USER:
            return {
                "max_accounts": self.config.limits.max_pool_accounts,
                "expires_at": None,
                "staff": True,
                "accounts_unlimited": False,
                "channels_unlimited": False,
                "feature_plan": "both",
                "channel_limit": self.config.limits.max_channels_per_user,
            }
        if self.force_subs:
            await self.force_subs.require(user_id)
        row = await self.store.db.users.find_one({"_id": user_id})
        plan = (row or {}).get("plan", {})
        if not plan.get("expires_at") or plan["expires_at"] <= (at or now()):
            raise UserError("Premium is required for automation. Open My Plan and contact an owner/admin.")
        plan = normalized_plan(plan, self.config)
        if kind is not None and not feature_allowed(plan, kind):
            raise UserError("This feature is not included in your plan. Contact an admin to change it.")
        return effective_plan(plan, self.config)

    async def add_admin(self, actor, target):
        await self.require_staff(actor, owner_only=True)
        if target <= 0 or target in self.config.owner_ids:
            raise UserError("Use a positive non-owner Telegram user ID.")
        await self.store.db.admins.update_one({"_id": target}, {"$set": {"added_by": actor, "created_at": now()}}, upsert=True)
        await self.store.audit(actor, "admin_added", user_id=target)

    async def remove_admin(self, actor, target):
        await self.require_staff(actor, owner_only=True)
        if target in self.config.owner_ids:
            raise UserError("Owners are configured in config.json and cannot be removed in the bot.")
        await self.store.db.admins.delete_one({"_id": target})
        await self.store.audit(actor, "admin_removed", user_id=target)


class Plans:
    def __init__(self, store, access, notifier, config):
        self.store, self.access, self.notifier, self.config = store, access, notifier, config
        self.lock = asyncio.Lock()

    async def grant(self, actor, target, days, max_accounts=None, mode="set", feature_plan=None, channel_limit=None, request_key=None):
        await self.access.require_staff(actor)
        if target <= 0:
            raise UserError("Target must be a positive Telegram user ID.")
        async with self.access.target_locks.get(target):
            async with self.lock:
                role = await self.access.require_staff(actor)
                user = await self.store.db.users.find_one({"_id": target}) or {}
                try:
                    old = normalized_plan(user.get("plan"), self.config)
                except UserError:
                    if feature_plan is None or channel_limit is None:
                        raise
                    old = dict(user.get("plan") or {})  # Explicit staff settings may repair invalid metadata.
                event_id = (
                    sha256(f"plan:{actor}:{target}:{request_key}".encode()).hexdigest()[:24] if request_key else secrets.token_hex(12)
                )
                if user.get("plan", {}).get("version") == event_id:
                    return user["plan"]["expires_at"]
                feature_plan = old["feature_plan"] if feature_plan is None else feature_plan
                channel_limit = (
                    (UNLIMITED if old.get("channels_unlimited") else old["channel_limit"]) if channel_limit is None else channel_limit
                )
                max_accounts = (
                    (UNLIMITED if old.get("accounts_unlimited") else old.get("max_accounts", self.config.limits.default_plan_accounts))
                    if max_accounts is None
                    else max_accounts
                )
                if feature_plan not in FEATURE_PLANS:
                    raise UserError("Choose a channels, calls or both plan.")
                channel_limit = quota_choice(channel_limit, self.config.limits.max_channels_per_user, "Channel limit")
                max_accounts = quota_choice(max_accounts, self.config.limits.max_pool_accounts, "Account limit")
                channels_unlimited, accounts_unlimited = channel_limit is None, max_accounts is None
                effective_accounts = self.config.limits.max_pool_accounts if accounts_unlimited else max_accounts
                saved = await self.store.db.targets.count_documents({"user_id": target})
                if channel_limit is not None and saved > channel_limit:
                    raise UserError(
                        f"This user already has {saved} locked channels. Choose at least {saved}, or use staff channel corrections first."
                    )
                expires = plan_expiry(old.get("expires_at"), days, mode)
                expires = expires.replace(microsecond=expires.microsecond // 1000 * 1000)  # Mongo date precision.
                event = {
                    "id": event_id,
                    "action": "grant",
                    "actor": actor,
                    "actor_role": role.value,
                    "days": days,
                    "mode": mode,
                    "expires_at": expires,
                    "max_accounts": max_accounts,
                    "feature_plan": feature_plan,
                    "channel_limit": channel_limit,
                    "channels_unlimited": channels_unlimited,
                    "accounts_unlimited": accounts_unlimited,
                }
                await self.store.db.users.update_one(
                    {"_id": target},
                    {
                        "$set": {
                            "plan": {
                                "expires_at": expires,
                                "max_accounts": max_accounts,
                                "feature_plan": feature_plan,
                                "channel_limit": channel_limit,
                                "channels_unlimited": channels_unlimited,
                                "accounts_unlimited": accounts_unlimited,
                                "granted_by": actor,
                                "updated_at": now(),
                                "version": event_id,
                                "schema_version": 3,
                            },
                            "expiry_notified": False,
                        },
                        "$push": {"pending_plan_events": event},
                        "$setOnInsert": {"created_at": now()},
                    },
                    upsert=True,
                )
                await self.store.db.targets.update_many({"user_id": target}, {"$set": {"locked": True}})
                # Stop only work no longer covered; allowed() independently fails
                # closed even if this secondary cancellation write needs a retry.
                disallowed = list({"join", "call"} - FEATURE_PLANS[feature_plan])
                await self.store.db.jobs.update_many(
                    {
                        "user_id": target,
                        "status": {"$in": ["queued", "running"]},
                        "$or": [{"kind": {"$in": disallowed}}, {"account_count": {"$gt": effective_accounts}}],
                    },
                    {"$set": {"cancel_requested": True}},
                )
                if self.access.auto_wakeup:
                    self.access.auto_wakeup()
                return expires

    async def revoke(self, actor, target):
        await self.access.require_staff(actor)
        if target <= 0:
            raise UserError("Target must be a positive Telegram user ID.")
        async with self.access.target_locks.get(target):
            async with self.lock:
                role = await self.access.require_staff(actor)
                event = {"id": secrets.token_hex(12), "action": "revoke", "actor": actor, "actor_role": role.value, "expires_at": now()}
                existing = await self.store.db.users.find_one({"_id": target}) or {}
                event.update(
                    {
                        key: value
                        for key, value in existing.get("plan", {}).items()
                        if key in {"feature_plan", "channel_limit", "max_accounts", "channels_unlimited", "accounts_unlimited"}
                    }
                )
                fields = {"plan.expires_at": now(), "expiry_notified": True}
                if not existing.get("plan"):
                    fields.update(
                        {
                            "plan.feature_plan": "both",
                            "plan.channel_limit": self.config.limits.default_plan_channels,
                            "plan.schema_version": 2,
                        }
                    )
                await self.store.db.users.update_one(
                    {"_id": target},
                    {"$set": fields, "$push": {"pending_plan_events": event}},
                    upsert=True,
                )
                await self.store.db.jobs.update_many(
                    {"user_id": target, "status": {"$in": ["queued", "running"]}}, {"$set": {"cancel_requested": True}}
                )

                if self.access.auto_wakeup:
                    self.access.auto_wakeup()

    async def expire(self):
        # Always acquire user-target lock before the global plan mutation lock.
        async for candidate in self.store.db.users.find({"plan.expires_at": {"$lte": now()}, "expiry_notified": {"$ne": True}}).limit(200):
            async with self.access.target_locks.get(candidate["_id"]):
                async with self.lock:
                    user = await self.store.db.users.find_one(
                        {"_id": candidate["_id"], "plan.expires_at": {"$lte": now()}, "expiry_notified": {"$ne": True}}
                    )
                    if not user:
                        continue
                    event = {
                        "id": secrets.token_hex(12),
                        "action": "expire",
                        "actor": 0,
                        "actor_role": "system",
                        "expires_at": user["plan"]["expires_at"],
                    }
                    event.update(
                        {
                            key: value
                            for key, value in user["plan"].items()
                            if key in {"feature_plan", "channel_limit", "max_accounts", "channels_unlimited", "accounts_unlimited"}
                        }
                    )
                    result = await self.store.db.users.update_one(
                        {"_id": user["_id"], "plan.version": user["plan"].get("version"), "expiry_notified": {"$ne": True}},
                        {"$set": {"expiry_notified": True}, "$push": {"pending_plan_events": event}},
                    )
                    if result.modified_count:
                        await self.store.db.jobs.update_many(
                            {"user_id": user["_id"], "status": {"$in": ["queued", "running"]}}, {"$set": {"cancel_requested": True}}
                        )


class Targets:
    """Verify real control, not a checkbox: requester and bot must be target admins."""

    def __init__(self, store, bot, access, bot_id):
        self.store, self.bot, self.access, self.bot_id = store, bot, access, bot_id
        self.locks = access.target_locks

    async def verify_control(self, user_id, chat_id):
        try:
            user = await self.bot.get_chat_member(chat_id, user_id)
            bot = await self.bot.get_chat_member(chat_id, self.bot_id)
        except TelegramBadRequest:
            raise UserError("Add this bot as an admin to your channel/supergroup first, with Invite Users permission.") from None
        permitted = {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}
        if user.status not in permitted:
            raise UserError("You must be an administrator/owner of the selected target.")
        if bot.status not in permitted or not getattr(bot, "can_invite_users", False):
            raise UserError("The bot must be an admin with Invite Users permission in this target.")

    async def register(self, user_id, value):
        async with self.locks.get(user_id):
            return await self._register(user_id, value)

    async def _register(self, user_id, value):
        entitlement = await self.access.entitlement(user_id)
        value = value.strip()
        if value.lstrip("-").isdigit():
            chat_id = int(value)
        else:
            parsed = parse_link(value)
            if parsed.kind != "public":
                raise UserError("For private targets send the -100... chat ID after adding the bot as admin.")
            chat_id = "@" + parsed.value
        try:
            chat = await self.bot.get_chat(chat_id)
        except TelegramBadRequest:
            raise UserError("Target not found. Add bot as admin; then use @username or the numeric -100... chat ID.") from None
        if chat.type not in (ChatType.SUPERGROUP, ChatType.CHANNEL):
            raise UserError("Use a Telegram supergroup or channel, not a private chat/basic group.")
        await self.verify_control(user_id, chat.id)
        previous = await self.store.db.targets.find_one({"user_id": user_id, "chat_id": chat.id})
        if previous:
            await self.store.db.targets.update_one(
                {"_id": previous["_id"]}, {"$set": {"title": chat.title, "username": chat.username, "verified_at": now()}}
            )
            return previous["_id"]
        if await self.store.db.targets.count_documents({"user_id": user_id}) >= entitlement["channel_limit"]:
            raise channel_capacity_error(entitlement, self.access.config)
        links = []
        try:
            request = await self.bot.create_chat_invite_link(chat.id, name=f"TelePilot request {user_id}", creates_join_request=True)
            links.append(request.invite_link)
            call = await self.bot.create_chat_invite_link(chat.id, name=f"TelePilot call {user_id}", creates_join_request=False)
            links.append(call.invite_link)
            target_id = secrets.token_hex(6)
            await self.store.db.targets.insert_one(
                {
                    "_id": target_id,
                    "user_id": user_id,
                    "chat_id": chat.id,
                    "title": chat.title,
                    "username": chat.username,
                    "request_link": request.invite_link,
                    "call_link": call.invite_link,
                    "created_at": now(),
                    "verified_at": now(),
                    "locked": not entitlement.get("staff", False),
                    "locked_at": now(),
                }
            )
        except Exception:
            for link in links:
                with suppress(Exception):
                    await self.bot.revoke_chat_invite_link(chat.id, link)
            raise
        await self.store.audit(user_id, "target_registered", chat_id=chat.id)
        return target_id

    async def get(self, user_id, target_id, recheck=False):
        target = await self.store.db.targets.find_one({"_id": target_id, "user_id": user_id})
        if not target:
            raise UserError("Registered target not found. Open Targets and register it first.")
        if recheck:
            await self.verify_control(user_id, target["chat_id"])
        return target

    async def validate_link(self, target, text):
        parsed = parse_link(text)
        if parsed.kind == "public":
            try:
                chat = await self.bot.get_chat("@" + parsed.value)
            except TelegramBadRequest:
                raise UserError("Public target cannot be resolved by this bot.") from None
            if chat.id != target["chat_id"]:
                raise UserError("That link does not belong to your selected authorized target.")
        else:
            permitted = {parse_link(target[k]).identity for k in ("request_link", "call_link")}
            if parsed.identity not in permitted:
                raise UserError(
                    "For private targets use this bot's managed request/call link. Arbitrary private invite ownership cannot be verified before joining."
                )
        return parsed

    async def join_link(self, target):
        """Current target identity decides direct public join vs private request.

        Never prefer a request invite just because the old wizard stored one for
        a public target. Stored targets/ownership and numeric ID remain mandatory.
        """
        try:
            async with asyncio.timeout(10):
                chat = await self.bot.get_chat(target["chat_id"])
        except TelegramBadRequest:
            raise UserError("Saved target cannot be resolved. Check bot access and target details.") from None
        if chat.id != target["chat_id"] or chat.type not in {ChatType.CHANNEL, ChatType.SUPERGROUP}:
            raise UserError("Saved target identity/type changed; no join was attempted.")
        username = getattr(chat, "username", None)
        return parse_link("@" + username) if username else parse_link(target["request_link"])

    async def remove(self, user_id, target_id):
        async with self.locks.get(user_id):
            await self._remove(user_id, target_id)

    async def _remove(self, user_id, target_id):
        if await self.access.role(user_id) == Role.USER:
            raise UserError("Saved channels are locked, even after your plan ends. Only an owner/admin can make a correction.")
        await self._delete_target(user_id, target_id, actor=user_id, reason="staff own target removal")

    async def staff_remove(self, actor, user_id, target_id, reason):
        await self.access.require_staff(actor)
        reason = reason.strip()
        if not 5 <= len(reason) <= 200:
            raise UserError("Enter a correction reason of 5–200 characters. Do not include secrets.")
        async with self.locks.get(user_id):
            await self.access.require_staff(actor)
            await self._delete_target(user_id, target_id, actor, reason)

    async def _delete_target(self, user_id, target_id, actor, reason):
        target = await self.get(user_id, target_id)
        busy_sids = [
            row["busy_job"][5:] async for row in self.store.db.accounts.find({"busy_job": {"$regex": "^auto:"}}, {"busy_job": 1, "_id": 0})
        ]
        auto_busy = await self.store.db.auto_sessions.count_documents(
            {"target_id": target_id, "$or": [{"assigned_count": {"$gt": 0}}, {"_id": {"$in": busy_sids}}]}
        )
        if target.get("auto_call", {}).get("enabled") or auto_busy:
            raise UserError("Disable automatic calls for this target first and wait for its accounts to leave.")
        if await self.store.db.jobs.count_documents({"target_id": target_id, "status": {"$in": ["queued", "running"]}}):
            raise UserError("Cancel this target's queued/running jobs first.")
        # An acknowledged audit event is required before a deliberate override.
        await self.store.audit(
            actor, "target_correction_authorized", user_id=user_id, target_id=target_id, chat_id=target["chat_id"], reason=reason
        )
        for key in ("request_link", "call_link"):
            try:
                await self.bot.revoke_chat_invite_link(target["chat_id"], target[key])
            except TelegramBadRequest:
                pass
        await self.store.db.targets.delete_one({"_id": target_id, "user_id": user_id})
        await self.store.audit(actor, "target_removed", user_id=user_id, target_id=target_id, chat_id=target["chat_id"])
        await self.notifier_target_correction(user_id, target, actor)

    async def notifier_target_correction(self, user_id, target, actor):
        # Durable source event; no links or free-text reason is sent to customers.
        await self.store.db.users.update_one(
            {"_id": user_id},
            {
                "$push": {
                    "pending_target_events": {
                        "id": secrets.token_hex(12),
                        "actor": actor,
                        "chat_id": target["chat_id"],
                        "title": target["title"][:64],
                    }
                }
            },
            upsert=True,
        )
