"""Authored remediation only: never display a Telegram exception message."""

from collections import Counter

ERROR_HINTS = {
    "InvalidBufferError": "Telegram returned an invalid transport buffer. Saved authorization is retained; inspect the safe numeric transport code and respected cooldown, not packet contents. This is not by itself proof of a ban.",
    "AuthKeyNotFound": "Telegram's transport does not recognize the key; this may be temporary or permanent. Keep the encrypted session/original key; paced recovery does not request OTP automatically.",
    "CallCleanupOffline": "Telegram transport is offline. Only owned local native cleanup is attempted; the encrypted session remains saved for paced recovery.",
    "MTProtoClientNotConnected": "The Telegram transport is offline. Owned local native cleanup and paced saved-session recovery are used; this alone does not mean the account logged out.",
    "AuthKeyUnregisteredError": "Stored session is no longer authorized. Sign this account in again.",
    "AuthKeyDuplicatedError": "Telegram invalidated a duplicated authorization (parallel main connections can conflict even on one IP). Stop all copies, review session safety, then authorize a new sign-in. Keeping/restoring the old key cannot repair it.",
    "SessionRevokedError": "The account session was revoked. Sign in again; do not reuse the old session.",
    "SessionExpiredError": "The account session expired. Sign in again.",
    "NotInCallError": "Native call is already absent; a verified empty transport does not log out the Telegram account.",
    "TransportCleanupPending": "Previous local transport cleanup is still uncertain. It stays owned and paced recovery retries before any replacement is attached.",
    "SessionDecryptError": "Restore the original session encryption key/database; the saved encrypted data has not been erased.",
    "SessionIdentityMismatch": "Saved session identity did not match. Automation is blocked and encrypted data is retained for staff review.",
    "UserDeactivatedError": "Telegram deactivated this account. It cannot be used for this task.",
    "UserDeactivatedBanError": "Telegram banned/deactivated this account. Do not retry or bypass the restriction.",
    "UserBannedInChannelError": "This account is banned in the target. Moderator restrictions are respected.",
    "ChannelsTooMuchError": "This account reached Telegram's joined-channel limit. Review its memberships manually.",
    "ChannelPrivateError": "This account cannot access the target. Check its approved membership and saved target access.",
    "InviteHashExpiredError": "Managed invite expired. Ask staff to repair the authorized target/invite.",
    "InviteHashInvalidError": "Managed invite is invalid/revoked. Ask staff to repair it.",
    "UsernameInvalidError": "Public username is invalid. Verify the saved target's current username.",
    "UsernameNotOccupiedError": "Public username no longer resolves. Verify the target's current username.",
    "FloodWaitError": "Telegram requested a cooldown. The account will not retry before the deadline.",
    "TelegramRetryAfter": "Bot API requested a rate pause. Retry only after Telegram's deadline.",
    "ConnectionError": "Temporary connection failure. The saved session is retained; automatic paced recovery will retry without requesting OTP.",
    "TimeoutError": "A bounded request timed out, not an automatic logout. Saved sessions are retained; uncertain call cleanup is quarantined before safe recovery.",
    "CallCleanupUncertain": "An uncertain local call transport is quarantined. Automatic cleanup/reconnect will retry after cooldown; the saved Telegram session is not deleted.",
    "CallAdapterStartupUncertain": "Native adapter startup was uncertain. The saved session is retained; automatic safe cleanup/recovery retries after cooldown. Check host RTC compatibility if repeated.",
}


def result_explanation(result):
    error_type = result.get("error_type") or result.get("last_error_type")
    if error_type == "UserError" and result.get("detail"):
        return result["detail"][:180]  # Authored validation error, not an RPC message.
    if error_type:
        return ERROR_HINTS.get(error_type, "See the protected error type and sanitized logs; no success is assumed.")
    if result.get("status") in {"request_sent", "awaiting_approval"}:
        return "Request sent, not joined yet. The target admin must approve it."
    return ""


def error_counts(results):
    return Counter(
        row.get("error_type") or row.get("last_error_type") for row in results if row.get("error_type") or row.get("last_error_type")
    )


def error_overview(results):
    return "; ".join(f"{name}: {count}" for name, count in sorted(error_counts(results).items()))
