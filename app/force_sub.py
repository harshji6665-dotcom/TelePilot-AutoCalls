"""Owner-managed subscription requirements; staff are exempt, checks fail closed."""

from collections import OrderedDict
from contextlib import suppress
import asyncio
import secrets
import time

from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter, TelegramForbiddenError

from .links import parse_link
from .security import Role, UserError
from .timeutils import now
from .ui import KeyedLocks


class SubscriptionRequired(UserError):
    def __init__(self, rows, error_type=None):
        self.rows, self.error_type = rows, error_type
        super().__init__(
            "Membership could not be verified. Try check again shortly."
            if error_type
            else "Join the required channels/groups, then tap check membership."
        )


class ForceSubscriptions:
    def __init__(self, store, bot, access, bot_id, config):
        self.store, self.bot, self.access, self.bot_id, self.config = store, bot, access, bot_id, config
        self.lock, self.user_locks = asyncio.Lock(), KeyedLocks()
        self.cache = OrderedDict()
        self.not_before = 0.0
        self.api_limit = asyncio.Semaphore(3)

    async def rows(self):
        return (
            await self.store.db.force_subs.find({})
            .sort("created_at", 1)
            .limit(self.config.limits.max_force_sub_channels)
            .to_list(length=self.config.limits.max_force_sub_channels)
        )

    async def view(self, actor):
        await self.access.require_staff(actor)
        return await self.rows()

    async def add(self, actor, value):
        await self.access.require_staff(actor, owner_only=True)
        value = value.strip()
        if value.lstrip("-").isdigit():
            ident = int(value)
        else:
            parsed = parse_link(value)
            if parsed.kind != "public":
                raise UserError("For a private required channel use its -100... chat ID, not an arbitrary invite.")
            ident = "@" + parsed.value
        try:
            chat = await self.bot.get_chat(ident)
            owner = await self.bot.get_chat_member(chat.id, actor)
            member = await self.bot.get_chat_member(chat.id, self.bot_id)
        except TelegramBadRequest:
            raise UserError("Add this bot as an admin with invite permission first. Use @username or the chat ID.") from None
        permitted = {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}
        if chat.type not in {ChatType.CHANNEL, ChatType.SUPERGROUP}:
            raise UserError("Use a channel or supergroup, not a private chat/basic group.")
        if owner.status not in permitted or member.status not in permitted or not getattr(member, "can_invite_users", False):
            raise UserError("You and this bot must be target admins; the bot needs invite permission.")
        async with self.lock:
            await self.access.require_staff(actor, owner_only=True)
            previous = await self.store.db.force_subs.find_one({"_id": chat.id})
            if previous:
                return previous  # Duplicate add never creates another managed invite.
            if await self.store.db.force_subs.count_documents({}) >= self.config.limits.max_force_sub_channels:
                raise UserError(f"At most {self.config.limits.max_force_sub_channels} required channels/groups are supported.")
            managed = not bool(chat.username)
            link = "https://t.me/" + chat.username if chat.username else None
            try:
                if managed:
                    invite = await self.bot.create_chat_invite_link(chat.id, name="TelePilot membership", creates_join_request=False)
                    link = invite.invite_link
                row = {
                    "_id": chat.id,
                    "title": (chat.title or "required channel")[:100],
                    "join_url": link,
                    "managed_link": managed,
                    "added_by": actor,
                    "created_at": now(),
                    "revision": secrets.token_hex(6),
                }
                await self.store.audit(actor, "force_sub_add_authorized", chat_id=chat.id)
                await self.store.db.force_subs.insert_one(row)
            except BaseException:
                if managed and link:
                    with suppress(Exception):
                        await self.bot.revoke_chat_invite_link(chat.id, link)
                raise
            self.cache.clear()
            return row

    async def remove(self, actor, chat_id):
        await self.access.require_staff(actor, owner_only=True)
        async with self.lock:
            await self.access.require_staff(actor, owner_only=True)
            row = await self.store.db.force_subs.find_one({"_id": chat_id})
            if not row:
                raise UserError("Required channel not found. Refresh the list.")
            await self.store.audit(actor, "force_sub_remove_authorized", chat_id=chat_id)
            if row["managed_link"]:
                try:
                    await self.bot.revoke_chat_invite_link(chat_id, row["join_url"])
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass  # Removed bot/already revoked: owner must still repair a broken requirement.
            await self.store.db.force_subs.delete_one({"_id": chat_id})
            self.cache.clear()

    async def missing(self, user_id, force=False):
        if await self.access.role(user_id) != Role.USER:
            return []  # An owner/admin must always be able to repair requirements.
        async with self.user_locks.get(user_id):
            rows = await self.rows()
            if not rows:
                return []
            fingerprint = tuple((row["_id"], row["revision"]) for row in rows)
            cached = self.cache.get(user_id)
            tick = time.monotonic()
            if cached and cached["fingerprint"] == fingerprint:
                age = tick - cached["at"]
                reuse = (tick - cached.get("forced_at", -1000) < 5) if force else age < (10 if cached["missing"] or cached["error"] else 30)
                if reuse:
                    self.cache.move_to_end(user_id)
                    if cached["error"]:
                        raise SubscriptionRequired(cached["missing"], cached["error"])
                    return cached["missing"]
            if tick < self.not_before:
                raise SubscriptionRequired(rows, "TelegramRetryAfter")
            missing, error_type = [], None

            async def check(row):
                async with self.api_limit:
                    if time.monotonic() < self.not_before:
                        return row, "TelegramRetryAfter"
                    try:
                        async with asyncio.timeout(8):
                            member = await self.bot.get_chat_member(row["_id"], user_id)
                        joined = member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER}
                        joined = joined or (member.status == ChatMemberStatus.RESTRICTED and bool(getattr(member, "is_member", False)))
                        return (None if joined else row), None
                    except Exception as exc:
                        if isinstance(exc, TelegramRetryAfter):
                            self.not_before = time.monotonic() + exc.retry_after + 1
                        return row, type(exc).__name__

            try:
                async with asyncio.timeout(12):
                    outcomes = await asyncio.gather(*(check(row) for row in rows))
                for row, error in outcomes:
                    if row:
                        missing.append(row)
                    error_type = error_type or error
            except TimeoutError:
                # A queued/partial check is not proof of membership. Keep the
                # full bounded gate visible; no indefinitely blocked /start.
                missing, error_type = rows, "TimeoutError"
            self.cache[user_id] = {
                "fingerprint": fingerprint,
                "at": tick,
                "missing": missing,
                "error": error_type,
                "forced_at": tick if force else (cached or {}).get("forced_at", -1000),
            }
            self.cache.move_to_end(user_id)
            while len(self.cache) > 1024:
                self.cache.popitem(last=False)
            if error_type:
                raise SubscriptionRequired(missing, error_type)
            return missing

    async def require(self, user_id, force=False):
        missing = await self.missing(user_id, force)
        if missing:
            raise SubscriptionRequired(missing)
