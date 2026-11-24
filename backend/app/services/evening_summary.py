"""v9.2 #26 Evening summary: one WhatsApp to the owner at 8 PM IST with today's chats, new customers, orders
and money. OFF by default. It goes out only through the approved template `anril_evening_summary`; until
WhatsApp approves it the job skips and the page says "Waiting for WhatsApp to approve".

The planner schedules send_evening_summaries(db) at 20:00 IST. A business gets at most one a day
(last_sent_on in its setting), so a re-run or retry never sends twice."""
import asyncio
import logging

from app.services.number_jobs import sender_for
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from app.services.automation_store import (
    owner_phone, read_setting, settings_rows, template_status_of, write_setting,
)

logger = logging.getLogger(__name__)

SETTING_KEY = "evening_summary"
TEMPLATE_NAME = "anril_evening_summary"
TEMPLATE_BODY = (
    "Your day at {{1}}: {{2}} chats, {{3}} new customers, {{4}} orders. {{5}} Open Anril for the details."
)
TEMPLATE_EXAMPLES = ["Sri Stores", "24", "6", "3", "Money in today: ₹12,450."]
SEND_HOUR_IST = 20
IST = timezone(timedelta(hours=5, minutes=30))
_PAGE = 1000          # PostgREST returns at most 1000 rows a request, whatever .limit() says


def get_settings(db, tenant_id: str) -> dict:
    s = read_setting(db, tenant_id, SETTING_KEY)
    status = template_status_of(db, tenant_id, TEMPLATE_NAME)
    return {
        "on": bool(s.get("on")),
        "template_name": TEMPLATE_NAME,
        "template_status": status,
        "waiting_for_approval": status != "APPROVED",
        "note": "Waiting for WhatsApp to approve" if status != "APPROVED" else None,
        "last_sent_on": s.get("last_sent_on"),
        "sends_at": "8 PM",
        "template_body": TEMPLATE_BODY,
    }


def save_on(db, tenant_id: str, on: bool) -> dict:
    s = read_setting(db, tenant_id, SETTING_KEY)
    s["on"] = bool(on)
    write_setting(db, tenant_id, SETTING_KEY, s)
    return get_settings(db, tenant_id)


def rupees_text(paise: int) -> str:
    """12345600 paise -> '1,23,456' (Indian digit grouping). Whole rupees when exact, two decimals when not
    (50 paise -> '0.50'), the same rule as the other money helpers."""
    paise = max(0, int(paise))
    n = paise // 100
    if paise % 100:
        return f"{_group(n)}.{paise % 100:02d}"
    return _group(n)


