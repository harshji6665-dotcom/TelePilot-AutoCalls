"""Owner-reviewed, audited resume; staff can view, users cannot mutate safety."""

from datetime import timedelta
import secrets

from .security import Role, UserError
from .session_safety import DUPLICATE_QUERY
from .timeutils import now


class SessionSafetyUI:
    async def session_safety(self, message, actor, state=None, review=False):
        role = await self.r.access.require_staff(actor)
        guard = self.r.pool.safety
        affected = await self.r.store.db.accounts.count_documents(DUPLICATE_QUERY)
        text = (
            "<b>session safety</b>\n<blockquote>"
            f"account traffic · {'paused for review' if guard.paused else 'not safety-paused'}\n"
            f"duplicated authorizations recorded · {affected}\n"
            "Telegram invalidated duplicated keys; this is not a temporary network error or necessarily an account ban. "
            "Old keys cannot be made valid by restoring a backup or changing the encryption key.</blockquote>\n\n"
            "Stop all other bot/session copies: old deployments, staging services, local scripts, extra containers and copied databases. "
            "One main connection per saved authorization must be enforced, even on the same IP. "
            "Use the read-only safety report; it cannot prove no other host exists. "
            "Only after resolving the cause should the owner resume and reauthenticate affected accounts one at a time. "
            "Valid saved accounts and all original private data stay retained."
        )
        rows = [[("refresh safety", "sg:view")], [("← manage", "nav:staff")]]
        if guard.paused and role == Role.OWNER:
            rows.insert(0, [("review before resume", "sg:review")])
        if review:
            await self.r.access.require_staff(actor, owner_only=True)
            if not guard.paused or not state:
                raise UserError("No current safety pause is available for review.")
            nonce = secrets.token_hex(6)
            await state.update_data(
                session_safety_review={"actor": actor, "epoch": guard.epoch, "nonce": nonce, "expires_at": now() + timedelta(minutes=5)}
            )
            text += "\n\n<b>owner confirmation</b>\n<blockquote>Confirm ONLY after you have stopped every conflicting copy and reviewed the deployment. This does not repair revoked keys, prove your network safe, clear bans or request OTP. Stale confirmations are rejected; local cleanup must be complete.</blockquote>"
            rows.insert(0, [("i stopped other copies · resume", "sg:confirm:" + nonce)])
        await message.answer(text, reply_markup=self.keyboard(*rows))

    async def session_safety_callback(self, message, actor, parts, state):
        await self.r.access.require_staff(actor)
        if parts == ["sg", "view"]:
            await self.session_safety(message, actor, state)
        elif parts == ["sg", "review"]:
            await self.session_safety(message, actor, state, review=True)
        elif len(parts) == 3 and parts[1] == "confirm":
            await self.r.access.require_staff(actor, owner_only=True)
            review = (await state.get_data()).get("session_safety_review", {})
            if review.get("actor") != actor or review.get("nonce") != parts[2] or (review.get("expires_at") or now()) <= now():
                raise UserError("Safety confirmation expired or belongs to another owner. Review the current incident again.")
            await self.r.pool.safety.resume(actor, review.get("epoch"))
            await state.clear()
            await message.answer(
                "<blockquote>Owner review recorded. Valid saved sessions may recover; confirmed duplicated/revoked keys remain blocked until authorized sign-in. No original data was deleted and no automatic login was requested.</blockquote>"
            )
            await self.session_safety(message, actor, state)
        else:
            raise UserError("Unknown session safety control.")
