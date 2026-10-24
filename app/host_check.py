"""Read-only host verifier. NEVER constructs or decrypts a Telegram user session.

Run in the EXISTING app container/environment, not a second app runtime. The
only Bot API action is getMe. User-session/call evidence is read from a fresh,
closed-schema report emitted by staff /health in the existing singleton.
"""

import argparse
import asyncio
from datetime import datetime, timedelta
import json
import sys

import httpx
from aiogram import Bot

from . import __version__
from .config import load_config, POOL_ACCOUNT_CEILING
from .live_diagnostics import REPORT_SCHEMA, REPORT_SETTING, runtime_reference, bot_reference, configuration_reference
from .logging_setup import configure_logging
from .store import Store
from .session_safety import SAFETY_SETTING, DUPLICATE_QUERY
from .deployment_audit import local_deployment_observations
from .timeutils import now

MANUAL_CHECKS = (
    "start_response_and_original_photo",
    "private_chat_signin_otp_exact_2fa",
    "qr_approval_when_used",
    "saved_session_reconnect_without_new_otp",
    "owned_call_start_stop_preserves_session",
    "roles_plans_and_target_restrictions",
)
HEALTH_FIELDS = (
    "schema_version",
    "code_version",
    "runtime_reference",
    "configuration_reference",
    "bot_reference",
    "finished_at",
    "scan_status",
    "database_connected",
    "bot_api_connected",
    "workers_running",
    "accounts_reviewed",
    "accounts_self_verified",
    "call_observation",
    "session_safety",
)


def check(status, reason=None, **fields):
    result = {"status": status, **fields}
    if reason:
        result["reason"] = reason
    return result


def safe_count(value):
    return value if type(value) is int and 0 <= value <= 1_000_000 else 0


def evaluate_health(evidence, lease, reference, expected_bot, max_age, expected_configuration=None):
    """Never echo arbitrary stored dictionaries, IDs, hashes, messages or types."""
    missing = {
        "runtime_health": check("incomplete", "run_health_in_the_existing_bot"),
        "saved_authorization": check("incomplete", "no_fresh_in_process_identity_proof"),
        "call_presence": check("incomplete", "no_existing_managed_call_observation"),
    }
    if not isinstance(evidence, dict) or type(evidence.get("schema_version")) is not int or evidence.get("schema_version") != REPORT_SCHEMA:
        return missing
    finished = evidence.get("finished_at")
    if not isinstance(finished, datetime) or finished.tzinfo is None:
        return missing
    age = (reference - finished).total_seconds()
    current = (
        isinstance(lease, dict)
        and isinstance(lease.get("holder"), str)
        and isinstance(lease.get("until"), datetime)
        and lease["until"].tzinfo is not None
        and lease["until"] > reference
    )
    current = current and evidence.get("runtime_reference") == runtime_reference(lease["holder"])
    current = current and evidence.get("code_version") == __version__ and expected_bot and evidence.get("bot_reference") == expected_bot
    current = current and expected_configuration and evidence.get("configuration_reference") == expected_configuration
    if not current or not -30 <= age <= max_age:
        missing["runtime_health"] = check("incomplete", "report_stale_or_bot_config_key_version_runtime_changed")
        return missing
    completed = evidence.get("scan_status") == "complete"
    healthy = completed and all(evidence.get(key) is True for key in ("database_connected", "bot_api_connected", "workers_running"))
    call = evidence.get("call_observation") if isinstance(evidence.get("call_observation"), dict) else {}
    call_ok = (
        healthy
        and call.get("status") == "verified"
        and type(call.get("sampled")) is int
        and call.get("sampled") == 1
        and call.get("native_transport") is True
        and call.get("server_self_participant") is True
    )
    identities = safe_count(evidence.get("accounts_self_verified"))
    reviewed = safe_count(evidence.get("accounts_reviewed"))
    identities = min(identities, reviewed, POOL_ACCOUNT_CEILING)
    return {
        "runtime_health": check(
            "passed" if healthy else "incomplete",
            None if healthy else "health_scan_not_complete_or_component_failed",
            age_seconds=max(0, int(age)),
            accounts_reviewed=min(reviewed, POOL_ACCOUNT_CEILING),
        ),
        "saved_authorization": check(
            "passed" if healthy and (identities or call_ok) else "incomplete",
            identities_self_verified=identities,
            existing_call_self_verified=bool(call_ok),
        ),
        "call_presence": check(
            "passed" if call_ok else "incomplete",
            None if call_ok else "run_health_during_one_owned_managed_test_call",
            sampled=1 if call_ok else 0,
            scope="native_binding_and_same_call_telegram_self_participant_not_media_quality",
        ),
    }


