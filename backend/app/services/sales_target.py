"""My business > Target & profit: the shop's monthly sales target.

Stored in app_settings, key "sales_target":
  {"monthly_paise": int|None, "months": {"YYYY-MM": paise}, "show_team": bool}
"months" overrides monthly_paise for that one IST calendar month.

"Money in" is the same number Home shows: deal_payments by paid_at, less deal_refunds (not failed)
by created_at (services/orders._cards). The suggestion is the average of the last 3 FULL IST months
that had money in, plus 10%, rounded UP to the next Rs 1,000, in whole-integer maths.
"""
import json
import logging
import re
from datetime import datetime, timedelta

from app.services.orders import IST, _now

logger = logging.getLogger(__name__)

KEY = "sales_target"
MAX_PAISE = 10**12
MAX_MONTHS = 24
SUGGEST_MONTHS = 3
SUGGEST_UPLIFT_PCT = 10
ROUND_TO_PAISE = 1000 * 100
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PAGE = 1000
MAX_PAGES = 20


class TargetError(ValueError):
    """The saved target is not valid; the message is plain words for the owner."""


# ───────────────────────────────────────────────────────────── plain helpers

def indian_rupees(paise: int) -> str:
    """₹2,00,000 (Indian grouping); paise only when there are some."""
    paise = int(paise)
    sign = "-" if paise < 0 else ""
    rupees, rest = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}₹{digits}" + (f".{rest:02d}" if rest else "")


def month_key(dt: datetime) -> str:
    ist = dt.astimezone(IST)
    return f"{ist.year:04d}-{ist.month:02d}"


