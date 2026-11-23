"""Reports (v9.2 Batch H #16): the pieces every report tab shares.

Days are IST calendar days, `to` inclusive. A report is {"period": {...}, "before": {...}|null,
"in_short": "<one plain sentence>"}. The sentence is built here from the numbers, never by an AI.

Money: any rupee figure (keys ending _paise, plus money_back) needs the owner or deals.view.
Profit, expenses, GST paid and supplier dues also need purchases.view. A person without the
permission gets the key left OUT (not zero) and "money_hidden": true.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

from app.dependencies.tenant import _has_permission
from app.services.sales_target import indian_rupees

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
MAX_DAYS = 400
DEFAULT_DAYS = 30
CHUNK = 150
PAGE = 1000
MAX_PAGES = 60

# Keys a person needs purchases.view for (on top of deals.view).
PROFIT_KEYS = {"cost_paise", "expenses_paise", "profit_paise", "gst_paid_paise", "gst_to_pay_paise",
               "owed_to_suppliers_paise"}
# Non-_paise keys that are still rupee figures.
OTHER_MONEY_KEYS = {"money_back"}


# ── the picked days ───────────────────────────────────────────────────────────

def today_ist() -> date:
    return datetime.now(IST).date()


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def start_utc(self) -> datetime:
        return datetime.combine(self.start, datetime.min.time(), IST).astimezone(timezone.utc)

    @property
    def end_utc(self) -> datetime:
        """Exclusive: midnight IST at the end of the last picked day."""
        return datetime.combine(self.end + timedelta(days=1), datetime.min.time(), IST).astimezone(timezone.utc)

    @property
    def start_iso(self) -> str:
        return self.start_utc.isoformat()

    @property
    def end_iso(self) -> str:
        return self.end_utc.isoformat()

    @property
    def end_excl_day(self) -> date:
        return self.end + timedelta(days=1)

    def previous(self) -> "Period":
        """The same number of days right before this period."""
        return Period(self.start - timedelta(days=self.days), self.start - timedelta(days=1))

    def whole_months(self) -> list[str] | None:
        """["2026-10", ...] when the picked days are exactly whole IST months, else None."""
        if self.start.day != 1 or (self.end + timedelta(days=1)).day != 1:
            return None
        out, cur = [], self.start
        while cur <= self.end:
            out.append(cur.strftime("%Y-%m"))
            cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        return out


def _parse_day(text: str, what: str) -> date:
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"The '{what}' day must look like 2026-10-31.")


def resolve_period(from_day: str | None, to_day: str | None, now: date | None = None) -> Period:
    """No days picked = the last 30 days up to today."""
    end = _parse_day(to_day, "to") if to_day else (now or today_ist())
    start = _parse_day(from_day, "from") if from_day else end - timedelta(days=DEFAULT_DAYS - 1)
    if start > end:
        raise HTTPException(status_code=400, detail="The first day can't be after the last day.")
    if (end - start).days + 1 > MAX_DAYS:
        raise HTTPException(status_code=400, detail=f"Pick {MAX_DAYS} days or fewer.")
    return Period(start, end)


def want_before(compare: str | None) -> bool:
    if compare in (None, "", "previous"):
        return True
    if compare == "off":
        return False
    raise HTTPException(status_code=400, detail="compare must be 'previous' or 'off'.")


# ── who may see what ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Flags:
    sees_money: bool
    sees_profit: bool


def flags_for(ctx: dict) -> Flags:
    money = _has_permission(ctx, "deals.view")
    return Flags(sees_money=money, sees_profit=money and _has_permission(ctx, "purchases.view"))


def strip_money(obj, flags: Flags):
    """A copy of obj with the rupee keys this person may not see left out (recursively)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            is_money = isinstance(k, str) and (k.endswith("_paise") or k in OTHER_MONEY_KEYS)
            if is_money and not flags.sees_money:
                continue
            if isinstance(k, str) and k in PROFIT_KEYS and not flags.sees_profit:
                continue
            out[k] = strip_money(v, flags)
        return out
    if isinstance(obj, list):
        return [strip_money(v, flags) for v in obj]
    return obj


# ── small helpers ─────────────────────────────────────────────────────────────

def safe_cell(value):
    """Text a spreadsheet must never run as a formula (a customer name like '=HYPERLINK(...)')."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def chunks(items: list, size: int = CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def paged(make_query, order_by: str | tuple = "id") -> list[dict]:
    """Every row of a query, page by page (PostgREST caps one answer at 1000 rows).
    make_query() must return a fresh query each call."""
    cols = (order_by,) if isinstance(order_by, str) else tuple(order_by)
    out: list[dict] = []
    for _ in range(MAX_PAGES):
        q = make_query()
        for c in cols:
            q = q.order(c)
        page = q.range(len(out), len(out) + PAGE - 1).execute().data or []
        out.extend(page)
        if len(page) < PAGE:
            break
    return out


def safe(fn, default, what: str):
    """Run fn; a missing table or a failed read gives `default` and a log line, never a crash."""
    try:
        return fn()
    except Exception as e:  # the migration may not be applied yet
        logger.warning("report: %s unavailable: %s", what, e)
        return default


def money(paise) -> str:
    return indian_rupees(int(paise or 0))


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def vs_before(now, before, unit: str = "") -> str:
    """'up 8 from before' / 'down 3 from before' / 'same as before' ('' without a before number)."""
    if before is None or now is None:
        return ""
    diff = int(now) - int(before)
    if diff == 0:
        return "same as before"
    amount = money(abs(diff)) if unit == "paise" else str(abs(diff))
    return f"{'up' if diff > 0 else 'down'} {amount} from before"


def count_phrase(n, before, noun_one: str, noun_many: str | None = None) -> str:
    """'42 new chats, up 8 from before'"""
    n = int(n or 0)
    text = plural(n, noun_one, noun_many)
    change = vs_before(n, before)
    return f"{text}, {change}" if change else text


def sentence(parts: list[str], fallback: str) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return fallback
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def finish(payload: dict, flags: Flags, keep: tuple = ()) -> dict:
    """Strip the money this person may not see; say so with money_hidden / profit_hidden."""
    kept = {k: payload[k] for k in keep if k in payload}
    out = strip_money({k: v for k, v in payload.items() if k not in keep}, flags)
    out.update(kept)
    if not flags.sees_money:
        out["money_hidden"] = True
    elif not flags.sees_profit:
        out["profit_hidden"] = True
    return out


def build_report(compute, db, tenant_id: str, period: Period, compare: bool, flags: Flags, **kw) -> dict:
    """{"period": numbers, "before": numbers|None, ...extras from compute}. compute returns
    (numbers, extras) for one period."""
    numbers, extras = compute(db, tenant_id, period, flags, **kw)
    before = None
    if compare:
        before, _ = compute(db, tenant_id, period.previous(), flags, **kw)
    return {"period": numbers, "before": before, **extras}


def run_report(module, db, tenant_id: str, period: Period, compare: bool, flags: Flags, keep: tuple = (), **kw) -> dict:
    """One tab: compute this period (and the one before), strip what this person may not see,
    then write the plain 'in short' sentence from the numbers that are left."""
    payload = build_report(module.compute, db, tenant_id, period, compare, flags, **kw)
    payload = finish(payload, flags, keep)
    payload["in_short"] = module.in_short(payload["period"], payload["before"])
    return payload
