"""Saved authorizations are not transport connections: never erase on failure."""

import hashlib
import random

from telethon import errors
from telethon.sessions import StringSession

AUTH_BLOCKED = frozenset({"revoked", "banned", "deactivated", "reauth_required", "storage_error"})
RECOVERY_BLOCKED = AUTH_BLOCKED - {"storage_error"}
CONFIRMED_BANS = (errors.UserDeactivatedBanError, errors.PhoneNumberBannedError)


def auth_status(exc):
    if isinstance(exc, CONFIRMED_BANS):
        return "banned"
    if isinstance(exc, errors.UserDeactivatedError):
        return "deactivated"
    return "revoked"


def session_guard(row):
    """CAS fence: an old connection cannot damage a newly saved authorization."""
    if row.get("session_generation"):
        return {"session_generation": row["session_generation"]}
    return {"session_generation": None, "session_ciphertext": row.get("session_ciphertext")}


def session_value(client):
    session = getattr(client, "session", None)
    if not isinstance(session, StringSession):
        return None
    value = StringSession.save(session)
    return value or None


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest() if value else None


def recovery_delay(failures):
    # Bounded reconnect, not OTP/authentication retry or Telegram-limit evasion.
    base = min(900, 60 * 2 ** min(max(0, failures - 1), 4))
    return min(900, base + random.uniform(0, base * 0.15))


def recovery_hint(row):
    status = row.get("status", "offline")
    if not row.get("session_ciphertext"):
        if status == "banned":
            return "Telegram reported an account ban. Do not bypass it. No encrypted session remains in this database; this update cannot reconstruct erased data."
        if status == "deactivated":
            return "Telegram reported a deactivated/deleted account. No encrypted session remains here. Review the account through Telegram's official tools."
        return "No encrypted session remains in this database. This update cannot reconstruct erased data. A compatible backup helps only if Telegram still accepts it; otherwise an authorized new sign-in is needed."
    if status == "healthy":
        return "Saved session connected. No new sign-in is needed."
    if status == "disabled":
        return "Disabled by staff. Saved authorization is retained; enable it to reconnect."
    if status == "banned":
        return "Telegram reported an account ban. Automation is disabled; do not bypass the restriction. Saved encrypted data is retained for staff review."
    if status == "deactivated":
        return "Telegram reported this account deactivated/deleted, not a network logout. Automation is blocked; review the account in Telegram."
    if status == "revoked" and (
        row.get("authorization_error_type") == "AuthKeyDuplicatedError" or row.get("last_error_type") == "AuthKeyDuplicatedError"
    ):
        return "Telegram invalidated this duplicated authorization key. Stop conflicting session copies/main connections first, then review session safety and sign in again with permission. A backup/encryption-key change cannot revive this key. No data was deleted; this is not necessarily an account ban."
    if status == "revoked":
        return "Telegram rejected/revoked this authorization. Its encrypted record is retained, but the server may require a new sign-in. No automatic OTP is requested."
    if status == "storage_error":
        return "Saved session needs local validation. Restore the ORIGINAL encryption key/database; automatic paced validation retries without requesting OTP. Do not replace or delete the saved data."
    if status == "reauth_required":
        return "The saved identity needs staff review/sign-in. The existing encrypted session has not been deleted."
    if row.get("last_error_code") == 429:
        return "Telegram reported a transport-level rate restriction. The saved session is retained; recovery waits at least the local transport cooldown and never shortens a Telegram wait. Do not request repeated OTPs or bypass limits."
    if row.get("last_error_code") == 404:
        return "Telegram's transport did not recognize this authorization key. This can be temporary or permanent, not proof of a ban. The encrypted session is retained for paced validation; persistent rejection may need an authorized sign-in."
    if row.get("last_error_type") == "TransportCleanupPending":
        return "Local cleanup is not confirmed. Automatic safe cleanup/recovery will retry; this identity is not reused until cleanup finishes. Saved authorization is retained."
    return "Temporary connection/cooldown, not a logout. Saved authorization is retained; automatic reconnect uses backoff and respects Telegram waits. No OTP is needed if Telegram still accepts it."


class DurableStringSession(StringSession):
    """Notify the owner when Telethon saves DC/key changes; no plaintext logging.

    The callback only schedules an identity-validated, CAS-fenced encrypted
    checkpoint. Empty intermediate migration keys are never checkpointed.
    """

    on_save = None

    def save(self):
        value = super().save()
        if value and self.on_save:
            self.on_save()
        return value
