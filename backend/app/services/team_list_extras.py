"""v9.2 #48 Team & roles list: sales per person, a leave tag, and a one-line "what they can do".

Sales are this month's won orders, before GST, by the person who sold (sold_by is a callers.id) or, when nobody
is recorded, the person who made the order. Only given to someone who may see deals. Leave dates live on callers
(leave_from, leave_to; migration 321) and are set in Settings > Calling rules.
"""
from datetime import date

from app.services.caller_leave import on_leave, today_ist
from app.services.reports_common import Period, paged, safe
from app.services.reports_data import sales_before_gst, won_deals

# (permission, what it lets them do), in the order a person would say it. A "manage" key also covers its "view".
_CAN_DO = [
    ("roles.manage", "manage users and roles"),
    ("settings.manage", "change settings"),
    ("team.manage", "run the team"),
    ("team.view", "see team results"),
    ("deals.manage", "make orders"),
    ("deals.view", "see orders"),
    ("telecalling.dialer", "make calls"),
    ("leads.manage", "work leads"),
    ("leads.view", "see leads"),
    ("bookings.manage", "run bookings"),
    ("bookings.view", "see bookings"),
    ("conversations.reply", "reply to chats"),
    ("conversations.view", "see chats"),
    ("leads.download", "download lists"),
]
_SHOWN = 4


def _has(perms: set[str], key: str) -> bool:
    if key in perms:
        return True
    return key.endswith(".view") and f"{key[:-5]}.manage" in perms


def role_summary(role_slug: str | None, permissions: list[str] | None) -> str:
    """One short line: "Can reply to chats, make calls and 2 more". The owner can do everything."""
    if role_slug == "owner":
        return "Can do everything"
    perms = set(permissions or [])
    said: list[str] = []
    covered: set[str] = set()
    for key, phrase in _CAN_DO:
        if not _has(perms, key):
            continue
        area = key.rsplit(".", 1)[0]
        # "run the team" already says "see team results"; "work leads" already says "see leads".
        if key.endswith((".view",)) and area in covered:
            continue
        if key.endswith(".manage"):
            covered.add(area)
        said.append(phrase)
    if not said:
        return "Can only look around"
    if len(said) > _SHOWN:
        return "Can " + ", ".join(said[: _SHOWN - 1]) + f" and {len(said) - _SHOWN + 1} more"
    if len(said) == 1:
        return "Can " + said[0]
    return "Can " + ", ".join(said[:-1]) + " and " + said[-1]


def month_so_far(today: date) -> Period:
    return Period(today.replace(day=1), today)


def sales_by_user(db, tenant_id: str, today: date) -> dict[str, int]:
    """user_id -> this month's sales in paise, before GST. People with no sales are absent."""
    deals = safe(lambda: won_deals(db, tenant_id, month_so_far(today)), [], "team sales")
    caller_user = {
        r["id"]: r.get("user_id") for r in safe(lambda: paged(
            lambda: db.table("callers").select("id,user_id").eq("tenant_id", tenant_id)), [], "team callers")
    }
    out: dict[str, int] = {}
    for d in deals:
        if d.get("sold_by_ai"):
            continue
        user = caller_user.get(d.get("sold_by")) if d.get("sold_by") else None
        user = user or d.get("created_by")
        if not user:
            continue
        out[str(user)] = out.get(str(user), 0) + sales_before_gst(d)
    return out


def leave_by_user(db, tenant_id: str, today: date) -> dict[str, str]:
    """user_id -> the last day of leave, for people on leave today."""
    rows = safe(lambda: paged(lambda: db.table("callers").select("id,user_id,leave_from,leave_to")
                              .eq("tenant_id", tenant_id)), [], "team leave")
    return {str(r["user_id"]): str(r["leave_to"])[:10] for r in rows if r.get("user_id") and on_leave(r, today)}


def build(db, tenant_id: str, can_see_sales: bool, today: date | None = None) -> dict:
    today = today or today_ist()
    return {
        "sales": sales_by_user(db, tenant_id, today) if can_see_sales else None,
        "leave": leave_by_user(db, tenant_id, today),
    }
