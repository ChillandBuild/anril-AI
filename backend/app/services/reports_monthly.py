"""Reports: the two monthly bells to each owner.

  1st of the month  "Your report for October: Rs 1,20,000 sales, 42 new customers"   -> Reports > Overview
  5th of the month  "Last month's accountant file is ready"                           -> Reports > Money

Both are called by the daily reports-monthly-bells job. They never raise and send at most once per
shop per month: the month is saved in app_settings (reports_monthly_bell / reports_accountant_bell)
before the bell is sent. A job that was down on the exact day still catches up within 3 days.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.services.reports_common import IST, Period, money, paged, plural, safe
from app.services.reports_data import new_chats, sales_before_gst, won_deals

logger = logging.getLogger(__name__)

MONTHLY_KEY = "reports_monthly_bell"
ACCOUNTANT_KEY = "reports_accountant_bell"
CATCH_UP_DAYS = 3
BELL_TYPE = "monthly_report"


def _last_month(now: datetime | None) -> tuple[date, str, Period, int]:
    """(today in IST, 'YYYY-MM', whole last month, its day count)."""
    today = (now or datetime.now(timezone.utc)).astimezone(IST).date()
    last_day = today.replace(day=1) - timedelta(days=1)
    first = last_day.replace(day=1)
    return today, first.strftime("%Y-%m"), Period(first, last_day), last_day.day


def _claim(db, tenant_id: str, key: str, month: str) -> bool:
    """True when this shop has not been sent this month's bell yet (and marks it sent)."""
    row = db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", key).maybe_single().execute()
    if row and (row.data or {}).get("value") == month:
        return False
    db.table("app_settings").upsert({"tenant_id": tenant_id, "key": key, "value": month}, on_conflict="tenant_id,key").execute()
    return True


def _owners(db, tenant_id: str) -> list[str]:
    rows = db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner").execute().data or []
    return [r["user_id"] for r in rows if r.get("user_id")]


def _tenant_ids(db) -> list[str]:
    return [t["id"] for t in paged(lambda: db.table("tenants").select("id"))]


def _month_numbers(db, tenant_id: str, period: Period) -> tuple[int, int]:
    deals = won_deals(db, tenant_id, period)
    return sum(sales_before_gst(d) for d in deals), len(new_chats(db, tenant_id, period))


def send_monthly_report_bells(now: datetime | None = None) -> int:
    """Bell + push to each owner on the 1st (to the 3rd if missed). Returns how many owners were rung."""
    try:
        db = get_supabase()
        today, month, period, _ = _last_month(now)
        if today.day > CATCH_UP_DAYS:
            return 0
        from app.services.notify import notify_user
        rung = 0
        for tenant_id in safe(lambda: _tenant_ids(db), [], "tenants"):
            try:
                sales, customers = _month_numbers(db, tenant_id, period)
                if not sales and not customers:  # a quiet shop gets no bell
                    continue
                if not _claim(db, tenant_id, MONTHLY_KEY, month):
                    continue
                name = period.start.strftime("%B")
                parts = ([f"{money(sales)} sales"] if sales else []) + [plural(customers, "new customer")]
                for user_id in _owners(db, tenant_id):
                    notify_user(tenant_id, user_id, BELL_TYPE, f"Your report for {name}", f"Your report for {name}: {', '.join(parts)}.",
                                db=db, push_url=f"/dashboard/analytics?tab=overview&month={month}")
                    rung += 1
            except Exception as e:
                logger.warning("monthly report bell failed for %s: %s", tenant_id, e)
        return rung
    except Exception as e:
        logger.warning("monthly report bells failed: %s", e)
        return 0


def send_accountant_file_bells(now: datetime | None = None) -> int:
    """Bell + push to each owner on the 5th (to the 7th if missed). Returns how many owners were rung."""
    try:
        db = get_supabase()
        today, month, period, _ = _last_month(now)
        if not 5 <= today.day < 5 + CATCH_UP_DAYS:
            return 0
        from app.services.notify import notify_user
        rung = 0
        for tenant_id in safe(lambda: _tenant_ids(db), [], "tenants"):
            try:
                if not won_deals(db, tenant_id, period):  # nothing sold last month: no file to send
                    continue
                if not _claim(db, tenant_id, ACCOUNTANT_KEY, month):
                    continue
                for user_id in _owners(db, tenant_id):
                    notify_user(tenant_id, user_id, BELL_TYPE, "Accountant file is ready",
                                "Last month's accountant file is ready.", db=db,
                                push_url=f"/dashboard/analytics?tab=money&accountant=1&month={month}")
                    rung += 1
            except Exception as e:
                logger.warning("accountant file bell failed for %s: %s", tenant_id, e)
        return rung
    except Exception as e:
        logger.warning("accountant file bells failed: %s", e)
        return 0


def send_due_bells(now: datetime | None = None) -> dict:
    """The daily job's one call: the monthly report bell, then the accountant file bell.
    One failing never stops the other."""
    out = {"monthly_report": 0, "accountant_file": 0}
    for key, fn in (("monthly_report", send_monthly_report_bells), ("accountant_file", send_accountant_file_bells)):
        try:
            out[key] = fn(now)
        except Exception as e:  # noqa: BLE001 — a bell must never break the job
            logger.error(f"reports bells {key} failed: {type(e).__name__}: {e}")
    return out