def month_start(dt: datetime) -> datetime:
    return dt.astimezone(IST).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def previous_month_start(start: datetime) -> datetime:
    return (start - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def last_full_months(now: datetime, n: int = SUGGEST_MONTHS) -> list[datetime]:
    """Start of each of the last n full IST months, oldest first (this month is not full)."""
    starts = []
    cursor = month_start(now)
    for _ in range(n):
        cursor = previous_month_start(cursor)
        starts.append(cursor)
    return list(reversed(starts))


def suggest_paise(money_in: list[int]) -> int | None:
    """Average of the months that had money in, +10%, rounded UP to the next ₹1,000.
    None when no month had any money in."""
    months = [int(m) for m in money_in if int(m) > 0]
    if not months:
        return None
    # ceil(total * 110 / (100 * n)) in integers, then ceil to the next 1,000 rupees
    uplifted = -(-sum(months) * (100 + SUGGEST_UPLIFT_PCT) // (100 * len(months)))
    return -(-uplifted // ROUND_TO_PAISE) * ROUND_TO_PAISE


def pct_of(money_in: int, target: int | None) -> int | None:
    if not target or target <= 0:
        return None
    return round(int(money_in) * 100 / int(target))


def target_for_month(target: dict, key: str) -> int | None:
    """This month's own number if set, else the every-month one. 0 and None both mean "no target"."""
    value = (target.get("months") or {}).get(key)
    if value is None:
        value = target.get("monthly_paise")
    return int(value) if value else None


# ───────────────────────────────────────────────────────────── stored target

def _clean_paise(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TargetError(f"{what} must be a whole number of paise")
    if value < 0:
        raise TargetError(f"{what} can't be below zero")
    if value > MAX_PAISE:
        raise TargetError(f"{what} is too large")
    return value


def validate(data: dict) -> dict:
    monthly = data.get("monthly_paise")
    monthly = None if monthly is None else _clean_paise(monthly, "The monthly target")
    months_in = data.get("months") or {}
    if not isinstance(months_in, dict):
        raise TargetError("Months must be a list of month and amount")
    if len(months_in) > MAX_MONTHS:
        raise TargetError(f"You can set a different target for at most {MAX_MONTHS} months")
    months = {}
    for key, value in months_in.items():
        if not isinstance(key, str) or not MONTH_RE.match(key):
            raise TargetError(f"'{key}' is not a month. Use the form 2026-12")
        months[key] = _clean_paise(value, f"The target for {key}")
    return {"monthly_paise": monthly, "months": months, "show_team": bool(data.get("show_team"))}


def prune_months(months: dict, now: datetime | None = None) -> dict:
    """Drop per-month targets for months before this IST month (nobody sees them again), so the
    24-month cap can never lock the owner out. Keys that are not months are kept for validate()."""
    current = month_key(now or _now())
    return {k: v for k, v in (months or {}).items() if not (isinstance(k, str) and MONTH_RE.match(k) and k < current)}


def read_target(db, tenant_id: str, now: datetime | None = None) -> dict:
    """The saved target, or an empty one when nothing is saved or the row can't be read."""
    empty = {"monthly_paise": None, "months": {}, "show_team": False}
    try:
        rows = (
            db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", KEY)
            .limit(1).execute().data or []
        )
        raw = rows[0].get("value") if rows else None
        saved = json.loads(raw) if raw else {}
        if not isinstance(saved, dict):
            return empty
        return validate({**saved, "months": prune_months(saved.get("months"), now)})
    except Exception as e:
        logger.warning("sales target: could not read for tenant %s: %s", tenant_id, e)
        return empty


def save_target(db, tenant_id: str, data: dict, now: datetime | None = None) -> dict:
    from app.config_dynamic import invalidate_cache
    clean = validate({**data, "months": prune_months(data.get("months"), now)})
    db.table("app_settings").upsert({
        "tenant_id": tenant_id, "key": KEY, "value": json.dumps(clean), "is_secret": False,
        "updated_at": "now()",
    }, on_conflict="tenant_id,key").execute()
    invalidate_cache(KEY)
    return clean


# ───────────────────────────────────────────────────────────── money in

def _paged(make_query, order_by: str = "id") -> list[dict]:
    """All rows of a query, a page at a time. Ordered (the column, then id as a tie-break) so a
    page boundary can never skip or repeat a row."""
    rows: list[dict] = []
    for page in range(MAX_PAGES):
        q = make_query().order(order_by)
        if order_by != "id":
            q = q.order("id")
        got = q.range(page * PAGE, page * PAGE + PAGE - 1).execute().data or []
        rows.extend(got)
        if len(got) < PAGE:
            return rows
    logger.warning("sales target: stopped at %s rows; the totals may be short", len(rows))
    return rows


def money_in_by_month(db, tenant_id: str, since: datetime, until: datetime | None = None) -> dict[str, int]:
    """IST month -> payments received (paid_at) less refunds given (created_at, not failed), the
    same rule as Home's Money in. Months with nothing are left out."""
    def payments():
        q = db.table("deal_payments").select("amount_paise, paid_at").eq("tenant_id", tenant_id).gte("paid_at", since.isoformat())
        return q.lt("paid_at", until.isoformat()) if until else q

    def refunds():
        q = (
            db.table("deal_refunds").select("amount_paise, created_at").eq("tenant_id", tenant_id)
            .neq("status", "failed").gte("created_at", since.isoformat())
        )
        return q.lt("created_at", until.isoformat()) if until else q

    totals: dict[str, int] = {}
    for rows, stamp, sign in ((_paged(payments, "paid_at"), "paid_at", 1), (_paged(refunds, "created_at"), "created_at", -1)):
        for r in rows:
            try:
                when = datetime.fromisoformat(str(r.get(stamp)).replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.tzinfo is None:
                continue
            key = month_key(when)
            totals[key] = totals.get(key, 0) + sign * int(r.get("amount_paise") or 0)
    return totals


# ───────────────────────────────────────────────────────────── the Target page

def cost_coverage(db, tenant_id: str) -> dict | None:
    """{with_cost, total} of catalogue items; None when the catalogue can't be read."""
    try:
        rows = _paged(lambda: db.table("catalog_items").select("id, cost_price_paise").eq("tenant_id", tenant_id))
    except Exception as e:
        logger.warning("sales target: cost coverage failed for tenant %s: %s", tenant_id, e)
        return None
    return {"with_cost": sum(1 for r in rows if r.get("cost_price_paise") is not None), "total": len(rows)}


def overview(db, tenant_id: str, now: datetime | None = None, sees_money: bool = True) -> dict:
    """sees_money False (a person without Orders view): the target and the % stay, every rupee of
    money in (and the suggestion made from it) is left out."""
    now = now or _now()
    target = read_target(db, tenant_id, now)
    this_start = month_start(now)
    past = last_full_months(now)
    try:
        by_month = money_in_by_month(db, tenant_id, past[0])
        money_ok = True
    except Exception as e:
        logger.warning("sales target: money in failed for tenant %s: %s", tenant_id, e)
        by_month, money_ok = {}, False
    last3 = [{"month": month_key(s), "money_in_paise": by_month.get(month_key(s), 0)} for s in past]
    key = month_key(this_start)
    this_target = target_for_month(target, key)
    this_money = by_month.get(key, 0)
    suggested = suggest_paise([m["money_in_paise"] for m in last3]) if money_ok else None
    if not sees_money:
        suggested = None
        last3 = [{"month": m["month"], "money_in_paise": None} for m in last3]
    return {
        "monthly_paise": target["monthly_paise"],
        "months": target["months"],
        "show_team": target["show_team"],
        "suggested_paise": suggested,
        "last3": last3,
        "this_month": {
            "month": key,
            "target_paise": this_target,
            "money_in_paise": this_money if money_ok and sees_money else None,
            "pct": pct_of(this_money, this_target) if money_ok else None,
        },
        "cost_coverage": cost_coverage(db, tenant_id),
    }


# ───────────────────────────────────────────────────────────── the Home box

def home_box(db, ctx: dict, now: datetime | None = None) -> dict | None:
    """The "Target this month" box for this person, or None when they should not see it.

    Owner, and anyone with Orders view: "₹1,86,000 of ₹2,00,000 · 93%". Everyone else: only
    "93% of target", and only when the owner turned "Show the target to my team" on.
    No target set: the owner gets a "Set a target" box, nobody else gets anything."""
    from app.dependencies.tenant import _has_permission
    now = now or _now()
    tenant_id = ctx["tenant_id"]
    is_owner = ctx.get("role") == "owner"
    sees_money = is_owner or _has_permission(ctx, "deals.view")
    # The target page shows rupees, so only people who may see money are sent there.
    href = "/dashboard/settings/target" if (is_owner or (sees_money and _has_permission(ctx, "settings.view"))) else "/dashboard"

    target = read_target(db, tenant_id, now)
    key = month_key(now)
    goal = target_for_month(target, key)
    if not goal:
        if is_owner:
            return {"value": 0, "unit": "set_target", "sub": "Tap to choose one", "href": "/dashboard/settings/target"}
        return None
    if not sees_money and not target["show_team"]:
        return None

    money = money_in_by_month(db, tenant_id, month_start(now)).get(key, 0)
    pct = pct_of(money, goal)
    if sees_money:
        return {"value": money, "unit": "paise", "sub": f"of {indian_rupees(goal)} · {pct}%", "href": href}
    return {"value": pct, "unit": "percent", "sub": "of target", "href": href}
