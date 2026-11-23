"""Reports: the shared reads. Every query filters tenant_id; nothing here writes."""
from app.services.inbound_leads_logic import INBOUND_SOURCES
from app.services.reports_common import Period, chunks, paged, safe

WON_COLUMNS = ("id,lead_id,total_paise,gst_paise,paid_paise,refunded_paise,bill_type,buyer_gstin,buyer_business,"
               "sold_by,sold_by_ai,created_by,customer_name,invoice_number,won_at,payment_method,deal_number,channel")
LEAD_COLUMNS = "id,name,phone,source,segment,created_at,converted_at,lost_at,booked_at,ad_campaign_id,qr_link_id"


def won_deals(db, tenant_id: str, period: Period) -> list[dict]:
    """Orders that were paid (stage won) with won_at inside the days."""
    return paged(lambda: db.table("deals").select(WON_COLUMNS).eq("tenant_id", tenant_id).eq("stage", "won")
                 .gte("won_at", period.start_iso).lt("won_at", period.end_iso))


def sales_before_gst(deal: dict) -> int:
    return int(deal.get("total_paise") or 0) - int(deal.get("gst_paise") or 0)


def new_leads(db, tenant_id: str, period: Period) -> list[dict]:
    """Everyone whose record was created in the days (any channel)."""
    return paged(lambda: db.table("leads").select(LEAD_COLUMNS).eq("tenant_id", tenant_id)
                 .is_("deleted_at", "null").gte("created_at", period.start_iso).lt("created_at", period.end_iso))


def new_chats(db, tenant_id: str, period: Period) -> list[dict]:
    """New people who came in through a chat channel (WhatsApp, Instagram, QR, Instant form...)."""
    return [lead for lead in new_leads(db, tenant_id, period) if (lead.get("source") or "") in INBOUND_SOURCES]


def is_hot(lead: dict) -> bool:
    return (lead.get("segment") or "").upper() == "A"


def buyers_split(db, tenant_id: str, period: Period, deals: list[dict]) -> dict:
    """Buyers in the days, split into first-time and repeat. Repeat = had a paid order before the days."""
    lead_ids = sorted({d["lead_id"] for d in deals if d.get("lead_id")})
    earlier: set[str] = set()
    for part in chunks(lead_ids):
        rows = paged(lambda part=part: db.table("deals").select("id,lead_id").eq("tenant_id", tenant_id)
                     .eq("stage", "won").in_("lead_id", part).lt("won_at", period.start_iso))
        earlier |= {r["lead_id"] for r in rows if r.get("lead_id")}
    repeat = [i for i in lead_ids if i in earlier]
    new = [i for i in lead_ids if i not in earlier]
    return {"buyer_ids": lead_ids, "repeat_ids": repeat, "new_ids": new}


def money_in(db, tenant_id: str, period: Period) -> int:
    """Money received in the days, less refunds (the same number Home and the target bar use)."""
    pays = paged(lambda: db.table("deal_payments").select("id,amount_paise").eq("tenant_id", tenant_id)
                 .gte("paid_at", period.start_iso).lt("paid_at", period.end_iso))
    refunds = paged(lambda: db.table("deal_refunds").select("id,amount_paise").eq("tenant_id", tenant_id)
                    .neq("status", "failed").gte("created_at", period.start_iso).lt("created_at", period.end_iso))
    return sum(int(p["amount_paise"]) for p in pays) - sum(int(r["amount_paise"]) for r in refunds)


def call_numbers(db, tenant_id: str, period: Period) -> dict:
    """Calls placed by the team (an owner's own calls, with no caller, are left out, as on the Calls page)."""
    rows = paged(lambda: db.table("call_logs").select("id,caller_id,manual_status,outcome,duration_seconds")
                 .eq("tenant_id", tenant_id).gte("created_at", period.start_iso).lt("created_at", period.end_iso))
    rows = [r for r in rows if r.get("caller_id") is not None]
    return {
        "calls": len(rows),
        "connected_calls": sum(1 for r in rows if r.get("manual_status") == "connected"),
        "sales_from_calls": sum(1 for r in rows if r.get("outcome") == "converted"),
        "talk_minutes": round(sum(int(r.get("duration_seconds") or 0) for r in rows) / 60),
    }


def booking_count(db, tenant_id: str, period: Period) -> int | None:
    """Bookings for the days that are still on (booked or came). None when bookings aren't set up."""
    def read():
        rows = paged(lambda: db.table("bookings").select("id,status").eq("tenant_id", tenant_id)
                     .gte("booking_date", period.start.isoformat()).lt("booking_date", period.end_excl_day.isoformat()))
        return sum(1 for r in rows if r.get("status") in ("booked", "came"))
    return safe(read, None, "bookings")


def modules_in_use(db, tenant_id: str) -> dict:
    """Which parts of the business this tenant actually uses (picks the Overview cards)."""
    def any_row(table: str) -> bool:
        return bool(safe(lambda: db.table(table).select("id").eq("tenant_id", tenant_id).limit(1).execute().data,
                         [], table))
    return {"orders": any_row("deals"), "calls": any_row("call_logs"), "ads": any_row("ad_campaigns"),
            "bookings": any_row("bookings")}
