"""Feature/nullable-quota definitions; unlimited is explicit, never a big integer."""

from .security import UserError

FEATURE_PLANS = {"channels": frozenset({"join"}), "calls": frozenset({"call"}), "both": frozenset({"join", "call"})}
FEATURE_LABELS = {"channels": "join channels", "calls": "join a call", "both": "channels + calls"}
LEGACY_CHANNEL_LIMIT = 10
UNLIMITED = "unlimited"
QUOTAS = {"accounts": ("max_accounts", "accounts_unlimited"), "channels": ("channel_limit", "channels_unlimited")}


def quota_choice(value, maximum, label):
    if isinstance(value, str):
        value = value.strip().lower()
        if value == UNLIMITED:
            return None
        if value.isascii() and value.isdigit():
            value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise UserError(f"{label} must be 1–{maximum} or unlimited.")
    return value


def normalized_plan(plan, config):
    value = dict(plan or {})
    value.setdefault("feature_plan", "both")
    value.setdefault("channel_limit", LEGACY_CHANNEL_LIMIT if value.get("expires_at") else config.limits.default_plan_channels)
    value.setdefault("max_accounts", config.limits.default_plan_accounts)
    if value["feature_plan"] not in FEATURE_PLANS:
        raise UserError("Your plan needs a staff review. Contact an admin.")
    for kind, (field, flag) in QUOTAS.items():
        value.setdefault(flag, False)
        if not isinstance(value[flag], bool):
            raise UserError("Your quota mode needs a staff review. Contact an admin.")
        if value[flag]:
            if value[field] is not None:
                raise UserError("Your unlimited quota needs a staff review. Contact an admin.")
        elif isinstance(value[field], bool) or not isinstance(value[field], int) or value[field] < 1:
            raise UserError(f"Your {kind} limit needs a staff review. Contact an admin.")
    return value


def effective_plan(plan, config):
    """Fresh operational ceilings, not a snapshot of today's pool account count."""
    result = dict(plan)
    for kind, ceiling in (("accounts", config.limits.max_pool_accounts), ("channels", config.limits.max_channels_per_user)):
        field, flag = QUOTAS[kind]
        result[field] = ceiling if plan.get(flag) else min(plan[field], ceiling)
    return result


def quota_label(plan, kind):
    field, flag = QUOTAS[kind]
    value = plan.get(field)
    if plan.get(flag) is True or (isinstance(value, str) and value.lower() == UNLIMITED):
        return UNLIMITED
    return str(value) if value is not None else "unchanged"


def channel_capacity_error(plan, config):
    if plan.get("channels_unlimited"):
        return UserError(
            f"This host's {config.limits.max_channels_per_user}-channel safety ceiling is full. Your plan quota remains unlimited. Contact the operator; saved choices stay locked."
        )
    return UserError(
        f"Your {plan['channel_limit']}-channel limit is full. Saved channels are locked. Contact an admin for a correction or upgrade."
    )


def account_capacity_error(plan):
    if plan.get("accounts_unlimited") or plan.get("staff"):
        return UserError(
            f"This host permits 1–{plan['max_accounts']} accounts per task. Unlimited plan quotas do not override operational ceilings."
        )
    return UserError("Requested accounts exceed your Premium limit or the current host ceiling. Use a positive permitted count.")


def feature_allowed(plan, kind):
    return kind in FEATURE_PLANS.get(plan.get("feature_plan"), ())


def feature_label(value):
    return FEATURE_LABELS.get(value, "needs staff review")
