from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .security import UserError


def now() -> datetime:
    return datetime.now(UTC)


def display_time(value: datetime | None, timezone: str) -> str:
    if value is None:
        return "—"
    return value.astimezone(ZoneInfo(timezone)).strftime("%d %b %Y, %H:%M %Z")


def parse_schedule(text: str, timezone: str, reference: datetime | None = None) -> datetime:
    reference = reference or now()
    try:
        naive = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
        local = naive.replace(tzinfo=ZoneInfo(timezone))
        value = local.astimezone(UTC)
        # Reject nonexistent local times (DST) instead of silently changing them.
        if value.astimezone(ZoneInfo(timezone)).replace(tzinfo=None) != naive:
            raise ValueError
    except ValueError:
        raise UserError("Date format: YYYY-MM-DD HH:MM, e.g. 2026-10-20 18:30 (your configured timezone).") from None
    if value < reference + timedelta(seconds=30):
        raise UserError("Schedule must be at least 30 seconds in the future.")
    if value > reference + timedelta(days=90):
        raise UserError("Schedule can be at most 90 days ahead.")
    return value


def plan_expiry(previous: datetime | None, days: int, mode: str, reference: datetime | None = None) -> datetime:
    reference = reference or now()
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        raise UserError("Plan duration must be 1–365 days.")
    if mode not in ("set", "extend"):
        raise UserError("Plan mode must be set or extend.")
    base = max(previous or reference, reference) if mode == "extend" else reference
    return base + timedelta(days=days)
