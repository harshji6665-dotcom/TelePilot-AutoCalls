"""Owner-managed start photos; explicit /start replaces, navigation never resends."""

import asyncio
from contextlib import suppress
from datetime import timedelta
import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

from .security import UserError
from .timeutils import now

logger = logging.getLogger(__name__)
BANNER_SHA = "52add815ba014ae85fe1d50b9f73ce5eac85902485959586c4b70b0f993c9deb"


class StartPhotoUI:
    async def start_photo_enabled(self):
        return bool(await self.r.store.setting("start_photo_enabled", self.r.config.start_photo_enabled))

    def original_photo(self):
        asset = Path(__file__).resolve().parent.parent / "assets/start.png"
        return FSInputFile(asset) if asset.exists() else self.r.config.default_start_image_url

    async def send_start_photo(self, message, user_id):
        """Best-effort optional photo, bounded including settings reads.

        Telegram RetryAfter is retained by Panels, so callers do not bypass it
        with another send. Unknown network outcomes are NOT immediately retried.
        """
        try:
            async with asyncio.timeout(12):
                if not await self.start_photo_enabled():
                    return None
                custom = await self.r.store.setting("custom_start_image")
                cached = await self.r.store.setting("default_start_image_cache", {})
                bot_id = self.r.targets.bot_id
                cache_valid = cached.get("bot_id") == bot_id and cached.get("sha256") == BANNER_SHA and cached.get("file_id")
                source = custom or (cached["file_id"] if cache_valid else self.original_photo())
                try:
                    result = await self.deliver_start_photo(message, user_id, source)
                except TelegramBadRequest:
                    # A bad stored/custom file ID must not hide the supplied fallback.
                    # Do not retry a timeout/FloodWait/unknown acknowledgement here.
                    result = await self.deliver_start_photo(message, user_id, self.original_photo())
                    custom = None
                photos = getattr(result, "photo", None)
                if not custom and isinstance(photos, (list, tuple)) and photos:
                    file_id = getattr(photos[-1], "file_id", None)
                    if isinstance(file_id, str):
                        with suppress(Exception):
                            await self.r.store.set_setting(
                                "default_start_image_cache", {"bot_id": bot_id, "file_id": file_id, "sha256": BANNER_SHA}
                            )
                return result
        except Exception as exc:
            logger.warning(
                "Optional start photo unavailable; actor=%s error=%s; text response will still be attempted", user_id, type(exc).__name__
            )
            return None

    async def deliver_start_photo(self, message, user_id, source, caption=None):
        if self.r.config.ui_edit_panels:
            anchor = getattr(message, "raw", message)
            return await self.ui.banner(anchor, user_id, source, fresh=True, caption=caption)
        return await message.answer_photo(source, caption=caption)

    async def photo_settings(self, message, actor):
        await self.r.access.require_staff(actor, owner_only=True)
        enabled = await self.start_photo_enabled()
        custom = await self.r.store.setting("custom_start_image")
        await message.answer(
            f"<b>start photo settings</b>\n<blockquote>Status · {'enabled' if enabled else 'disabled'}\nImage · {'custom Telegram photo' if custom else 'supplied default'}\nAn enabled photo is sent with every explicit /start. Button navigation stays in the current panel.</blockquote>\n"
            "Send an image as a Telegram photo to change it. Disabling hides the photo on future starts; it does not remove the saved choice. Login QR photos are separate and remain available.",
            reply_markup=self.keyboard(
                [("set start photo", "owner:banner"), ("preview photo", "owner:photo_preview")],
                [("disable photo" if enabled else "enable photo", "owner:photo_off" if enabled else "owner:photo_on")],
                [("restore supplied image", "owner:photo_reset")],
                [("← manage", "nav:staff")],
            ),
        )

    async def photo_prompt(self, message, actor, state):
        await self.r.access.require_staff(actor, owner_only=True)
        await state.clear()
        await state.set_state(self.Input.banner)
        await state.update_data(photo_actor=actor, photo_until=now() + timedelta(minutes=15))
        await message.answer(
            "<b>set start photo</b>\n<blockquote>Send one image as a Telegram photo, not a document or URL. It replaces only the start image. The separate enable/disable setting is preserved. This form expires in 15 minutes.</blockquote>",
            reply_markup=self.keyboard([("cancel", "owner:photo")]),
        )

    async def accept_photo(self, message, actor, state):
        await self.r.access.require_staff(actor, owner_only=True)
        data = await state.get_data()
        if data.get("photo_actor") != actor or data.get("photo_until", now()) <= now():
            await state.clear()
            raise UserError("Photo form expired or belongs to another user. Open start photo settings again.")
        if not message.photo:
            raise UserError("Send an image as a Telegram photo, not a file/link.")
        await self.r.store.audit(actor, "start_photo_set_authorized")
        await self.r.store.set_setting("custom_start_image", message.photo[-1].file_id)
        await state.clear()
        await self.photo_settings(message, actor)

    async def photo_action(self, message, actor, operation, state):
        await self.r.access.require_staff(actor, owner_only=True)
        if operation == "banner":
            await self.photo_prompt(message, actor, state)
            return
        await state.clear()
        if operation in {"photo_on", "photo_off"}:
            value = operation == "photo_on"  # Explicit setters; double clicks do not reverse it.
            await self.r.store.audit(actor, "start_photo_visibility_authorized", enabled=value)
            await self.r.store.set_setting("start_photo_enabled", value)
        elif operation == "photo_reset":
            await self.r.store.audit(actor, "start_photo_reset_authorized")
            await self.r.store.set_setting("custom_start_image", None)
            await self.r.store.set_setting("default_start_image_cache", {})
        elif operation == "photo_preview":
            custom = await self.r.store.setting("custom_start_image")
            source = custom or self.original_photo()
            try:
                await self.deliver_start_photo(message, actor, source, caption="<b>start photo preview</b>")
            except TelegramBadRequest:
                await self.deliver_start_photo(message, actor, self.original_photo(), caption="<b>supplied fallback preview</b>")
        elif operation != "photo":
            raise UserError("Old start photo button. Open the owner panel again.")
        await self.photo_settings(message, actor)
