"""Editable subscription-management and opt-in auto-call panels."""

from datetime import timedelta
import secrets

from .links import parse_link
from .plans import quota_label
from .security import Role, UserError, html
from .timeutils import now, display_time


class AutomationUI:
    async def force_gate(self, message, user_id, missing, error_type=None, fresh=False):
        rows = [[("join " + row["title"][:35], "url:" + row["join_url"])] for row in missing]
        rows += [[("✓ check membership", "fs:check")], [self.contact_button()], [("help", "nav:help")]]
        body = "<b>join before continuing</b>\n<blockquote>Join every required channel/group, then tap check membership. A pending join request is not membership.</blockquote>"
        if error_type:
            body += "\nMembership check is temporarily unavailable. Your access stays paused until it can be verified."
        if fresh:
            await self.send_start_photo(message, user_id)
        options = {"fresh": True} if fresh and self.r.config.ui_edit_panels else {}
        await message.answer(body, reply_markup=self.keyboard(*rows), **options)

    async def force_list(self, message, actor):
        rows = await self.r.force_subs.view(actor)
        owner = await self.r.access.role(actor) == Role.OWNER
        lines, buttons = [], []
        for row in rows:
            lines.append(f"{html(row['title'])} · <code>{row['_id']}</code>")
            controls = [("open " + row["title"][:25], "url:" + row["join_url"])]
            if owner:
                controls += [("remove…", "fs:remove:" + str(row["_id"]))]
            buttons.append(controls)
        if owner:
            buttons += [[("add required channel", "fs:add")]]
        buttons += [[("← manage", "nav:staff")]]
        await message.answer(
            "<b>required subscriptions</b>\n<blockquote>"
            + ("\n".join(lines) or "No required channels/groups. The gate is off.")
            + "</blockquote>\nOwners add/remove requirements; admins can view them. Staff stay exempt so the owner can repair a broken requirement.",
            reply_markup=self.keyboard(*buttons),
        )

    async def automation_form(self, actor, state, kind, **values):
        nonce = secrets.token_hex(12)
        await state.clear()
        await state.update_data(
            automation_form={"actor": actor, "nonce": nonce, "kind": kind, "expires_at": now() + timedelta(minutes=15), **values}
        )
        return nonce

    async def get_automation_form(self, actor, state, nonce, kind):
        data = (await state.get_data()).get("automation_form", {})
        if data.get("actor") != actor or data.get("nonce") != nonce or data.get("kind") != kind or data.get("expires_at", now()) <= now():
            raise UserError("This review is old or belongs to another user. Open the panel again.")
        return data

    async def force_add_prompt(self, message, actor, state):
        await self.r.access.require_staff(actor, owner_only=True)
        await state.clear()
        await state.set_state(self.Input.force_sub_input)
        await state.update_data(force_sub_input_actor=actor, force_sub_input_until=now() + timedelta(minutes=15))
        await message.answer(
            "<b>add a required channel/group</b>\n<blockquote>You and this bot must be admins there; allow invites for the bot. Send its @username or numeric chat ID. Private invite links are not accepted.\nThis requirement applies to all regular users, including Premium users.</blockquote>",
            reply_markup=self.keyboard([("cancel", "fs:view")]),
        )

    async def force_add_review(self, message, actor, state, text):
        await self.r.access.require_staff(actor, owner_only=True)
        value = text.strip()
        if value.lstrip("-").isdigit():
            value = str(int(value))
        else:
            link = parse_link(value)
            if link.kind != "public":
                raise UserError("Use @username or the numeric private-channel chat ID.")
            value = "@" + link.value
        nonce = await self.automation_form(actor, state, "force_add", value=value)
        await state.set_state(self.Input.force_sub_confirm)
        await message.answer(
            f"<b>require this channel/group?</b>\n<blockquote>Target · <code>{html(value)}</code>\nAll regular users must be members. Owner/admin staff remain exempt. The bot checks control before saving.</blockquote>",
            reply_markup=self.keyboard([("confirm requirement", "fs:confirm_add:" + nonce)], [("cancel", "fs:view")]),
        )

    async def auto_home(self, message, actor, page=0):
        page = max(0, min(100, page))
        rows = (
            await self.r.store.db.targets.find({"user_id": actor})
            .sort([("created_at", 1), ("_id", 1)])
            .skip(page * 6)
            .limit(6)
            .to_list(length=6)
        )
        total = await self.r.store.db.targets.count_documents({"user_id": actor})
        try:
            plan = await self.r.access.entitlement(actor, kind="call")
            cap = quota_label(plan, "accounts")
            allowed = self.r.config.calls_enabled and self.r.config.auto_calls_enabled
        except UserError:
            cap, allowed = 0, False
        lines, buttons = [], []
        for target in rows:
            info = target.get("auto_call", {})
            count = sum(
                len(accounts)
                for sid, accounts in self.r.auto_calls.assignments.items()
                if self.r.auto_calls.sessions.get(sid, {}).get("target_id") == target["_id"]
            )
            lines.append(
                f"{html(target['title'][:45])} · {'on' if info.get('enabled') else 'off'} · connected {count}\n{html(info.get('state', 'not enabled'))}"
            )
            if info.get("enabled"):
                buttons.append([("turn off " + target["title"][:25], "auto:off:" + target["_id"])])
            elif allowed:
                buttons.append([("enable " + target["title"][:25], "auto:review:" + target["_id"])])
        if total:
            if allowed:
                buttons += [[("enable all saved channels…", "auto:review_all")]]
            buttons += [[("turn off all my channels", "auto:off_all")]]
        navigation = []
        if page:
            navigation.append(("← previous", f"auto:home:{page - 1}"))
        if (page + 1) * 6 < total:
            navigation.append(("next →", f"auto:home:{page + 1}"))
        if navigation:
            buttons.append(navigation)
        buttons += [[("refresh", f"auto:home:{page}"), ("my channels", "targets:0")], [("🏠 home", "nav:home")]]
        await message.answer(
            "<b>automatic voice/video calls</b>\n<blockquote>"
            + ("\n\n".join(lines) or "Save your authorized channels/groups first.")
            + f"</blockquote>\nPer-channel account cap · {cap if allowed else 'no active call access'}\n"
            "Enable once for your selected saved channels. Calls are detected periodically; healthy free accounts are shared equally, within plan caps. Manual tasks have priority. Ended calls free their accounts for the remaining calls.\n"
            "Mic/camera stay off. No call is created. Checks/joins may be delayed by Telegram, busy accounts or hosting/network limits.",
            reply_markup=self.keyboard(*buttons),
        )

    async def auto_overview(self, message, actor):
        await self.r.access.require_staff(actor)
        rows = await self.r.store.db.targets.find({"auto_call.enabled": True}).sort("_id", 1).limit(15).to_list(length=15)
        total = await self.r.store.db.targets.count_documents({"auto_call.enabled": True})
        connected = sum(len(accounts) for accounts in self.r.auto_calls.assignments.values())
        lines = [
            f"{html(row['title'][:40])} · user <code>{row['user_id']}</code>\n{html(row.get('auto_call', {}).get('state', 'waiting'))} · {row.get('auto_call', {}).get('assigned_count', 0)} connected"
            for row in rows
        ]
        await message.answer(
            f"<b>automatic call overview</b>\n<blockquote>Watching · {total} channels\nConnected auto accounts · {connected}\nFree now · {len(await self.r.pool.available())}\nLast completed scan · {html(display_time(self.r.auto_calls.last_cycle_at, self.r.config.timezone))}\nLast worker error · {html(self.r.auto_calls.last_error_type or 'none')}</blockquote>\n"
            + "<blockquote>"
            + ("\n\n".join(lines) or "No users enabled automatic calls.")
            + "</blockquote>\nManual tasks have priority. Per-channel caps and permanent channel slots still apply. Individual users control their own opt-in settings.",
            reply_markup=self.keyboard([("refresh", "staff:auto_overview")], [("← manage", "nav:staff")]),
        )

    async def auto_review(self, message, actor, state, target_id=None):
        plan = await self.r.access.entitlement(actor, kind="call")
        if not self.r.config.calls_enabled or not self.r.config.auto_calls_enabled:
            raise UserError("Automatic calls are disabled on this host.")
        query = {"user_id": actor}
        if target_id:
            query["_id"] = target_id
        targets = await self.r.store.db.targets.find(query).sort("_id", 1).to_list(length=100)
        if not targets:
            raise UserError("No own saved channels selected.")
        nonce = await self.automation_form(actor, state, "auto_on", targets=[row["_id"] for row in targets])
        await state.set_state(self.Input.auto_confirm)
        names = "\n".join(html(row["title"][:45]) for row in targets[:8])
        await message.answer(
            f"<b>enable automatic calls?</b>\n<blockquote>Saved channels · {len(targets)}\n{names}\nPlan accounts · {quota_label(plan, 'accounts')} per channel; effective host ceiling · {plan['max_accounts']}. Fair share may be lower; future eligible pool accounts join later rebalances.\nWatching every ~{self.r.config.limits.auto_call_poll_seconds} seconds plus RPC pacing. Safety cap · {self.r.config.limits.max_call_minutes} minutes per detected call; never resets on redistribution/restart.</blockquote>\n"
            "You authorize owned pool accounts to join these groups through this bot's saved invites, detect active calls and connect with mic/camera off. This can leave group memberships in place after a call. You can turn auto mode off at any time. New saved channels remain off until you enable them.",
            reply_markup=self.keyboard([("enable auto mode", "auto:confirm:" + nonce)], [("cancel", "auto:home:0")]),
        )

    async def automation_callback(self, message, actor, parts, state):
        if parts[0] == "fs":
            operation = parts[1]
            if operation == "check":
                await self.r.force_subs.require(actor, force=True)
                await state.clear()
                await self.home(message, actor)
            elif operation == "view":
                await state.clear()
                await self.force_list(message, actor)
            elif operation == "add":
                await self.force_add_prompt(message, actor, state)
            elif operation == "confirm_add":
                form = await self.get_automation_form(actor, state, parts[2], "force_add")
                row = await self.r.force_subs.add(actor, form["value"])
                await state.clear()
                await message.answer(
                    f"<b>requirement saved</b>\n<blockquote>{html(row['title'])}</blockquote>",
                    reply_markup=self.keyboard([("required channels", "fs:view")]),
                )
            elif operation == "remove":
                await self.r.access.require_staff(actor, owner_only=True)
                row = await self.r.store.db.force_subs.find_one({"_id": int(parts[2])})
                if not row:
                    raise UserError("Requirement not found.")
                nonce = await self.automation_form(actor, state, "force_remove", chat_id=row["_id"])
                await state.set_state(self.Input.force_sub_confirm)
                await message.answer(
                    f"<b>remove required subscription?</b>\n<blockquote>{html(row['title'])}\nThis stops requiring membership; it does not remove existing members. A bot-created private invite is revoked.</blockquote>",
                    reply_markup=self.keyboard([("confirm removal", "fs:confirm_remove:" + nonce)], [("cancel", "fs:view")]),
                )
            elif operation == "confirm_remove":
                form = await self.get_automation_form(actor, state, parts[2], "force_remove")
                await self.r.force_subs.remove(actor, form["chat_id"])
                await state.clear()
                await self.force_list(message, actor)
            else:
                raise UserError("Old required-subscription button. Open /start.")
            return True
        if parts[0] == "auto":
            operation = parts[1]
            if operation == "home":
                await state.clear()
                await self.auto_home(message, actor, int(parts[2]) if len(parts) > 2 else 0)
            elif operation in {"review", "review_all"}:
                await self.auto_review(message, actor, state, parts[2] if operation == "review" else None)
            elif operation == "confirm":
                form = await self.get_automation_form(actor, state, parts[2], "auto_on")
                await self.r.auto_calls.set_enabled(actor, form["targets"], True)
                await state.clear()
                await self.auto_home(message, actor)
            elif operation in {"off", "off_all"}:
                ids = (
                    [parts[2]]
                    if operation == "off"
                    else [row["_id"] for row in await self.r.store.db.targets.find({"user_id": actor}).to_list(length=100)]
                )
                await self.r.auto_calls.set_enabled(actor, ids, False)
                await state.clear()
                await self.auto_home(message, actor)
            else:
                raise UserError("Old automatic-call button. Open /start.")
            return True
        return False

    async def automation_message(self, message, actor, state, text):
        if await state.get_state() == self.Input.force_sub_input.state:
            data = await state.get_data()
            if data.get("force_sub_input_actor") != actor or data.get("force_sub_input_until", now()) <= now():
                await state.clear()
                raise UserError("Required-subscription input expired. Open the owner panel again.")
            await self.force_add_review(message, actor, state, text)
            return True
        return False