def finish_report(report, calls_enabled, scope="full"):
    essential = ("configuration", "http_live", "http_ready", "database", "runtime_lease", "bot_api", "owner_configuration")
    failed = any(report["checks"].get(key, {}).get("status") != "passed" for key in essential)
    observed = ["runtime_health", "session_safety", "saved_authorization"] + (["call_presence"] if calls_enabled else [])
    if scope == "safety":
        observed = ["runtime_health", "session_safety"]
    incomplete = any(report["checks"].get(key, {}).get("status") != "passed" for key in observed)
    report["automated_status"] = "failed" if failed else "incomplete" if incomplete else "passed"
    report["complete_live_acceptance"] = False  # Manual signup/QR/recovery behavior cannot be asserted by this reader.
    return 1 if failed else 2 if incomplete else 0


async def collect(config, max_age=300, *, store=None, bot=None, http=None, scope="full"):
    if scope not in {"full", "safety"}:
        raise ValueError("Unsupported verifier scope")
    reference = now()
    report = {
        "report_kind": "telepilot_host_verification",
        "schema_version": 1,
        "code_version": __version__,
        "generated_at": reference.isoformat(),
        "scope": scope,
        "deployment_observations": local_deployment_observations(),
        "checks": {"configuration": check("passed")},
        "manual_checks": {name: "confirmation_required" for name in MANUAL_CHECKS},
        "safety": {
            "mode": "read_only_host_reader",
            "new_user_account_clients": False,
            "session_decryption_or_export": False,
            "otp_requests": False,
            "call_joins_or_leaves": False,
            "database_writes_or_lease_acquisition": False,
        },
    }
    checks = report["checks"]
    owned_store, owned_bot, owned_http = store is None, bot is None, http is None
    store = store if store is not None else Store(config)
    bot = bot if bot is not None else Bot(config.bot_token.get_secret_value())
    http = http if http is not None else httpx.AsyncClient(timeout=4, trust_env=False, follow_redirects=False)
    lease = evidence = safety_state = None
    duplicate_count = 0
    expected_bot = None
    try:
        for path, key, expected in (("/health/live", "http_live", "alive"), ("/health/ready", "http_ready", "ready")):
            try:
                response = await asyncio.wait_for(http.get(f"http://127.0.0.1:{config.http_port}{path}"), 5)
                checks[key] = check(
                    "passed" if response.status_code == 200 and response.json().get("status") == expected else "failed",
                    None if response.status_code == 200 else "runtime_not_ready_or_wrong_listener",
                )
            except Exception:
                checks[key] = check("failed", "local_runtime_http_unavailable")
        try:
            await asyncio.wait_for(store.client.admin.command("ping"), 5)
            checks["database"] = check("passed")
            async with asyncio.timeout(10):
                lease = await store.db.leases.find_one({"_id": "runtime"}, {"holder": 1, "until": 1, "_id": 0})
                until = lease.get("until") if isinstance(lease, dict) else None
                valid = isinstance(until, datetime) and until.tzinfo is not None and until > now() and isinstance(lease.get("holder"), str)
                checks["runtime_lease"] = check("passed" if valid else "failed", None if valid else "no_current_singleton_lease")
                if not valid:
                    lease = None
                projection = {"value." + field: 1 for field in HEALTH_FIELDS}
                projection["_id"] = 0
                row = await store.db.settings.find_one({"_id": REPORT_SETTING}, projection)
                evidence = row.get("value") if isinstance(row, dict) else None
                safety_row = await store.db.settings.find_one({"_id": SAFETY_SETTING}, {"value.paused": 1, "_id": 0})
                safety_state = safety_row.get("value", {}) if isinstance(safety_row, dict) else {}
                duplicate_count = safe_count(await store.db.accounts.count_documents(DUPLICATE_QUERY))
                counts = {}
                for name, query in (
                    ("saved", {}),
                    ("enabled", {"enabled": True}),
                    ("missing_encrypted_session", {"$or": [{"session_ciphertext": None}, {"session_ciphertext": ""}]}),
                ):
                    counts[name] = safe_count(await store.db.accounts.count_documents(query))
                checks["saved_records"] = check("observed", **counts, configured_capacity=config.limits.max_pool_accounts)
                recent = await store.db.audit.count_documents(
                    {"action": "account_authenticated", "created_at": {"$gte": reference - timedelta(hours=1)}}
                )
                checks["recent_saved_authorizations"] = check(
                    "observed", count=safe_count(recent), scope="recorded_commit_events_not_proof_of_all_phone_or_qr_steps"
                )
        except Exception:
            if "database" not in checks:
                checks["database"] = check("failed", "database_unavailable")
            checks.setdefault("runtime_lease", check("failed", "lease_state_unavailable"))
            checks["database_observations"] = check("incomplete", "bounded_read_could_not_finish")
        try:
            me = await asyncio.wait_for(bot.get_me(), 10)
            valid_bot = type(me.id) is int and me.id > 0 and getattr(me, "is_bot", False) is True
            expected_bot = bot_reference(me.id) if valid_bot else None
            checks["bot_api"] = check("passed" if valid_bot else "failed", None if valid_bot else "invalid_bot_identity")
            checks["owner_configuration"] = check(
                "passed" if valid_bot and me.id not in config.owner_ids else "failed",
                None if valid_bot and me.id not in config.owner_ids else "owner_ids_must_be_personal_user_ids_not_bot_id",
            )
        except Exception:
            checks["bot_api"] = check("failed", "bot_identity_request_failed_or_cooldown_no_automatic_retry")
            checks["owner_configuration"] = check("incomplete", "bot_identity_not_available")
        if isinstance(lease, dict) and lease["until"] <= now():
            checks["runtime_lease"] = check("failed", "singleton_lease_expired_during_check")
            lease = None
        expected_configuration = configuration_reference(config, lease["holder"]) if isinstance(lease, dict) else None
        checks.update(evaluate_health(evidence, lease, now(), expected_bot, max_age, expected_configuration))
        frame = evidence.get("session_safety", {}) if isinstance(evidence, dict) else {}
        frame = frame if isinstance(frame, dict) else {}
        paused = safety_state.get("paused") is True if isinstance(safety_state, dict) else None
        same = checks["runtime_health"]["status"] == "passed" and type(frame.get("paused")) is bool and frame.get("paused") == paused
        fenced = same and frame.get("wire_fence_enabled") is True and frame.get("ownership_valid") is True
        checks["session_safety"] = check(
            "blocked" if paused is True else "passed" if fenced else "incomplete",
            "owner_review_conflicting_copies_before_new_logins"
            if paused is True
            else None
            if fenced
            else "fresh_safety_fence_evidence_missing_or_changed",
            paused=paused,
            runtime_wire_fence_observed=bool(fenced),
            duplicate_authorization_records=duplicate_count,
            invalidated_keys_recoverable=False,
            global_deployment_inventory_verified=False,
        )
        if paused is True:
            checks["saved_authorization"] = check("incomplete", "safety_paused_no_account_probe_claimed")
            checks["call_presence"] = check("not_checked", "do_not_start_calls_or_reauthenticate_until_safety_review")
        elif not config.calls_enabled:
            checks["call_presence"] = check("not_checked", "calls_disabled_on_this_host")
    finally:
        # Dependency-injected clients belong to their caller. No Telegram user
        # client is ever created or disconnected anywhere in this module.
        operations = []
        if owned_http:
            operations.append(http.aclose)
        if owned_bot:
            operations.append(bot.session.close)
        if owned_store:
            operations.append(store.close)
        for operation in operations:
            try:
                await asyncio.wait_for(operation(), 3)
            except Exception:
                pass
    return report, finish_report(report, config.calls_enabled, scope)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid verifier arguments. Use --help; never pass credentials as command arguments.\n")


def main(argv=None):
    parser = SafeParser(description="Read-only verification of the existing TelePilot runtime. Never starts another account client.")
    parser.add_argument(
        "--config", help="Existing private config path; otherwise the usual CONFIG_PATH/env are used. Never pass secrets as arguments."
    )
    parser.add_argument(
        "--scope",
        choices=("full", "safety"),
        default="full",
        help="Use safety first after duplicate-key incidents; no user login/call required.",
    )
    parser.add_argument("--max-report-age", type=int, default=300, choices=range(30, 3601), metavar="30..3600")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        configure_logging(config.model_copy(update={"log_directory": ""}))  # Console redaction only, no log/config writes.
        report, code = asyncio.run(collect(config, args.max_report_age, scope=args.scope))
    except KeyboardInterrupt:
        report, code = (
            {
                "report_kind": "telepilot_host_verification",
                "automated_status": "incomplete",
                "reason": "operator_cancelled",
                "complete_live_acceptance": False,
            },
            2,
        )
    except Exception:
        report, code = (
            {
                "report_kind": "telepilot_host_verification",
                "automated_status": "failed",
                "reason": "configuration_or_verifier_unavailable_no_credentials_printed",
                "complete_live_acceptance": False,
            },
            1,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
