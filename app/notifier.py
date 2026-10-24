import asyncio
from datetime import timedelta
import logging

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .security import html
from .diagnostics import error_overview
from .plans import feature_label, quota_label
from .message_safety import bounded_html, plain_html, bad_request_category
from .timeutils import now, display_time

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, store, bot, config):
        self.store, self.bot, self.config = store, bot, config
        self.stopping = False

    async def enqueue(self, recipient: int, text: str, event_key: str, buttons=None):
        row = {
            "recipient": recipient,
            "text": bounded_html(text),
            "event_key": f"{event_key}:{recipient}",
            "buttons": buttons,
            "status": "pending",
            "attempts": 0,
            "run_at": now(),
            "created_at": now(),
        }
        try:
            await self.store.db.outbox.insert_one(row)
        except DuplicateKeyError:
            pass

    async def owners(self, text: str, event_key: str):
        recipients = set(self.config.owner_ids)
        if self.config.logging_chat_id:
            recipients.add(self.config.logging_chat_id)
        for recipient in recipients:
            await self.enqueue(recipient, text, event_key)

    async def drain_plan_events(self):
        async for user in self.store.db.users.find({"pending_plan_events.0": {"$exists": True}}).limit(100):
            for event in user.get("pending_plan_events", []):
                end = display_time(event.get("expires_at"), self.config.timezone)
                if event["action"] == "revoke":
                    body = "Your Premium plan was revoked. Automation is no longer available."
                elif event["action"] == "expire":
                    body = "Your Premium plan has expired. Contact an owner/admin to renew."
                else:
                    body = (
                        f"Premium activated/updated!\nDuration: <b>{event['days']} days</b> ({html(event['mode'])}).\n"
                        f"Valid until: <b>{html(end)}</b>.\nAccount limit per job: <b>{quota_label(event, 'accounts')}</b>.\n"
                        f"Features: <b>{html(feature_label(event.get('feature_plan', 'both')))}</b>.\n"
                        f"Locked channel/group limit: <b>{quota_label(event, 'channels')}</b>.\n"
                        "Unlimited includes current and future eligible pool accounts, subject to operational ceilings. Manual tasks keep their reviewed count; automatic calls rebalance fairly. Only your included features are available. Calls are group voice/video chats. Saved channels cannot be replaced without a staff correction."
                    )
                await self.enqueue(user["_id"], f"<b>💎 TelePilot · Plan update</b>\n<blockquote>{body}</blockquote>", event["id"])
                alert = (
                    f"<b>Plan {html(event['action'])}</b>\n<blockquote>Actor: {html(event['actor_role'])} <code>{event['actor']}</code>\n"
                    f"Target user: <code>{user['_id']}</code>\nDuration: {event.get('days', 0)} days\n"
                    f"Mode: {html(event.get('mode', '—'))}\nExpiry: {html(end)}\n"
                    f"Account cap: {quota_label(event, 'accounts')}\nFeatures: {html(feature_label(event.get('feature_plan', 'both')))}\nChannel limit: {quota_label(event, 'channels')}</blockquote>"
                )
                await self.owners(alert, "owners:" + event["id"])
                await self.store.db.audit.update_one(
                    {"_id": event["id"]},
                    {
                        "$setOnInsert": {
                            "actor": event["actor"],
                            "action": "plan_" + event["action"],
                            "details": {
                                "user_id": user["_id"],
                                "days": event.get("days", 0),
                                "expires_at": event.get("expires_at"),
                                "feature_plan": event.get("feature_plan", "both"),
                                "channel_limit": event.get("channel_limit", 10),
                                "max_accounts": event.get("max_accounts"),
                                "channels_unlimited": event.get("channels_unlimited", False),
                                "accounts_unlimited": event.get("accounts_unlimited", False),
                            },
                            "created_at": now(),
                            "purge_at": now() + timedelta(days=self.config.audit_retention_days),
                        }
                    },
                    upsert=True,
                )
                await self.store.db.users.update_one({"_id": user["_id"]}, {"$pull": {"pending_plan_events": {"id": event["id"]}}})

    async def drain_target_events(self):
        async for user in self.store.db.users.find({"pending_target_events.0": {"$exists": True}}).limit(100):
            for event in user.get("pending_target_events", []):
                await self.enqueue(
                    user["_id"],
                    f"<b>channel correction</b>\n<blockquote>An owner/admin removed {html(event['title'])} (<code>{event['chat_id']}</code>) from your locked channels. Its saved invites were revoked. You can add a replacement if your active plan has space.</blockquote>",
                    "target:" + event["id"],
                )
                await self.owners(
                    f"<b>channel corrected</b>\n<blockquote>Staff: <code>{event['actor']}</code>\nUser: <code>{user['_id']}</code>\nChannel: <code>{event['chat_id']}</code></blockquote>",
                    "target-owner:" + event["id"],
                )
                await self.store.db.users.update_one({"_id": user["_id"]}, {"$pull": {"pending_target_events": {"id": event["id"]}}})

    async def drain_job_events(self):
        from .jobs import job_summary

        async for job in self.store.db.jobs.find({"notification_pending": True}).limit(100):
            text = (
                f"<b>Job {html(job['status'])}</b>\n<blockquote>Job: <code>{job['_id']}</code>\n"
                f"Type: {html(job['kind'])}\nTarget: {html(job['target_title'])}\n"
                f"{html(job_summary(job))}\n{html(job.get('reason', ''))}</blockquote>"
            )
            errors = error_overview(job.get("results", []))
            if errors:
                text += "\n<b>error types</b>\n<pre>" + html(errors[:650]) + "</pre>"
            if any(row["status"] in {"request_sent", "awaiting_approval"} for row in job.get("results", [])):
                text += "\nRequests sent still need admin approval; they are not confirmed memberships."
            buttons = [[{"text": "task details", "callback_data": "job:view:" + job["_id"]}]]
            await self.enqueue(job["user_id"], text, "job-terminal:" + job["_id"], buttons)
            if self.config.logging_chat_id and self.config.logging_chat_id != job["user_id"]:
                await self.enqueue(self.config.logging_chat_id, text, "job-log:" + job["_id"])
            await self.store.db.audit.update_one(
                {"_id": "job:" + job["_id"]},
                {
                    "$setOnInsert": {
                        "actor": 0,
                        "action": "job_finished",
                        "details": {"job_id": job["_id"], "user_id": job["user_id"], "status": job["status"], "errors": errors},
                        "created_at": now(),
                        "purge_at": now() + timedelta(days=self.config.audit_retention_days),
                    }
                },
                upsert=True,
            )
            await self.store.db.jobs.update_one({"_id": job["_id"]}, {"$set": {"notification_pending": False}})

    async def deliver(self, row, markup):
        try:
            await self.bot.send_message(row["recipient"], bounded_html(row["text"]), reply_markup=markup)
        except TelegramBadRequest as exc:
            category = bad_request_category(exc)
            if category not in {"html_parse", "message_too_long"} or row.get("plain_fallback"):
                raise
            # Also repairs malformed/truncated legacy outbox HTML once. This is
            # deliberately NOT attempted for unknown delivery/permission errors.
            text = plain_html(row["text"])
            await self.store.db.outbox.update_one(
                {"_id": row["_id"]}, {"$set": {"text": text, "plain_fallback": True, "fallback_category": category}}
            )
            logger.warning("Notification plain-format fallback; category=%s", category)
            await self.bot.send_message(row["recipient"], text, reply_markup=markup)

    async def run(self):
        await self.store.db.outbox.update_many({"status": "sending"}, {"$set": {"status": "pending", "run_at": now()}})
        last_drain = 0.0
        while not self.stopping:
            try:
                if asyncio.get_running_loop().time() - last_drain > 3:
                    await self.drain_plan_events()
                    await self.drain_job_events()
                    await self.drain_target_events()
                    last_drain = asyncio.get_running_loop().time()
                row = await self.store.db.outbox.find_one_and_update(
                    {"status": "pending", "run_at": {"$lte": now()}},
                    {"$set": {"status": "sending"}},
                    sort=[("run_at", 1)],
                    return_document=ReturnDocument.AFTER,
                )
                if not row:
                    await asyncio.sleep(0.8)
                    continue
                markup = None
                if row.get("buttons"):
                    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**b) for b in line] for line in row["buttons"]])
                try:
                    await self.deliver(row, markup)
                    await self.store.db.outbox.update_one(
                        {"_id": row["_id"]}, {"$set": {"status": "sent", "sent_at": now(), "purge_at": now() + timedelta(days=7)}}
                    )
                except Exception as exc:
                    attempts = row["attempts"] + 1
                    category = bad_request_category(exc) if isinstance(exc, TelegramBadRequest) else type(exc).__name__
                    failed = (
                        isinstance(exc, TelegramForbiddenError)
                        or category in {"chat_not_found", "write_forbidden", "invalid_keyboard"}
                        or attempts >= 5
                    )
                    delay = exc.retry_after + 1 if isinstance(exc, TelegramRetryAfter) else min(300, 2**attempts * 3)
                    await self.store.db.outbox.update_one(
                        {"_id": row["_id"]},
                        {
                            "$set": {
                                "status": "failed" if failed else "pending",
                                "attempts": attempts,
                                "error_type": type(exc).__name__,
                                "error_category": category,
                                "run_at": now() + timedelta(seconds=delay),
                                "purge_at": now() + timedelta(days=30),
                            }
                        },
                    )
                    if failed:
                        logger.warning(
                            "Notification delivery failed; recipient=%s error=%s category=%s",
                            row["recipient"],
                            type(exc).__name__,
                            category,
                        )
                        await self.store.audit(
                            0, "notification_failed", recipient=row["recipient"], error_type=type(exc).__name__, error_category=category
                        )
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Notification worker iteration failed")
                await asyncio.sleep(5)
