"""Private editable panels; smallcaps styling never changes functional values."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import timedelta
from hashlib import sha256
from html.parser import HTMLParser
import logging
import re
import time
from types import SimpleNamespace
from weakref import WeakValueDictionary

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, ForceReply, InputMediaPhoto, LinkPreviewOptions

from pymongo.errors import PyMongoError
from .security import UserError
from .timeutils import now

logger = logging.getLogger(__name__)
CAPS = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ", strict=True))
FUNCTIONAL = re.compile(
    r"(?:https?://|tg://|t\.me/|telegram\.me/)[^\s<>]+|@[A-Za-z0-9_]+|/[A-Za-z][A-Za-z0-9_]*(?:@[A-Za-z0-9_]+)?|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);"
)


def smallcaps(text: str) -> str:
    def convert(value):
        return "".join(CAPS.get(char.lower(), char) for char in value)

    pieces, offset = [], 0
    for match in FUNCTIONAL.finditer(text):
        pieces.extend((convert(text[offset : match.start()]), match.group()))
        offset = match.end()
    pieces.append(convert(text[offset:]))
    return "".join(pieces)


class _StyledHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts, self.pending, self.protected = [], [], 0

    def flush(self):
        # Keep contiguous data/entities together so an escaped URL query such as
        # ?A=X&amp;B=Y remains an intact functional token, not partly smallcaps.
        value = "".join(self.pending)
        self.parts.append(value if self.protected else smallcaps(value))
        self.pending.clear()

    def close(self):
        super().close()
        self.flush()

    def handle_starttag(self, tag, attrs):
        self.flush()
        self.parts.append(self.get_starttag_text())
        if tag in {"code", "pre"}:
            self.protected += 1

    def handle_endtag(self, tag):
        self.flush()
        self.parts.append(f"</{tag}>")
        if tag in {"code", "pre"}:
            self.protected = max(0, self.protected - 1)

    def handle_startendtag(self, tag, attrs):
        self.flush()
        self.parts.append(self.get_starttag_text())

    def handle_data(self, data):
        self.pending.append(data)

    def handle_entityref(self, name):
        self.pending.append(f"&{name};")

    def handle_charref(self, name):
        self.pending.append(f"&#{name};")


def style_text(text: str, style="smallcaps") -> str:
    if style != "smallcaps":
        return text
    parser = _StyledHTML()
    parser.feed(text)
    parser.close()
    return "".join(parser.parts)


def style_markup(markup, style="smallcaps"):
    if style != "smallcaps" or not isinstance(markup, InlineKeyboardMarkup):
        return markup
    return markup.model_copy(
        update={
            "inline_keyboard": [
                [button.model_copy(update={"text": smallcaps(button.text)}) for button in row] for row in markup.inline_keyboard
            ]
        }
    )


class StyleRequests(BaseRequestMiddleware):
    """Also styles real notifications, group replies and legacy approvals."""

    def __init__(self, config):
        self.config = config

    async def __call__(self, make_request, bot, method):
        updates = {}
        for field in ("text", "caption"):
            value = getattr(method, field, None)
            if isinstance(value, str):
                updates[field] = style_text(value, self.config.ui_style)
        markup = getattr(method, "reply_markup", None)
        if markup is not None:
            updates["reply_markup"] = style_markup(markup, self.config.ui_style)
        media = getattr(method, "media", None)
        if isinstance(getattr(media, "caption", None), str):
            updates["media"] = media.model_copy(update={"caption": style_text(media.caption, self.config.ui_style)})
        if updates:
            method = method.model_copy(update=updates)
        return await make_request(bot, method)


class KeyedLocks:
    def __init__(self):
        self.items = WeakValueDictionary()

    def get(self, key):
        lock = self.items.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self.items[key] = lock
        return lock


class Panels:
    """One durable text panel + optional reused start banner per private user.

    QR photos are transient login secrets, never the durable panel/banner.
    Notifications are intentional new events and do not replace this panel.
    """

    def __init__(self, runtime):
        self.r = runtime
        self.locks, self.actions = KeyedLocks(), KeyedLocks()
        self.cache = OrderedDict()
        self.cooldowns = {}
        self.dirty = set()

    def wrap(self, message, user_id):
        if not self.r.config.ui_edit_panels or isinstance(message, PanelMessage):
            return message
        return PanelMessage(message, self, user_id)

    async def row(self, user_id):
        cached = self.cache.get(user_id)
        if cached is not None:
            self.cache.move_to_end(user_id)
            return dict(cached)
        value = await self.r.store.db.ui_panels.find_one({"_id": user_id}) or {"_id": user_id}
        return value

    async def save(self, user_id, row):
        row.update(updated_at=now(), purge_at=now() + timedelta(days=90))
        # Cache before optional UI metadata persistence: a brief DB write failure
        # after send must not create another panel. Authorization never uses this cache.
        self.cache[user_id] = dict(row)
        self.cache.move_to_end(user_id)
        while len(self.cache) > 512:
            old_id, _ = self.cache.popitem(last=False)
            self.dirty.discard(old_id)
        try:
            await self.r.store.db.ui_panels.update_one(
                {"_id": user_id}, {"$set": {key: val for key, val in row.items() if key != "_id"}}, upsert=True
            )
            self.dirty.discard(user_id)
        except PyMongoError:
            self.dirty.add(user_id)
            logger.warning("Panel metadata persistence delayed; actor=%s; existing RAM panel retained", user_id)

    def check_cooldown(self, user_id):
        until = self.cooldowns.get(user_id, 0)
        if until > time.monotonic():
            raise UserError(f"Please wait {max(1, int(until - time.monotonic()) + 1)} seconds before updating this screen.")
        self.cooldowns.pop(user_id, None)

    async def request(self, user_id, call):
        try:
            return await call
        except TelegramRetryAfter as exc:
            tick = time.monotonic()
            self.cooldowns = {uid: until for uid, until in self.cooldowns.items() if until > tick}
            self.cooldowns[user_id] = tick + exc.retry_after + 1
            raise UserError(f"Telegram asks us to wait {exc.retry_after} seconds. Your existing panel is safe; try again later.") from None

    async def render(self, anchor, user_id, text, reply_markup=None, force=False, fresh=False, view_key=None, expected_view=None, **kwargs):
        async with self.locks.get(user_id):
            row = await self.row(user_id)
            if expected_view is not None and row.get("view_key") != expected_view:
                return None  # A background health result must not replace a newer page.
            text = style_text(text, self.r.config.ui_style)
            # ForceReply cannot be attached to an edited Telegram message.
            # Credential parsing already preserves exact password text.
            if isinstance(reply_markup, ForceReply):
                ctx = self.r.login.chat_contexts.get(user_id)
                reply_markup = (
                    InlineKeyboardMarkup(inline_keyboard=[[{"text": "cancel sign-in", "callback_data": "signin:cancel:" + ctx.context_id}]])
                    if ctx
                    else None
                )
            markup = style_markup(reply_markup, self.r.config.ui_style)
            signature = sha256((text + (markup.model_dump_json() if markup else "")).encode()).hexdigest()
            if not fresh and not force and row.get("message_id") and row.get("render_hash") == signature:
                if user_id in self.dirty or row.get("view_key") != view_key:
                    row["view_key"] = view_key
                    await self.save(user_id, row)
                return SimpleNamespace(message_id=row["message_id"])
            self.check_cooldown(user_id)
            options = {"parse_mode": "HTML", "reply_markup": markup, "link_preview_options": LinkPreviewOptions(is_disabled=True)}
            previous = row.get("message_id")
            current = None if fresh else previous
            if current:
                try:
                    result = await self.request(
                        user_id, self.r.bot.edit_message_text(text=text, chat_id=user_id, message_id=current, **options)
                    )
                except TelegramBadRequest as exc:
                    reason = exc.message.lower()
                    if "message is not modified" in reason:
                        result = SimpleNamespace(message_id=current)
                    elif any(
                        part in reason
                        for part in (
                            "message to edit not found",
                            "message can't be edited",
                            "message_id_invalid",
                            "message identifier is not specified",
                        )
                    ):
                        # Deleted/inaccessible old panel: recreate once, not on every click.
                        result = await self.request(user_id, anchor.answer(text, **options))
                    else:
                        logger.error("Panel edit rejected; actor=%s error=%s", user_id, type(exc).__name__)
                        raise UserError("This screen could not be updated. Try /start; check the sanitized logs if it repeats.") from None
            else:
                result = await self.request(user_id, anchor.answer(text, **options))
            message_id = getattr(result, "message_id", current)
            if isinstance(message_id, int):
                row.update(message_id=message_id, render_hash=signature, view_key=view_key)
                await self.save(user_id, row)
                if fresh and previous and previous != message_id:
                    # Explicit /start must be visible at the bottom of the chat.
                    # Remove the old panel only AFTER its replacement was acknowledged.
                    try:
                        await self.r.bot.delete_message(user_id, previous)
                    except Exception:
                        pass  # Old Telegram messages may be inaccessible/too old to delete.
            return result

    async def banner(self, anchor, user_id, photo, force=False, fresh=False, caption=None):
        async with self.locks.get(user_id):
            row = await self.row(user_id)
            path = getattr(photo, "path", None)
            key = "file:" + str(path) if path else "telegram:" + str(photo)
            if not fresh and not force and row.get("banner_id") and row.get("banner_key") == key:
                if user_id in self.dirty:
                    await self.save(user_id, row)
                return
            self.check_cooldown(user_id)
            previous = row.get("banner_id")
            if previous and not fresh:
                try:
                    await self.request(
                        user_id,
                        self.r.bot.edit_message_media(chat_id=user_id, message_id=row["banner_id"], media=InputMediaPhoto(media=photo)),
                    )
                    row["banner_key"] = key
                    await self.save(user_id, row)
                    return
                except TelegramBadRequest as exc:
                    if "message is not modified" in exc.message.lower():
                        row["banner_key"] = key
                        await self.save(user_id, row)
                        return
                    if not any(
                        part in exc.message.lower()
                        for part in ("message to edit not found", "message can't be edited", "message_id_invalid")
                    ):
                        raise
            options = {"caption": style_text(caption, self.r.config.ui_style)} if caption else {}
            result = await self.request(user_id, anchor.answer_photo(photo, **options))
            message_id = getattr(result, "message_id", None)
            if isinstance(message_id, int):
                row.update(banner_id=message_id, banner_key=key)
                await self.save(user_id, row)
                if fresh and previous and previous != message_id:
                    try:
                        await self.r.bot.delete_message(user_id, previous)
                    except Exception:
                        pass  # Keep the new acknowledged photo; old cleanup is best effort.
            return result


class PanelMessage:
    def __init__(self, raw, panels, user_id):
        self.raw, self.panels, self.user_id = raw, panels, user_id

    def __getattr__(self, name):
        return getattr(self.raw, name)

    async def answer(self, text, **kwargs):
        return await self.panels.render(self.raw, self.user_id, text, **kwargs)

    async def answer_photo(self, photo, caption=None, reply_markup=None, **kwargs):
        if getattr(photo, "filename", "") == "telegram-signin-qr.png":
            # Login token is deliberately short-lived and cleaned by LoginManager.
            return await self.raw.answer_photo(
                photo,
                caption=style_text(caption or "", self.panels.r.config.ui_style),
                reply_markup=style_markup(reply_markup, self.panels.r.config.ui_style),
                **kwargs,
            )
        # /start is an explicit repair request: probe an unchanged banner/panel
        # so deleted messages can be recreated. Normal navigation remains deduplicated.
        await self.panels.banner(self.raw, self.user_id, photo, force=True)
        if caption:
            return await self.answer(caption, reply_markup=reply_markup, force=True, **kwargs)

    async def edit_reply_markup(self, **kwargs):
        # The next panel render replaces all controls atomically. Avoid an extra
        # request/flicker and never edit a just-deleted transient QR/photo.
        return None
