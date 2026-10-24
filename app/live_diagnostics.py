"""Bounded live observations INSIDE the existing, authorized singleton runtime.

No new account clients, OTP, call joins/leaves, recording or session export.
Only aggregate, closed-schema evidence is published for the host-side reader.
"""

import asyncio
import hmac
import json
from collections import Counter
from hashlib import sha256

from telethon import errors

from . import __version__
from .timeutils import now

REPORT_SETTING = "host_verification_report"
REPORT_SCHEMA = 1
HEALTH_STATUSES = frozenset({"running", "complete", "partial", "failed", "stopped"})
ACCOUNT_STATUSES = frozenset(
    {"healthy", "offline", "cooldown", "disabled", "revoked", "banned", "deactivated", "reauth_required", "storage_error", "removed"}
)
CALL_STATUSES = frozenset({"verified", "not_checked", "not_present", "cooldown", "failed"})


def bot_reference(ident):
    return sha256(f"telegram-bot:{ident}".encode()).hexdigest() if type(ident) is int and ident > 0 else None


def runtime_reference(instance):
    return sha256(instance.encode()).hexdigest()


def configuration_reference(config, instance):
    # Private, per-runtime keyed attestation, not exported by the reader. This
    # detects a replaced key/config file before a restart loses saved access.
    payload = {
        "runtime": runtime_reference(instance),
        "version": __version__,
        "api_id": config.api_id,
        "api_hash": config.api_hash.get_secret_value(),
        "bot_token": config.bot_token.get_secret_value(),
        "mongo_uri": config.mongo_uri.get_secret_value(),
        "database": config.mongo_database,
        "owners": sorted(config.owner_ids),
        "login_mode": config.login_mode,
        "calls_enabled": config.calls_enabled,
        "auto_calls_enabled": config.auto_calls_enabled,
        "http_port": config.http_port,
        "limits": config.limits.model_dump(),
    }
    return hmac.new(
        config.session_encryption_key.get_secret_value().encode(),
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        "sha256",
    ).hexdigest()


async def observe_existing_call(runtime, budget=15):
    """Sample ONE already-managed call using the current pool clients only.

    A presence observation requires the same managed call ID, native binding
    presence and Telegram's own non-left self participant. It does not certify
    media quality or future uninterrupted attendance. Busy identity scans remain
    skipped; this separate read-only sample is explicit staff health work.
    """
    result = {"status": "not_checked", "sampled": 0, "native_transport": False, "server_self_participant": False}
    if not runtime.config.calls_enabled or not runtime.ready or runtime.stopping or not getattr(runtime, "leader", True):
        return result
    try:
        async with asyncio.timeout(budget):
            for slot in list(runtime.pool.slots.values()):
                if slot.closing or slot.disconnected or not slot.call_client or not slot.busy_job:
                    continue
                assignment = slot.busy_job
                if assignment.startswith("auto:"):
                    auto = getattr(runtime, "auto_calls", None)
                    sid = assignment[5:]
                    session = auto.sessions.get(sid) if auto else None
                    if not session or auto.assignments.get(sid, {}).get(slot.account_id) is not slot:
                        continue
                    if session.get("terminal") or session["deadline"] <= now():
                        continue
                    target = session["target"]
                    await auto.allowed(target, control=True)
                    chat_id, expected = session["chat_id"], session["call_id"]
                else:
                    engine = getattr(runtime, "jobs", None)
                    if not engine:
                        continue
                    job = await runtime.store.db.jobs.find_one(
                        {"_id": assignment, "kind": "call", "status": "running", "cancel_requested": False}
                    )
                    if not job or not job.get("expected_call_id") or not job.get("end_at") or job["end_at"] <= now():
                        continue
                    await engine.allowed(job, recheck_target=True)
                    chat_id, expected = job["chat_id"], job["expected_call_id"]
                if chat_id in slot.joining_chats | slot.leaving_chats | slot.forbidden_chats:
                    continue
                result["sampled"] = 1
                if not await runtime.pool.in_call(slot, chat_id):
                    result["status"] = "not_present"
                    return result
                result["native_transport"] = True
                call = await runtime.pool.get_call(slot, chat_id)
                if not call or call.id != expected:
                    result["status"] = "not_present"
                    return result
                present = await runtime.pool.can_rejoin(slot, call)
                result["server_self_participant"] = bool(present)
                # The normal job may finish while the read requests are pending.
                valid = (
                    runtime.pool.slots.get(slot.account_id) is slot
                    and slot.busy_job == assignment
                    and not slot.closing
                    and not slot.disconnected
                )
                valid = valid and chat_id not in slot.joining_chats | slot.leaving_chats | slot.forbidden_chats
                result["native_transport"] = bool(valid and await runtime.pool.in_call(slot, chat_id))
                result["status"] = "verified" if present and result["native_transport"] else "not_present"
                return result
    except errors.FloodWaitError:
        result["status"] = "cooldown"  # pool.rpc already persists the wait; never retry here.
    except Exception:
        result["status"] = "failed"  # No raw exception text, IDs, peers or requests enter evidence.
    return result


def health_evidence(runtime, state):
    """Project, never copy arbitrary UI/result dictionaries into the export."""
    rows = state.get("accounts", [])
    verified = sum(row.get("identity_verified") is True and row.get("status") == "healthy" and not row.get("error_type") for row in rows)
    counts = Counter(row.get("status") if row.get("status") in ACCOUNT_STATUSES else "other" for row in rows)
    components = state.get("components", {})
    native = state.get("call_observation") or {}
    call = {
        "status": native.get("status") if native.get("status") in CALL_STATUSES else "not_checked",
        "sampled": int(native.get("sampled") == 1),
        "native_transport": native.get("native_transport") is True,
        "server_self_participant": native.get("server_self_participant") is True,
    }
    return {
        "schema_version": REPORT_SCHEMA,
        "code_version": __version__,
        "runtime_reference": runtime_reference(runtime.store.instance),
        "configuration_reference": configuration_reference(runtime.config, runtime.store.instance),
        "bot_reference": state.get("_bot_reference"),
        "finished_at": state["finished_at"],
        "scan_status": state["status"] if state.get("status") in HEALTH_STATUSES else "failed",
        "database_connected": components.get("database") == "connected",
        "bot_api_connected": components.get("bot api") == "connected",
        "workers_running": components.get("workers") == "running",
        "accounts_reviewed": len(rows),
        "accounts_self_verified": verified,
        "account_status_counts": dict(counts),
        "call_observation": call,
        "session_safety": {
            "paused": runtime.pool.safety.paused,
            "wire_fence_enabled": runtime.store.lease_fence_enabled,
            "ownership_valid": runtime.store.lease_valid(),
        },
    }
