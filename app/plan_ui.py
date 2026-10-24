"""Editable, staff-only subscription and locked-channel correction forms."""

from datetime import timedelta
import secrets

from .plans import FEATURE_PLANS, feature_label, UNLIMITED, quota_choice
from .security import UserError, html
from .timeutils import now, display_time


class PlanUI:
    async def premium_help(self, message, user_id):
        await self.r.access.require_staff(user_id)
        await message.answer(
            "<b>💎 premium setup guide</b>\n\n"
            "<blockquote>Choose channels only, calls only or both. Set how many channel/group slots the user gets, then the account limit and duration. Saved channels stay locked, including after expiry. Only staff can correct them. One group/channel is one slot, even when both features use it.</blockquote>\n\n"
            "Use <code>unlimited</code> independently for channel slots and/or accounts. It covers future pool additions, subject to host safety ceilings and Telegram rules. Manual tasks keep their reviewed count; automatic calls rebalance.\n\n"
            "<b>command format</b>\n<code>/premium USER_ID DAYS PLAN CHANNELS ACCOUNTS set|extend</code>\n\n"
            "<b>calls only · 1 channel · 5 accounts · 30 days</b>\n<code>/premium 123456789 30 calls 1 5 set</code>\n\n"
            "<b>channels only · 2 channels · 3 accounts</b>\n<code>/premium 123456789 30 channels 2 3 set</code>\n\n"
            "<b>both · 3 channels · 5 accounts · renew 15 days</b>\n<code>/premium 123456789 15 both 3 5 extend</code>\n\n"
            "<b>unlimited channels + accounts</b>\n<code>/premium 123456789 30 both unlimited unlimited set</code>\n\n"
            "<b>2 channels + all current/future pool accounts</b>\n<code>/premium 123456789 30 calls 2 unlimited set</code>\n\n"
            "<b>unlimited channels + 5 accounts</b>\n<code>/premium 123456789 30 channels unlimited 5 set</code>\n\n"
            "<code>set</code> starts from today; <code>extend</code> adds days after the later of today/current expiry. Omitted quotas on short renewals retain finite or unlimited modes; old short commands retain features; a first short grant defaults to both + 1 channel. No automatic payment check.",
            reply_markup=self.keyboard(
                [("give premium", "staff:grant"), ("channel corrections", "staff:channels")], [("← manage", "nav:staff")]
            ),
        )

    async def plan_setup(self, message, user_id, state, target=None):
        await self.r.access.require_staff(user_id)
        await state.clear()
        await state.update_data(plan_created=now(), plan_key=secrets.token_hex(12), plan_target=target)
        if target is None:
            await state.set_state(self.Input.grant_user)
            await message.answer(
                "<b>give premium</b>\nSend the user’s numeric Telegram ID. They can find it with <code>/id</code>.\n\nCommand example: <code>/premium 123456789 30 calls 1 5 set</code>",
                reply_markup=self.keyboard([("📖 examples", "staff:premium_help")], [("cancel", "nav:staff")]),
            )
        else:
            await self.grant_feature_prompt(message, state)

    async def plan_draft(self, state):
        data = await state.get_data()
        if not data.get("plan_created") or data["plan_created"] < now() - timedelta(minutes=15):
            await state.clear()
            raise UserError("Premium form expired. Open give premium and start again.")
        return data

    async def grant_feature_prompt(self, message, state):
        data = await self.plan_draft(state)
        await state.set_state(self.Input.grant_feature)
        await message.answer(
            f"<b>choose a feature plan</b>\n<blockquote>User · <code>{data['plan_target']}</code>\nOnly included feature buttons will appear. Old buttons and tasks are checked too.</blockquote>",
            reply_markup=self.keyboard(
                [("📥 channels only", "grant:feature:channels")],
                [("🎧 calls only", "grant:feature:calls")],
                [("✦ both", "grant:feature:both")],
                [("cancel", "nav:staff")],
            ),
        )

    async def grant_days_prompt(self, message, state):
        await state.set_state(self.Input.grant_days)
        await message.answer(
            "<b>how many days?</b>\nSend a number from 1 to 365, or choose below.",
            reply_markup=self.keyboard(
                [("7 days", "grant:days:7"), ("30 days", "grant:days:30"), ("90 days", "grant:days:90")], [("cancel", "nav:staff")]
            ),
        )

    async def grant_channels_prompt(self, message, state):
        data = await self.plan_draft(state)
        saved = await self.r.store.db.targets.count_documents({"user_id": data["plan_target"]})
        cap = self.r.config.limits.max_channels_per_user
        await state.set_state(self.Input.grant_channels)
        values = sorted({n for n in (1, 2, 3, 5, saved) if max(1, saved) <= n <= cap})
        await message.answer(
            f"<b>how many channel/group slots?</b>\n<blockquote>Already saved · {saved}\nNumber · 1–{cap}, or unlimited\nHost safety ceiling · {cap}\nOnce saved, a channel is locked. Users cannot remove it to reuse the slot.</blockquote>\nSend a number or unlimited, or choose below.",
            reply_markup=self.keyboard(
                *([[(str(n), f"grant:channels:{n}") for n in values]] if values else []),
                [("unlimited channels", "grant:channels:unlimited")],
                [("cancel", "nav:staff")],
            ),
        )

    async def grant_accounts_prompt(self, message, state):
        await state.set_state(self.Input.grant_accounts)
        cap = self.r.config.limits.max_pool_accounts
        values = sorted({1, min(3, cap), min(self.r.config.limits.default_plan_accounts, cap), cap})
        await message.answer(
            f"<b>accounts per task</b>\n<blockquote>Number · 1–{cap}, or unlimited\nHost safety ceiling · {cap}\nUnlimited includes future eligible pool additions. This is the number of signed-in pool accounts, not the number of channels.</blockquote>\nSend a number or unlimited, or choose below.",
            reply_markup=self.keyboard(
                [(str(n), f"grant:accounts:{n}") for n in values],
                [("unlimited accounts", "grant:accounts:unlimited")],
                [("cancel", "nav:staff")],
            ),
        )

    async def grant_mode_prompt(self, message, state):
        await state.set_state(self.Input.grant_mode)
        await message.answer(
            "<b>start or renew?</b>\n<blockquote>Start today replaces the expiry. Extend keeps remaining days and adds the new duration.</blockquote>",
            reply_markup=self.keyboard(
                [("start today", "grant:mode:set"), ("extend current plan", "grant:mode:extend")], [("cancel", "nav:staff")]
            ),
        )

    async def grant_review(self, message, state):
        data = await self.plan_draft(state)
        await state.set_state(self.Input.grant_confirm)
        await message.answer(
            f"<b>review premium</b>\n<blockquote>User · <code>{data['plan_target']}</code>\nFeatures · <b>{html(feature_label(data['feature_plan']))}</b>\nLocked channels/groups · <b>{data['channel_limit']}</b>\nAccounts per task · <b>{data['max_accounts']}</b>\nDuration · {data['days']} days\nMode · <code>{data['mode']}</code></blockquote>\nChanging the feature plan stops tasks that are no longer included. A limit cannot be lower than the channels already saved.",
            reply_markup=self.keyboard([("✅ confirm premium", "grant:confirm:" + data["plan_key"])], [("cancel", "nav:staff")]),
        )

    async def grant_value(self, message, state, operation, value, actor):
        data = await self.plan_draft(state)
        expected = {
            "feature": self.Input.grant_feature,
            "days": self.Input.grant_days,
            "channels": self.Input.grant_channels,
            "accounts": self.Input.grant_accounts,
            "mode": self.Input.grant_mode,
            "confirm": self.Input.grant_confirm,
        }
        if operation not in expected or await state.get_state() != expected[operation].state:
            raise UserError("This premium button is old. Open give premium again.")
        if operation == "feature":
            if value not in FEATURE_PLANS:
                raise UserError("Choose channels, calls or both.")
            await state.update_data(feature_plan=value)
            await self.grant_days_prompt(message, state)
        elif operation in ("days", "channels", "accounts"):
            value = value.strip().lower()
            cap = {"days": 365, "channels": self.r.config.limits.max_channels_per_user, "accounts": self.r.config.limits.max_pool_accounts}[
                operation
            ]
            if operation == "days":
                if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= cap:
                    raise UserError("Choose a number from 1 to 365.")
                number = int(value)
            else:
                number = quota_choice(value, cap, operation.title() + " limit")
            if operation == "channels" and number is not None:
                saved = await self.r.store.db.targets.count_documents({"user_id": data["plan_target"]})
                if number < saved:
                    raise UserError(f"{saved} channels are already locked. Choose at least {saved}, or make a staff correction first.")
            await state.update_data(
                **{
                    {"days": "days", "channels": "channel_limit", "accounts": "max_accounts"}[operation]: UNLIMITED
                    if number is None
                    else number
                }
            )
            await {"days": self.grant_channels_prompt, "channels": self.grant_accounts_prompt, "accounts": self.grant_mode_prompt}[
                operation
            ](message, state)
        elif operation == "mode":
            if value not in ("set", "extend"):
                raise UserError("Choose start today or extend.")
            await state.update_data(mode=value)
            await self.grant_review(message, state)
        else:
            if value != data["plan_key"]:
                raise UserError("Premium confirmation is unavailable.")
            expires = await self.r.plans.grant(
                actor,
                data["plan_target"],
                data["days"],
                data["max_accounts"],
                data["mode"],
                data["feature_plan"],
                data["channel_limit"],
                request_key=data["plan_key"],
            )
            await state.clear()
            await message.answer(
                f"<b>✅ premium saved</b>\n<blockquote>User · <code>{data['plan_target']}</code>\nFeatures · {html(feature_label(data['feature_plan']))}\nChannel limit · {data['channel_limit']}\nAccounts per task · {data['max_accounts']}\nUntil · {html(display_time(expires, self.r.config.timezone))}</blockquote>\nOwner/user notices are queued.",
                reply_markup=self.keyboard([("give another plan", "staff:grant"), ("← manage", "nav:staff")]),
            )

    async def grant_callback(self, message, user_id, state, parts):
        await self.r.access.require_staff(user_id)
        if len(parts) != 3:
            raise UserError("Invalid premium button.")
        await self.grant_value(message, state, parts[1], parts[2], user_id)

    async def grant_message(self, message, user_id, state, text):
        current = await state.get_state()
        supported = {
            self.Input.grant_user.state: "user",
            self.Input.grant_days.state: "days",
            self.Input.grant_channels.state: "channels",
            self.Input.grant_accounts.state: "accounts",
        }
        if current not in supported:
            return False
        await self.r.access.require_staff(user_id)
        if supported[current] == "user":
            if not text.isascii() or not text.isdigit() or not 0 < int(text) < 2**63:
                raise UserError("Send a positive numeric Telegram user ID.")
            await self.plan_draft(state)
            await state.update_data(plan_target=int(text))
            await self.grant_feature_prompt(message, state)
        else:
            await self.grant_value(message, state, supported[current], text, user_id)
        return True

    async def staff_channels(self, message, actor, target_user, page=0):
        await self.r.access.require_staff(actor)
        page = max(0, min(100, page))
        rows = (
            await self.r.store.db.targets.find({"user_id": target_user})
            .sort([("created_at", 1), ("_id", 1)])
            .skip(page * 8)
            .limit(8)
            .to_list(length=8)
        )
        count = await self.r.store.db.targets.count_documents({"user_id": target_user})
        lines = [f"🔒 {html(row['title'][:50])} · <code>{row['chat_id']}</code>" for row in rows]
        buttons = [[(row["title"][:45], f"tfix:view:{target_user}:{row['_id']}")] for row in rows]
        nav = []
        if page:
            nav.append(("← previous", f"tfix:list:{target_user}:{page - 1}"))
        if (page + 1) * 8 < count:
            nav.append(("next →", f"tfix:list:{target_user}:{page + 1}"))
        if nav:
            buttons.append(nav)
        buttons.extend([[("premium settings", f"plan:edit:{target_user}")], [("← manage", "nav:staff")]])
        await message.answer(
            f"<b>🔒 channel corrections</b>\nUser · <code>{target_user}</code>\nSaved · {count}\n<blockquote>"
            + ("\n".join(lines) or "No saved channels.")
            + "</blockquote>\nStaff corrections revoke saved invites and free a slot. All corrections require a reason and are audited.",
            reply_markup=self.keyboard(*buttons),
        )

    async def correction_callback(self, message, actor, state, parts):
        await self.r.access.require_staff(actor)
        if len(parts) == 4 and parts[1] in ("list", "view", "reason"):
            target_user = int(parts[2])
            value = parts[3]
            if parts[1] == "list":
                await state.clear()
                return await self.staff_channels(message, actor, target_user, int(value))
            target = await self.r.targets.get(target_user, value)
            if parts[1] == "view":
                await state.clear()
                return await message.answer(
                    f"<b>correct a locked channel?</b>\n<blockquote>User · <code>{target_user}</code>\nChannel · {html(target['title'][:64])}\nID · <code>{target['chat_id']}</code></blockquote>\nRemoving it revokes its saved invites and lets the user fill that slot again. Stop its tasks first.",
                    reply_markup=self.keyboard(
                        [("remove for correction", f"tfix:reason:{target_user}:{value}")], [("cancel", f"tfix:list:{target_user}:0")]
                    ),
                )
            await state.clear()
            await state.set_state(self.Input.correction_reason)
            await state.update_data(
                correction_user=target_user, correction_target=value, correction_key=secrets.token_hex(12), correction_created=now()
            )
            return await message.answer(
                "<b>why is this correction needed?</b>\nSend a reason of 5–200 characters. It is saved to the audit. Do not send credentials.",
                reply_markup=self.keyboard([("cancel", f"tfix:list:{target_user}:0")]),
            )
        if len(parts) == 3 and parts[1] == "confirm":
            data = await state.get_data()
            if (
                await state.get_state() != self.Input.correction_confirm.state
                or data.get("correction_key") != parts[2]
                or data.get("correction_created", now() - timedelta(days=1)) < now() - timedelta(minutes=15)
            ):
                raise UserError("Channel correction expired. Start again from manage bot.")
            await self.r.targets.staff_remove(actor, data["correction_user"], data["correction_target"], data["correction_reason"])
            await state.clear()
            return await self.staff_channels(message, actor, data["correction_user"])
        raise UserError("Invalid channel correction button.")

    async def correction_message(self, message, actor, state, text):
        current = await state.get_state()
        if current not in (self.Input.correction_user.state, self.Input.correction_reason.state):
            return False
        await self.r.access.require_staff(actor)
        if current == self.Input.correction_user.state:
            if not text.isascii() or not text.isdigit() or not 0 < int(text) < 2**63:
                raise UserError("Send a positive numeric user ID.")
            await state.clear()
            await self.staff_channels(message, actor, int(text))
            return True
        data = await state.get_data()
        if data.get("correction_created", now() - timedelta(days=1)) < now() - timedelta(minutes=15):
            raise UserError("Correction form expired. Start again.")
        if not 5 <= len(text) <= 200:
            raise UserError("Send a reason of 5–200 characters. Do not include secrets.")
        await state.update_data(correction_reason=text)
        await state.set_state(self.Input.correction_confirm)
        await message.answer(
            "<b>confirm staff correction</b>\nReason · "
            + html(text)
            + "\n\nThe channel is removed, its invites revoked and the slot freed. The user is notified.",
            reply_markup=self.keyboard(
                [("✅ confirm correction", "tfix:confirm:" + data["correction_key"])],
                [("cancel", f"tfix:list:{data['correction_user']}:0")],
            ),
        )
        return True