def _group(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def _day_bounds(now: datetime) -> tuple[str, str]:
    from app.services.telecaller_performance import ist_day_bounds
    return ist_day_bounds(now)


def _paged(build) -> list[dict]:
    """Every row of a query, past the 1000-row API cap. build() returns a fresh query; pages are ordered by id
    so a page boundary never skips or repeats a row."""
    out: list[dict] = []
    while True:
        rows = build().order("id").range(len(out), len(out) + _PAGE - 1).execute().data or []
        out.extend(rows)
        if len(rows) < _PAGE:
            return out


def _count(query) -> int:
    return int(query.limit(1).execute().count or 0)


def build_summary(db, tenant_id: str, now: datetime | None = None) -> dict:
    """Today's (IST) numbers. A part that cannot be read counts as 0 rather than stopping the message."""
    now = now or datetime.now(timezone.utc)
    start, end = _day_bounds(now)

    def safe(fn, default=0):
        try:
            return fn()
        except Exception as e:
            logger.warning(f"evening summary: a part could not be read for {tenant_id}: {e}")
            return default

    def chats() -> int:
        rows = _paged(lambda: (
            db.table("messages").select("lead_id").eq("tenant_id", tenant_id).eq("direction", "inbound")
            .gte("created_at", start).lt("created_at", end)
        ))
        return len({r["lead_id"] for r in rows if r.get("lead_id")})

    def new_leads() -> int:
        return _count(db.table("leads").select("id", count="exact").eq("tenant_id", tenant_id)
                      .gte("created_at", start).lt("created_at", end))

    def orders() -> int:
        return _count(db.table("deals").select("id", count="exact").eq("tenant_id", tenant_id).eq("stage", "won")
                      .gte("won_at", start).lt("won_at", end))

    def money() -> int:
        """Payments in today less refunds given today (not failed), the same rule as Home's Money in."""
        paid = _paged(lambda: (
            db.table("deal_payments").select("amount_paise").eq("tenant_id", tenant_id)
            .gte("paid_at", start).lt("paid_at", end)
        ))
        refunded = _paged(lambda: (
            db.table("deal_refunds").select("amount_paise").eq("tenant_id", tenant_id).neq("status", "failed")
            .gte("created_at", start).lt("created_at", end)
        ))
        net = sum(int(r.get("amount_paise") or 0) for r in paid) - sum(int(r.get("amount_paise") or 0) for r in refunded)
        return max(0, net)

    return {"chats": safe(chats), "new_leads": safe(new_leads), "orders": safe(orders), "money_paise": safe(money)}


def template_values(business: str, summary: dict) -> list[str]:
    """The five {{n}} values: business, chats, new customers, orders, the money line (empty day: no payments)."""
    paise = int(summary.get("money_paise") or 0)
    money_line = f"Money in today: ₹{rupees_text(paise)}." if paise > 0 else "No payments today."
    name = " ".join((business or "your business").split())[:60] or "your business"
    return [name, str(summary.get("chats", 0)), str(summary.get("new_leads", 0)),
            str(summary.get("orders", 0)), money_line]


def _run(coro):
    """Run a coroutine from a plain (scheduler) thread, even when this thread already has a running loop."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _approved_template(db, tenant_id: str) -> dict | None:
    from app.services.call_details_share import _approved_templates
    try:
        return next((t for t in _approved_templates(db, tenant_id) if t.get("name") == TEMPLATE_NAME), None)
    except Exception as e:
        logger.warning(f"evening summary: templates not read for {tenant_id}: {e}")
        return None


def _business_name(db, tenant_id: str) -> str:
    try:
        rows = db.table("tenants").select("name").eq("id", tenant_id).limit(1).execute().data or []
        return (rows[0].get("name") if rows else "") or ""
    except Exception:
        return ""


def send_one(db, tenant_id: str, setting: dict, now: datetime) -> bool:
    """Send this business's summary. False when it is skipped (not approved, no number, already sent today)."""
    today = (now.astimezone(IST)).date().isoformat()
    if setting.get("last_sent_on") == today:
        return False
    template = _approved_template(db, tenant_id)
    if not template:
        return False                      # "Waiting for WhatsApp to approve"
    phone = owner_phone(db, tenant_id)
    if not phone:
        logger.info(f"evening summary: no owner number for {tenant_id}")
        return False
    values = template_values(_business_name(db, tenant_id), build_summary(db, tenant_id, now))
    components = [{"type": "body", "parameters": [{"type": "text", "text": v} for v in values]}]
    from app.services.meta_cloud import send_template_message
    try:
        resp = _run(send_template_message(
            phone, template["name"], template.get("language") or "en", components=components,
            tenant_id=tenant_id, skip_blocked_check=True,      # to the business's own owner, not a customer
            phone_number_id=sender_for(db, tenant_id, "alerts"),  # an alert to the owner: picked number, else Main
        ))
    except Exception as e:
        logger.warning(f"evening summary: not sent for {tenant_id}: {e}")
        return False
    if not ((resp or {}).get("messages") or [{}])[0].get("id"):
        return False
    setting["last_sent_on"] = today
    try:
        write_setting(db, tenant_id, SETTING_KEY, setting)
    except Exception as e:
        logger.warning(f"evening summary: sent but not recorded for {tenant_id}: {e}")
    return True


def send_evening_summaries(db, now: datetime | None = None) -> int:
    """Send the summary to every business that has it on. Returns how many were sent."""
    now = now or datetime.now(timezone.utc)
    sent = 0
    for row in settings_rows(db, SETTING_KEY):
        if not row["value"].get("on"):
            continue
        try:
            if send_one(db, row["tenant_id"], dict(row["value"]), now):
                sent += 1
        except Exception as e:
            logger.error(f"evening summary failed for {row['tenant_id']}: {e}")
    return sent


async def submit_template(db, tenant_id: str) -> dict:
    """Send anril_evening_summary to WhatsApp for approval (Utility, English) through the Templates page's own path."""
    from fastapi import HTTPException
    from app.routes.templates import CreateTemplate, create_template_record

    problems: list[str] = []
    if template_status_of(db, tenant_id, TEMPLATE_NAME) in (None, "REJECTED"):
        try:
            await create_template_record(
                CreateTemplate(name=TEMPLATE_NAME, category="UTILITY", language="en", body_text=TEMPLATE_BODY,
                               body_examples=TEMPLATE_EXAMPLES),
                tenant_id,
            )
        except HTTPException as e:
            problems.append(str(e.detail))
        except Exception as e:
            logger.warning(f"evening summary: template did not submit: {e}")
            problems.append("The message could not be sent to WhatsApp for approval. Please try again.")
    return {"template_status": template_status_of(db, tenant_id, TEMPLATE_NAME), "problems": problems}
