"""Commerce > Orders & payments: every sale, online and in the shop, as one order book.

An order is a deals row (services/deals.py keeps the stage, stock and payment rules). This
module adds what the Orders screens need on top:
  - the bill maths (discount spread over the lines, GST inside or on top, simple bill);
  - invoice numbers per financial year ("2026-27/0042") and the customer's bill link;
  - the list, its money cards and chips, and each row's next step;
  - New bill (shop counter): taken now or delivered later, advance, walk-in with no number;
  - delivery steps (working on it, ready, shipped with tracking, delivered);
  - WhatsApp updates to the customer: a normal message inside the 24-hour window, else the
    order's approved template, else a "Share on WhatsApp" link for the staff member's phone;
  - payment reminders on day 1, 3 and 7, stopped once paid.
"""
import logging
import os
import re
import secrets
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote

from app.db.supabase import get_supabase
from app.services import deals as deals_service
from app.services.deals import DealError, balance_paise, format_deal_number, _rupees

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
CARD_METHODS = ("cash", "upi", "card")
METHOD_LABELS = {"cash": "Cash", "upi": "UPI", "card": "Card", "razorpay": "Link", "bank_transfer": "Bank", "other": "Other"}
REMINDER_DAYS = (1, 3, 7)
REMINDER_HOURS_IST = (10, 19)  # only between 10 AM and 7 PM

# The three utility templates the owner submits once (Orders > Set up WhatsApp messages).
# {{n}} order is fixed here, so sending fills them without any mapping step.
ORDER_TEMPLATES = {
    "bill": {
        "name": "anril_order_bill",
        "body": "Vanakkam {{1}}, thank you for shopping at {{2}}. Your bill {{3}} for {{4}} is here: {{5}}",
        "examples": ["Priya", "Demo Silks", "2026-27/0042", "₹10,500", "https://www.anrilaitech.com/bill/abc123"],
    },
    "update": {
        "name": "anril_order_update",
        "body": "Vanakkam {{1}}, an update on your order {{2}} from {{3}}: {{4}}. Details: {{5}}",
        "examples": ["Priya", "D-1047", "Demo Silks", "it is ready for pickup, balance ₹7,500", "https://rzp.io/l/abc"],
    },
    "reminder": {
        "name": "anril_payment_reminder",
        "body": "Vanakkam {{1}}, a gentle reminder from {{2}}: {{3}} is still to pay for order {{4}}. You can pay here: {{5}}",
        "examples": ["Priya", "Demo Silks", "₹7,500", "D-1047", "https://rzp.io/l/abc"],
    },
    "quote": {
        "name": "anril_order_quote",
        "body": "Vanakkam {{1}}, here is your quote {{2}} from {{3}}: {{4}}. Total {{5}}. Tap Accept quote to confirm it.",
        "examples": ["Suresh", "D-1052", "Demo Silks", "Cotton saree x 100, Silk-cotton saree x 40", "₹1,14,000"],
        "buttons": ["Accept quote", "Ask a question"],
    },
    # The bill itself on top of the message: a receipt picture for a simple bill, the tax
    # invoice PDF for a GST bill (services/bill_files.py). {{4}} carries any balance.
    "bill_picture": {
        "name": "anril_bill_picture",
        "header": "IMAGE",
        "body": "Nandri {{1}}! 🙏 Your bill {{2}} from {{3}} for {{4}} is above.",
        "examples": ["Kavitha", "2026-27/0045", "Demo Silks", "₹3,800"],
        "footer": "Again vaanga!",
        "view_bill": True,
    },
    "bill_pdf": {
        "name": "anril_bill_pdf",
        "header": "DOCUMENT",
        "body": "Vanakkam {{1}} 🙏 Your GST invoice {{2}} from {{3}} for {{4}} is attached.",
        "examples": ["Kavitha", "2026-27/0045", "Demo Silks", "₹3,800"],
        "footer": "Again vaanga!",
        "view_bill": True,
    },
}
VIEW_BILL_EXAMPLE = "sample-bill-link"  # what Meta's reviewer sees after /bill/
TEMPLATE_FOR_KIND = {"bill": "bill", "confirmed": "update", "ready": "update", "shipped": "update",
                     "delivered": "update", "refund": "update", "pay_link": "reminder", "reminder": "reminder",
                     "quote": "quote", "quote_reminder": "quote"}
QUOTE_ACCEPT = "quote_accept:"
QUOTE_ASK = "quote_ask:"


class OrderError(ValueError):
    """Something staff can fix; routes turn it into a 400."""


SETTINGS_KEY = "orders_settings"
WORKING_LABELS = ("Working on it", "Stitching", "Packing", "Preparing", "Repairing", "Printing")
DEFAULT_SETTINGS = {"working_label": "Working on it", "google_review_link": ""}


def order_settings(tenant_id: str) -> dict:
    """The shop's order settings: the middle step's name and the Google review link."""
    import json
    from app.config_dynamic import get_setting
    raw = get_setting(SETTINGS_KEY, fallback=None, tenant_id=tenant_id)
    try:
        saved = json.loads(raw) if raw else {}
    except ValueError:
        saved = {}
    out = dict(DEFAULT_SETTINGS)
    for key in out:
        value = (saved or {}).get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def save_order_settings(db, tenant_id: str, data: dict) -> dict:
    import json
    from app.config_dynamic import invalidate_cache
    label = " ".join(str(data.get("working_label") or "").split())[:30] or DEFAULT_SETTINGS["working_label"]
    link = str(data.get("google_review_link") or "").strip()[:300]
    if link and not re.match(r"^https://[^\s]+$", link):
        raise OrderError("The review link must start with https://")
    clean = {"working_label": label, "google_review_link": link}
    db.table("app_settings").upsert({
        "tenant_id": tenant_id, "key": SETTINGS_KEY, "value": json.dumps(clean), "is_secret": False,
        "updated_at": "now()",
    }, on_conflict="tenant_id,key").execute()
    invalidate_cache(SETTINGS_KEY)
    return clean


# ─────────────────────────────────────────────────────────────── small helpers

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def fiscal_year(at: datetime) -> str:
    """Indian financial year, April to March: 19 Nov 2026 -> "2026-27"."""
    local = at.astimezone(IST)
    start = local.year if local.month >= 4 else local.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def order_label(deal: dict) -> str:
    return format_deal_number(int(deal.get("deal_number") or 0))


def bill_url(token: str | None) -> str | None:
    if not token:
        return None
    base = (os.environ.get("FRONTEND_URL") or "https://www.anrilaitech.com").rstrip("/")
    return f"{base}/bill/{token}"


def _first_name(name: str | None) -> str:
    return ((name or "").strip().split(" ") or [""])[0] or "there"


def _one_line(text: str) -> str:
    return " ".join((text or "").split())


def _shop_name(db, tenant_id: str) -> str:
    from app.services.business_details import get_business_details
    details = get_business_details(tenant_id, db) or {}
    return (details.get("legal_name") or "").strip() or "our shop"


# ─────────────────────────────────────────────────────────────── bill maths

def compute_bill(lines: list[dict], *, discount_paise: int, include_gst: bool, bill_type: str) -> dict:
    """Totals for a bill. lines are resolved deal lines (unit_price_paise, qty, gst_rate).
    The discount is spread over the lines by value (the last line takes the rounding), so
    each line's GST is on what was really charged. A simple bill shows and adds no GST."""
    gross = [int(li["unit_price_paise"]) * int(li["qty"]) for li in lines]
    subtotal = sum(gross)
    discount = max(0, min(int(discount_paise or 0), subtotal))
    shares, given = [], 0
    for i, g in enumerate(gross):
        share = discount - given if i == len(gross) - 1 else (discount * g // subtotal if subtotal else 0)
        shares.append(share)
        given += share
    out_lines, gst_total, total = [], 0, 0
    for li, g, share in zip(lines, gross, shares):
        charged = g - share
        rate = float(li.get("gst_rate") or 0) if bill_type == "gst" else 0.0
        if rate and include_gst:
            gst = round(charged * rate / (100 + rate))
            line_total = charged
        elif rate:
            gst = round(charged * rate / 100)
            line_total = charged + gst
        else:
            gst, line_total = 0, charged
        gst_total += gst
        total += line_total
        out_lines.append({**li, "discount_paise": share, "gst_paise": gst, "taxable_paise": line_total - gst,
                          "charged_paise": line_total})
    return {"subtotal_paise": subtotal, "discount_paise": discount, "gst_paise": gst_total,
            "total_paise": total, "lines": out_lines}


def gst_split(seller_gstin: str | None, buyer_gstin: str | None, gst_paise: int) -> dict:
    """CGST + SGST inside the state; IGST when the buyer's GSTIN is from another state."""
    seller_state = (seller_gstin or "")[:2]
    buyer_state = (buyer_gstin or "")[:2]
    if gst_paise and seller_state and buyer_state and seller_state != buyer_state:
        return {"igst_paise": gst_paise, "cgst_paise": 0, "sgst_paise": 0}
    half = gst_paise // 2
    return {"igst_paise": 0, "cgst_paise": gst_paise - half, "sgst_paise": half}


# ─────────────────────────────────────────────────────────────── invoice

def _rpc_int(data) -> int | None:
    if isinstance(data, list):
        data = data[0] if data else None
    if isinstance(data, dict):
        data = next(iter(data.values()), None)
    return int(data) if data is not None else None


def ensure_invoice(db, tenant_id: str, deal_id: str) -> str | None:
    """Give a paid (or part-paid) order its invoice number and bill link, once. Online and
    shop orders share the numbering. Never raises: a missing number must not lose a sale."""
    try:
        row = (
            db.table("deals").select("id, invoice_number, bill_token, created_at")
            .eq("id", deal_id).eq("tenant_id", tenant_id).maybe_single().execute()
        )
        deal = (row.data if row else None) or {}
        if not deal or deal.get("invoice_number"):
            return deal.get("invoice_number")
        fy = fiscal_year(_now())
        n = _rpc_int(db.rpc("next_invoice_number", {"p_tenant_id": tenant_id, "p_fy": fy}).execute().data)
        if n is None:
            return None
        number = f"{fy}/{n:04d}"
        patch = {"invoice_number": number, "invoice_issued_at": _now().isoformat()}
        if not deal.get("bill_token"):
            patch["bill_token"] = secrets.token_urlsafe(16)
        db.table("deals").update(patch).eq("id", deal_id).eq("tenant_id", tenant_id).is_("invoice_number", "null").execute()
        return number
    except Exception as e:
        logger.warning(f"Invoice number for deal {deal_id} failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────── states shown on screen

def payment_state(deal: dict) -> str:
    """paid | advance | waiting | quote | cancelled"""
    stage = deal.get("stage")
    if stage == "won":
        return "paid"
    if stage == "lost":
        return "cancelled"
    if int(deal.get("paid_paise") or 0) > 0:
        return "advance"
    if stage == "awaiting_payment":
        return "waiting"
    return "quote"


def delivery_state(deal: dict) -> str:
    """taken | none | working | ready | shipped | delivered (how it reaches the customer)."""
    if deal.get("handover") == "taken":
        return "taken"
    return deal.get("delivery_status") or "none"


def has_product(deal: dict) -> bool:
    """A line that is a product (a consultation or other service has nothing to pack)."""
    for item in deal.get("deal_items") or []:
        catalog = item.get("catalog_items")
        if isinstance(catalog, list):
            catalog = catalog[0] if catalog else None
        if (catalog or {}).get("item_type") == "product":
            return True
    return False


def needs_packing(deal: dict) -> bool:
    """To pack or ship: someone paid something, and it hasn't left the shop yet. An online
    order made before delivery steps existed counts only when it has a product in it."""
    if deal.get("stage") == "lost" or deal.get("handover") == "taken":
        return False
    if payment_state(deal) not in ("paid", "advance"):
        return False
    if not deal.get("handover") and not has_product(deal):
        return False
    if deal.get("handover") == "courier":
        return delivery_state(deal) not in ("shipped", "delivered")
    return delivery_state(deal) not in ("ready", "delivered")


def next_action(deal: dict) -> str:
    """The row's button: remind | collect | tracking | ready | open."""
    state = payment_state(deal)
    if state == "waiting":
        return "remind"
    if state == "advance":
        return "collect"
    if state == "paid" and needs_packing(deal):
        return "tracking" if deal.get("handover") == "courier" else "ready"
    return "open"


CHIPS = ("all", "waiting", "advance", "paid", "pack", "quote", "cancelled")


def chip_of(deal: dict) -> set[str]:
    chips = {"all", payment_state(deal)}
    if needs_packing(deal):
        chips.add("pack")
    return chips


# ─────────────────────────────────────────────────────────────── list + cards

ORDER_SELECT = (
    "id, deal_number, stage, source, channel, handover, delivery_status, total_paise, paid_paise, gst_paise, "
    "bill_type, payment_link, link_expires_at, lost_reason, created_at, won_at, courier, tracking_id, "
    "customer_name, lead_id, reminders_from, reminders_sent, invoice_number, refunded_paise, quote_valid_until, "
    "leads(id, name, phone, source, ad_name, ad_campaign_id), "
    "deal_items(name, qty, variant_label, catalog_items(item_type)), deal_payments(amount_paise, method, paid_at)"
)

SOURCE_LABELS = {"whatsapp": "WhatsApp", "instagram": "Instagram", "facebook": "Facebook", "telegram": "Telegram",
                 "store": "Store", "manual": "Added by hand", "upload": "Imported", "website": "Website",
                 "indiamart": "IndiaMART", "justdial": "JustDial", "meta_form": "Instant form", "api": "API"}


def _since(days: int | None) -> datetime | None:
    if not days:
        return None
    today = _now().astimezone(IST).date()
    return datetime.combine(today - timedelta(days=days - 1), time.min, IST)


def _came_from(deal: dict, lead: dict) -> str:
    if deal.get("channel") == "store" and not lead:
        return "Walk-in"
    if lead.get("ad_campaign_id") or lead.get("ad_name"):
        return f"Ad · {lead['ad_name']}" if lead.get("ad_name") else "From an ad"
    if deal.get("channel") == "store":
        return "Store"
    return SOURCE_LABELS.get(lead.get("source") or "", (lead.get("source") or "").title() or "—")


def _items_text(items: list[dict]) -> str:
    parts = []
    for it in items:
        name = it.get("name") or "Item"
        if it.get("variant_label"):
            name += f" ({it['variant_label']})"
        parts.append(f"{name} × {it['qty']}" if int(it.get("qty") or 1) > 1 else name)
    return ", ".join(parts)


def _payment_note(deal: dict, payments: list[dict], now: datetime) -> str:
    state = payment_state(deal)
    refunded = int(deal.get("refunded_paise") or 0)
    if state == "cancelled" and refunded:
        return f"Refunded {_rupees(refunded)}"
    if refunded and state in ("paid", "advance"):
        return f"{_rupees(refunded)} refunded"
    methods = sorted({METHOD_LABELS.get(p.get("method"), "Other") for p in payments}, key=list(METHOD_LABELS.values()).index)
    if state == "paid":
        return "Paid by link" if methods == ["Link"] else " + ".join(methods) or "Paid"
    if state == "advance":
        paid = sum(int(p["amount_paise"]) for p in payments)
        return f"{' + '.join(methods)} {_rupees(paid)} · {_rupees(balance_paise(deal))} left"
    if state == "waiting":
        sent = _parse(deal.get("reminders_from"))
        if deal.get("payment_link") and sent:
            return f"Link sent {_ago(sent, now)}"
        return "Not paid yet"
    if state == "cancelled":
        return deal.get("lost_reason") or "Cancelled"
    if deal.get("quote_valid_until"):
        return f"Valid till {_day(deal['quote_valid_until'])}"
    return "Price sent"


def _day(iso: str) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return f"{d.day} {d.strftime('%b')}"


def _ago(at: datetime, now: datetime) -> str:
    mins = int((now - at).total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 1)}m ago"
    if mins < 60 * 24:
        return f"{mins // 60}h ago"
    return f"{mins // (60 * 24)}d ago"


def order_row(deal: dict, now: datetime | None = None) -> dict:
    now = now or _now()
    lead = deal.get("leads") or {}
    items = deal.get("deal_items") or []
    payments = deal.get("deal_payments") or []
    return {
        "id": deal["id"],
        "label": order_label(deal),
        "created_at": deal.get("created_at"),
        "channel": deal.get("channel") or "online",
        "customer": {
            "lead_id": deal.get("lead_id"),
            "name": (lead.get("name") or deal.get("customer_name") or "").strip() or None,
            "phone": lead.get("phone"),
            "came_from": _came_from(deal, lead),
        },
        "items": _items_text(items),
        "total_paise": int(deal.get("total_paise") or 0),
        "paid_paise": int(deal.get("paid_paise") or 0),
        "refunded_paise": int(deal.get("refunded_paise") or 0),
        "balance_paise": balance_paise(deal) if deal.get("stage") != "lost" else 0,
        "payment": payment_state(deal),
        "payment_note": _payment_note(deal, payments, now),
        "handover": deal.get("handover"),
        "delivery": delivery_state(deal),
        "courier": deal.get("courier"),
        "tracking_id": deal.get("tracking_id"),
        "needs_packing": needs_packing(deal),
        "next_action": next_action(deal),
        "invoice_number": deal.get("invoice_number"),
    }


def _match_search(row: dict, q: str) -> bool:
    q = q.lower().strip()
    hay = " ".join(str(v or "") for v in (row["label"], row["customer"]["name"], row["customer"]["phone"],
                                            row["items"], row["invoice_number"])).lower()
    digits = re.sub(r"\D", "", q)
    return q in hay or bool(digits and digits in re.sub(r"\D", "", hay))


def list_orders(db, tenant_id: str, *, chip: str = "all", channel: str | None = None, days: int | None = 30,
                q: str | None = None, limit: int = 1000) -> dict:
    """Orders in the period (created in the last `days`), the chip counts and the money cards.
    Every number follows the same channel + period filter as the table."""
    since = _since(days)
    query = db.table("deals").select(ORDER_SELECT).eq("tenant_id", tenant_id)
    if channel in ("online", "store"):
        query = query.eq("channel", channel)
    if since:
        query = query.gte("created_at", since.isoformat())
    deals = query.order("created_at", desc=True).limit(limit).execute().data or []
    now = _now()
    rows = [order_row(d, now) for d in deals]
    if q and q.strip():
        keep = {r["id"] for r in rows if _match_search(r, q)}
        deals = [d for d in deals if d["id"] in keep]
        rows = [r for r in rows if r["id"] in keep]
    counts = {c: 0 for c in CHIPS}
    for d in deals:
        for c in chip_of(d):
            counts[c] += 1
    wanted = chip if chip in CHIPS else "all"
    shown = [r for d, r in zip(deals, rows) if wanted in chip_of(d)]
    return {"data": shown, "counts": counts, "cards": _cards(db, tenant_id, deals, since, channel, now)}


def _cards(db, tenant_id: str, deals: list[dict], since: datetime | None, channel: str | None, now: datetime) -> dict:
    # Money in: payments received in the period, less refunds given in the period.
    pq = db.table("deal_payments").select("amount_paise, paid_at, deal_id, deals!inner(channel)").eq("tenant_id", tenant_id)
    rq = (
        db.table("deal_refunds").select("amount_paise, created_at, deals!inner(channel)")
        .eq("tenant_id", tenant_id).neq("status", "failed")
    )
    if since:
        pq = pq.gte("paid_at", since.isoformat())
        rq = rq.gte("created_at", since.isoformat())
    if channel in ("online", "store"):
        pq = pq.eq("deals.channel", channel)
        rq = rq.eq("deals.channel", channel)
    payments = pq.limit(10000).execute().data or []
    refunds = rq.limit(10000).execute().data or []
    money_in = sum(int(p.get("amount_paise") or 0) for p in payments) - sum(int(r.get("amount_paise") or 0) for r in refunds)
    paid_orders = len({p.get("deal_id") for p in payments})

    open_deals = [d for d in deals if payment_state(d) in ("waiting", "advance")]
    reminded = sum(1 for d in open_deals if d.get("reminders_from") and int(d.get("reminders_sent") or 0) < len(REMINDER_DAYS))
    pack = [d for d in deals if needs_packing(d)]
    late = sum(1 for d in pack if (_parse(d.get("created_at")) or now) < now - timedelta(days=2))
    gst_bills = [d for d in deals if d.get("stage") == "won" and d.get("bill_type", "gst") == "gst" and int(d.get("gst_paise") or 0) > 0]
    return {
        "money_in": {"paise": money_in, "orders": paid_orders,
                     "refunded_paise": sum(int(r.get("amount_paise") or 0) for r in refunds)},
        "to_collect": {"paise": sum(balance_paise(d) for d in open_deals), "orders": len(open_deals), "reminders_on": reminded},
        "to_pack": {"orders": len(pack), "over_2_days": late},
        "gst": {"paise": sum(int(d.get("gst_paise") or 0) for d in gst_bills), "bills": len(gst_bills)},
    }


# ─────────────────────────────────────────────────────────────── one order

def _load(db, tenant_id: str, deal_id: str) -> dict:
    res = db.table("deals").select("*").eq("id", deal_id).eq("tenant_id", tenant_id).maybe_single().execute()
    if not res or not res.data:
        raise OrderError("Order not found")
    return res.data


def order_detail(db, tenant_id: str, deal_id: str) -> dict:
    deal = _load(db, tenant_id, deal_id)
    items = (
        db.table("deal_items").select("id, catalog_item_id, variant_id, variant_label, name, qty, unit_price_paise, gst_rate, line_total_paise, catalog_items(item_type)")
        .eq("deal_id", deal_id).eq("tenant_id", tenant_id).order("created_at").execute()
    ).data or []
    payments = (
        db.table("deal_payments").select("id, amount_paise, method, kind, paid_at, received_by_caller, note")
        .eq("deal_id", deal_id).eq("tenant_id", tenant_id).order("paid_at").execute()
    ).data or []
    messages = (
        db.table("deal_messages").select("id, kind, sent_via, body, created_at, message_id")
        .eq("deal_id", deal_id).eq("tenant_id", tenant_id).order("created_at").execute()
    ).data or []
    ticks: dict[str, str] = {}
    ids = [m["message_id"] for m in messages if m.get("message_id")]
    if ids:
        rows = db.table("messages").select("id, delivery_status").eq("tenant_id", tenant_id).in_("id", ids).execute().data or []
        ticks = {r["id"]: r.get("delivery_status") or "sent" for r in rows}
    lead = {}
    order_count = 0
    if deal.get("lead_id"):
        res = (
            db.table("leads").select("id, name, phone, source, segment, ad_name, ad_campaign_id, last_inbound_at")
            .eq("id", deal["lead_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
        )
        lead = (res.data if res else None) or {}
        earlier = (
            db.table("deals").select("id").eq("tenant_id", tenant_id).eq("lead_id", deal["lead_id"])
            .neq("stage", "lost").lte("created_at", deal["created_at"]).execute()
        ).data or []
        order_count = len(earlier)
    caller_ids = sorted({c for c in [deal.get("sold_by"), *(p.get("received_by_caller") for p in payments)] if c})
    names = {}
    if caller_ids:
        rows = db.table("callers").select("id, name").eq("tenant_id", tenant_id).in_("id", caller_ids).execute().data or []
        names = {r["id"]: r.get("name") for r in rows}
    refunds = (
        db.table("deal_refunds").select("id, amount_paise, method, reason, status, credit_note_number, created_at")
        .eq("deal_id", deal_id).eq("tenant_id", tenant_id).order("created_at").execute()
    ).data or []
    from app.services.business_details import get_business_details
    business = get_business_details(tenant_id, db) or {}
    ready_preview = None
    if deal.get("stage") != "lost" and deal.get("handover") not in ("taken",) and deal.get("delivery_status") not in ("ready", "shipped", "delivered"):
        ready_preview = compose(db, tenant_id, {**deal, "payment_link": deal.get("payment_link") or "(pay link)"}, "ready")[0] \
            if balance_paise(deal) > 0 else compose(db, tenant_id, deal, "ready")[0]
    return {
        **order_row({**deal, "leads": lead, "deal_items": items, "deal_payments": payments}),
        "refunds": [{**r, "method_label": METHOD_LABELS.get(r["method"], "Other")} for r in refunds],
        "refundable_paise": max(int(deal.get("paid_paise") or 0) - int(deal.get("refunded_paise") or 0), 0),
        "razorpay_refundable_paise": _razorpay_refundable(db, tenant_id, deal_id),
        "quote": {
            "valid_until": deal.get("quote_valid_until"), "sent_at": deal.get("quote_sent_at"),
            "accepted_at": deal.get("accepted_at"), "advance_paise": int(deal.get("advance_paise") or 0),
            "ready_in_days": deal.get("ready_in_days"),
        },
        "ready_preview": ready_preview,
        "advance_note": deal.get("advance_note"),
        "returnable": _returnable(db, tenant_id, deal_id),
        "settings": {"working_label": order_settings(tenant_id)["working_label"]},
        "stage": deal.get("stage"),
        "source": deal.get("source"),
        "items_full": items,
        "discount_paise": int(deal.get("discount_paise") or 0),
        "gst_paise": int(deal.get("gst_paise") or 0),
        "bill_type": deal.get("bill_type") or "gst",
        "buyer_gstin": deal.get("buyer_gstin"),
        "buyer_business": deal.get("buyer_business"),
        "prices_include_gst": bool(business.get("prices_include_gst", True)),
        "notes": deal.get("notes"),
        "ready_by": deal.get("ready_by"),
        "ready_at": deal.get("ready_at"),
        "shipped_at": deal.get("shipped_at"),
        "delivered_at": deal.get("delivered_at"),
        "won_at": deal.get("won_at"),
        "lost_reason": deal.get("lost_reason"),
        "payment_link": deal.get("payment_link"),
        "invoice_issued_at": deal.get("invoice_issued_at"),
        "bill_url": bill_url(deal.get("bill_token")),
        # The picture / PDF WhatsApp carries; a quote has none.
        "bill_file_url": bill_file_url(deal["bill_token"], (deal.get("bill_type") or "gst") == "gst")
        if deal.get("bill_token") and deal.get("stage") != "quoted" else None,
        "sold_by": {"name": names.get(deal.get("sold_by")) if deal.get("sold_by") else None, "ai": bool(deal.get("sold_by_ai"))},
        "payments": [
            {**p, "received_by_name": names.get(p.get("received_by_caller")), "method_label": METHOD_LABELS.get(p["method"], "Other")}
            for p in payments
        ],
        "messages": [
            {**m, "ticks": ticks.get(m.get("message_id") or "", "shared" if m["sent_via"] == "share" else "sent")}
            for m in messages
        ],
        "upcoming": _upcoming(deal),
        "customer_full": {
            "lead_id": lead.get("id"), "name": lead.get("name") or deal.get("customer_name"), "phone": lead.get("phone"),
            "segment": lead.get("segment"), "came_from": _came_from(deal, lead), "order_count": order_count,
        },
        "reminders": {"sent": int(deal.get("reminders_sent") or 0), "from": deal.get("reminders_from"),
                      "last_at": deal.get("last_reminder_at")},
    }


def _returnable(db, tenant_id: str, deal_id: str) -> dict[str, int]:
    try:
        from app.services.order_refunds import returnable_items
        return returnable_items(db, tenant_id, deal_id)
    except Exception as e:
        logger.warning(f"Returnable items for {deal_id} failed: {e}")
        return {}


def _razorpay_refundable(db, tenant_id: str, deal_id: str) -> int:
    """How much of this order was paid by Razorpay and not yet refunded through it."""
    paid = (
        db.table("deal_payments").select("amount_paise").eq("tenant_id", tenant_id).eq("deal_id", deal_id)
        .eq("method", "razorpay").not_.is_("razorpay_payment_id", "null").execute()
    ).data or []
    back = (
        db.table("deal_refunds").select("amount_paise").eq("tenant_id", tenant_id).eq("deal_id", deal_id)
        .eq("method", "razorpay").neq("status", "failed").execute()
    ).data or []
    return max(sum(int(p["amount_paise"]) for p in paid) - sum(int(r["amount_paise"]) for r in back), 0)


def _upcoming(deal: dict) -> list[dict]:
    """What goes out next, for the order page: messages tied to a step (no time, "when you
    tap Ready") and the reminders that go by themselves (with a time)."""
    out = []
    if deal.get("stage") == "lost":
        return out
    if deal.get("stage") != "quoted" and deal.get("handover") != "taken" and deal.get("delivery_status") != "delivered":
        courier = deal.get("handover") == "courier"
        if deal.get("delivery_status") not in ("ready", "shipped"):
            out.append({"kind": "ready", "at": None, "note": "when you tap Packed" if courier else "when you tap Ready"})
        if courier and deal.get("delivery_status") != "shipped":
            out.append({"kind": "shipped", "at": None, "note": "when you add the tracking ID"})
        out.append({"kind": "delivered", "at": None, "note": "after it's delivered" if courier else "after they pick it up"})
    if deal.get("stage") == "won":
        return out
    if deal.get("stage") == "quoted" and deal.get("quote_sent_at"):
        sent = _parse(deal["quote_sent_at"])
        if sent and not deal.get("quote_reminded_at"):
            out.append({"kind": "quote_reminder", "at": (sent + timedelta(days=2)).isoformat(), "note": "only if no reply"})
        if deal.get("quote_valid_until"):
            out.append({"kind": "quote_expiry", "at": f"{deal['quote_valid_until']}T23:59:00+05:30", "note": "marked Quote expired if not accepted"})
        return out
    start = _parse(deal.get("reminders_from"))
    sent = int(deal.get("reminders_sent") or 0)
    if start and sent < len(REMINDER_DAYS) and balance_paise(deal) > 0:
        when = (start + timedelta(days=REMINDER_DAYS[sent])).astimezone(IST)
        if when.hour < REMINDER_HOURS_IST[0]:
            when = when.replace(hour=REMINDER_HOURS_IST[0], minute=0)
        out.append({"kind": "reminder", "at": when.isoformat(), "note": "only if not paid"})
    return out


# ─────────────────────────────────────────────────────────────── WhatsApp to the customer

def compose(db, tenant_id: str, deal: dict, kind: str, *, pay_link: str | None = None) -> tuple[str, list[str]]:
    """(the message as the customer sees it, the 5 values for that kind's template)."""
    lead = {}
    if deal.get("lead_id"):
        res = db.table("leads").select("name").eq("id", deal["lead_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
        lead = (res.data if res else None) or {}
    first = _first_name(lead.get("name") or deal.get("customer_name"))
    shop = _shop_name(db, tenant_id)
    number = order_label(deal)
    due = balance_paise(deal)
    link = pay_link or deal.get("payment_link") or ""
    if kind in ("quote", "quote_reminder"):
        url = bill_url(deal.get("bill_token")) or ""
        items = (
            db.table("deal_items").select("name, qty").eq("deal_id", deal["id"]).eq("tenant_id", tenant_id).execute()
        ).data or []
        summary = ", ".join(f"{i['name']} x {i['qty']}" for i in items)[:300] or "your order"
        total = _rupees(int(deal["total_paise"]))
        if kind == "quote_reminder":
            text = f"Vanakkam {first}, a gentle reminder about quote {number} from {shop} ({total})."
        else:
            text = f"Quote {number} from {shop}\nVanakkam {first} 🙏\n" + "\n".join(
                f"• {i['name']} × {i['qty']}" for i in items[:12]) + f"\nTotal {total}"
            if deal.get("discount_paise"):
                text += f" (after {_rupees(int(deal['discount_paise']))} discount)"
        advance = int(deal.get("advance_paise") or 0)
        extra = []
        if advance:
            extra.append(f"Advance {_rupees(advance)} to confirm")
        if deal.get("ready_in_days"):
            extra.append(f"ready in {deal['ready_in_days']} days")
        if extra:
            text += "\n" + " · ".join(extra)
        if deal.get("quote_valid_until"):
            text += f"\nValid till {_day(deal['quote_valid_until'])}"
        if url:
            text += f"\nSee or download it: {url}"
        return text, [first, number, shop, summary, total]
    if kind == "confirmed":
        advance = min(int(deal.get("advance_paise") or 0), due)
        text = f"Nandri {first}! 🎉 Order {number} from {shop} is confirmed."
        if advance and link:
            text += f" Pay the {_rupees(advance)} advance here to start: {link}"
        elif advance:
            text += f" Advance to start: {_rupees(advance)}."
        update = f"it is confirmed{f', advance {_rupees(advance)}' if advance else ''}"
        return text, [first, number, shop, update, link or bill_url(deal.get("bill_token")) or number]
    if kind == "refund":
        refund = deal.get("_refund") or {}
        amount = _rupees(int(refund.get("amount_paise") or 0))
        if refund.get("method") == "razorpay":
            text = f"Vanakkam {first}, the refund of {amount} for order {number} from {shop} has started. It reaches your account in 5-7 working days."
            update = f"refund of {amount} started, 5-7 working days"
        else:
            how = METHOD_LABELS.get(refund.get("method"), "")
            text = f"Vanakkam {first}, {shop} has given back {amount} for order {number}{f' by {how}' if how else ''}."
            update = f"{amount} refunded{f' by {how}' if how else ''}"
        return text, [first, number, shop, update, bill_url(deal.get("bill_token")) or number]
    if kind == "bill":
        url = bill_url(deal.get("bill_token")) or ""
        bill_no = deal.get("invoice_number") or number
        text = f"Vanakkam {first} 🙏 Thank you for shopping at {shop}.\nYour bill {bill_no} for {_rupees(int(deal['total_paise']))}"
        if 0 < due < int(deal["total_paise"]):
            text += f" (paid {_rupees(int(deal.get('paid_paise') or 0))}, balance {_rupees(due)})"
        text += f": {url}" if url else "."
        return text, [first, shop, bill_no, _rupees(int(deal["total_paise"])), url or number]
    if kind == "ready":
        update = "it is ready for pickup" if deal.get("handover") != "courier" else "it is packed and ready to send"
        if due:
            update += f", balance {_rupees(due)}"
        text = f"Vanakkam {first} 🎉 Your order {number} from {shop} is ready" + (" for pickup." if deal.get("handover") != "courier" else ".")
        if due:
            text += f"\nBalance {_rupees(due)}" + (f". Pay here: {link}" if link else ". You can pay at the shop.")
        return text, [first, number, shop, update, link or bill_url(deal.get("bill_token")) or number]
    if kind == "shipped":
        courier = deal.get("courier") or "the courier"
        track = deal.get("tracking_id") or ""
        update = f"it is on the way with {courier}" + (f", tracking ID {track}" if track else "")
        text = f"Vanakkam {first} 🚚 Your order {number} from {shop} is on the way with {courier}."
        if track:
            text += f"\nTracking ID: {track}"
        return text, [first, number, shop, update, bill_url(deal.get("bill_token")) or number]
    if kind == "delivered":
        done = "delivered" if deal.get("handover") == "courier" else "picked up"
        review = order_settings(tenant_id).get("google_review_link") or ""
        text = f"Vanakkam {first} 🙏 Thank you for choosing {shop}! Your order {number} is {done}."
        if review:
            text += f"\nIf you liked it, a quick Google review helps us a lot: {review}"
        update = f"it is {done}, thank you" + (" - a Google review helps us a lot" if review else "")
        return text, [first, number, shop, update, review or bill_url(deal.get("bill_token")) or number]
    # reminder / pay_link
    text = (f"Vanakkam {first}, a gentle reminder from {shop}: {_rupees(due)} is still to pay for order {number}."
            if kind == "reminder" else f"Vanakkam {first}, here is the payment link for order {number} from {shop}: {_rupees(due)}.")
    if link:
        text += f"\nPay here: {link}"
    return text, [first, shop, _rupees(due), number, link or number]


def share_url(phone: str | None, text: str) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return None
    return f"https://wa.me/{digits}?text={quote(text)}"


def _approved_order_template(db, tenant_id: str, kind: str) -> dict | None:
    from app.services.call_details_share import _approved_templates
    wanted = ORDER_TEMPLATES[TEMPLATE_FOR_KIND[kind]]["name"]
    return next((t for t in _approved_templates(db, tenant_id) if t.get("name") == wanted), None)


def _approved_media_template(db, tenant_id: str, name: str) -> dict | None:
    """An approved template with a picture/document header (the text-only lookup skips those)."""
    from app.config_dynamic import get_setting
    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    if not waba_id:
        return None
    rows = (
        db.table("message_templates").select("*").eq("tenant_id", tenant_id).eq("name", name).execute()
    ).data or []
    return next((r for r in rows if (r.get("status") or "").upper() == "APPROVED" and r.get("meta_waba_id") == waba_id), None)


def public_api_base() -> str:
    from app.config import settings as env_settings
    return (env_settings.public_base_url or "https://aira-ai-5tfr.onrender.com").rstrip("/")


def bill_file_url(token: str, is_pdf: bool) -> str:
    return f"{public_api_base()}/api/v1/public/bills/{token}/{'invoice.pdf' if is_pdf else 'picture.png'}"


def bill_file(db, token: str) -> tuple[bytes, str, str] | None:
    """(bytes, content type, file name) of the bill as WhatsApp carries it: the tax invoice
    PDF for a GST bill, a receipt picture otherwise. None when the link is wrong."""
    from app.services import bill_files
    bill = public_bill(db, token)
    if not bill:
        return None
    if bill["bill_type"] == "gst":
        return bill_files.invoice_pdf(bill), "application/pdf", bill_files.pdf_filename(bill)
    return bill_files.bill_png(bill), "image/png", f"Bill {bill_files.bill_number(bill).replace('/', '-')}.png"


def _bill_amount_text(deal: dict) -> str:
    total, due = int(deal.get("total_paise") or 0), balance_paise(deal)
    text = _rupees(total)
    if 0 < due < total:
        text += f" (paid {_rupees(int(deal.get('paid_paise') or 0))}, balance {_rupees(due)})"
    return text


async def _send_bill_file(db, tenant_id: str, deal: dict, phone: str, caption: str, first: str,
                          window: bool) -> tuple[str, str, str, dict] | None:
    """The bill with the file on top: inside 24 hours as a picture/PDF with the caption,
    outside as the approved anril_bill_picture / anril_bill_pdf template. Returns
    (Meta message id, via, the text as the customer sees it, media fields for messages),
    or None so the caller falls back to the plain-text bill."""
    import asyncio
    from app.services.meta_cloud import send_media_message, send_template_message, upload_media_to_meta
    token = deal.get("bill_token")
    if not token:
        return None
    is_gst = (deal.get("bill_type") or "gst") == "gst"
    spec = ORDER_TEMPLATES["bill_pdf" if is_gst else "bill_picture"]
    template = None if window else _approved_media_template(db, tenant_id, spec["name"])
    if not window and not template:
        return None
    made = await asyncio.to_thread(bill_file, db, token)
    if not made:
        return None
    data, content_type, filename = made
    media_id = await upload_media_to_meta(data, content_type, filename, tenant_id=tenant_id)
    wa_type = "document" if is_gst else "image"
    media = {"media_type": wa_type, "media_url": bill_file_url(token, is_gst)}
    if window:
        resp = await send_media_message(phone, media_id=media_id, wa_type=wa_type, caption=caption[:1024],
                                        filename=filename if is_gst else None, tenant_id=tenant_id)
        sid = ((resp or {}).get("messages") or [{}])[0].get("id")
        return (sid, "text", caption, media) if sid else None
    values = [first, deal.get("invoice_number") or order_label(deal), _shop_name(db, tenant_id), _bill_amount_text(deal)]
    values = [_one_line(v) for v in values]
    header = {"id": media_id, **({"filename": filename} if is_gst else {})}
    components = [
        {"type": "header", "parameters": [{"type": wa_type, wa_type: header}]},
        {"type": "body", "parameters": [{"type": "text", "text": v} for v in values]},
        {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": token}]},
    ]
    resp = await send_template_message(phone, template["name"], template.get("language") or "en",
                                       components=components, tenant_id=tenant_id)
    sid = ((resp or {}).get("messages") or [{}])[0].get("id")
    body = spec["body"]
    for n, v in enumerate(values, start=1):
        body = body.replace(f"{{{{{n}}}}}", v)
    return (sid, "template", f"{body}\n{spec['footer']}", media) if sid else None


async def _send_order_template(db, tenant_id: str, phone: str, template: dict, values: list[str],
                               payloads: list[str] | None) -> tuple[str | None, str]:
    """An approved order template, with quick-reply payloads on its buttons (the quote's
    Accept / Ask). Returns (Meta message id, the text as the customer sees it)."""
    from fastapi import HTTPException
    from app.services.call_details_share import prepare_template
    from app.services.meta_cloud import send_template_message
    template, vals, content = prepare_template(db, tenant_id, template["id"], [_one_line(v) for v in values])
    components = [{"type": "body", "parameters": [{"type": "text", "text": v} for v in vals]}] if vals else []
    for index, payload in enumerate(payloads or []):
        components.append({"type": "button", "sub_type": "quick_reply", "index": str(index),
                           "parameters": [{"type": "payload", "payload": payload}]})
    try:
        resp = await send_template_message(phone, template["name"], template.get("language") or "en",
                                           components=components, tenant_id=tenant_id)
    except HTTPException as e:
        raise OrderError(f"WhatsApp didn't send it: {str(e.detail)[:200]}")
    return ((resp or {}).get("messages") or [{}])[0].get("id"), content


async def notify(db, tenant_id: str, deal_id: str, kind: str, *, user_id: str | None = None,
                 pay_link: str | None = None, sender: dict | None = None, buttons: list[dict] | None = None,
                 extra: dict | None = None) -> dict:
    """Send the customer one update about their order. Returns
    {"sent": bool, "via": "text"|"template"|None, "share_url": str|None, "text": str, "reason": str|None}.
    Never raises: the order change it follows has already happened."""
    deal = {**_load(db, tenant_id, deal_id), **(extra or {})}
    text, values = compose(db, tenant_id, deal, kind, pay_link=pay_link)
    result = {"sent": False, "via": None, "share_url": None, "text": text, "reason": None}
    lead = {}
    if deal.get("lead_id"):
        res = (
            db.table("leads").select("id, phone, opted_out, last_inbound_at")
            .eq("id", deal["lead_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
        )
        lead = (res.data if res else None) or {}
    phone = lead.get("phone")
    if not phone:
        result["reason"] = "no_phone"
        return result
    result["share_url"] = share_url(phone, text)
    if lead.get("opted_out"):
        result["reason"] = "opted_out"
        return result
    try:
        from app.config_dynamic import get_setting
        if not (get_setting("meta_phone_number_id", tenant_id=tenant_id) and get_setting("meta_access_token", tenant_id=tenant_id)):
            result["reason"] = "whatsapp_not_connected"
            return result
        from app.services.call_details_share import window_open
        sid, via, content, media = None, None, text, {}
        window = window_open(lead.get("last_inbound_at"), _now())
        if kind == "bill":
            try:
                sent = await _send_bill_file(db, tenant_id, deal, phone, text, values[0], window)
            except Exception as e:  # the plain-text bill below still goes
                logger.warning(f"Order {deal_id}: bill file didn't go, sending text: {e}")
                sent = None
            if sent:
                sid, via, content, media = sent
        if not sid and window:
            if buttons:
                from app.services.meta_cloud import send_interactive_buttons
                resp = await send_interactive_buttons(phone, text[:1024], buttons, tenant_id=tenant_id)
                sid = ((resp or {}).get("messages") or [{}])[0].get("id")
            else:
                from app.services.ai_reply import send_whatsapp
                sid = await send_whatsapp(phone, text, tenant_id=tenant_id)
            via = "text" if sid else None
        if not sid:
            template = _approved_order_template(db, tenant_id, kind)
            if template:
                sid, content = await _send_order_template(db, tenant_id, phone, template, values,
                                                           [b["id"] for b in buttons] if buttons else None)
                via = "template" if sid else None
        if not sid:
            result["reason"] = "outside_24h_no_template"
            return result
        msg = db.table("messages").insert({
            "lead_id": lead["id"], "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
            "content": content, "is_ai_generated": False, "meta_message_id": sid, **media, **(sender or {}),
        }).execute().data or []
        db.table("deal_messages").insert({
            "tenant_id": tenant_id, "deal_id": deal_id, "kind": kind, "sent_via": via, "body": content,
            "message_id": msg[0]["id"] if msg else None, "created_by": user_id,
        }).execute()
        result.update({"sent": True, "via": via, "text": content})
    except Exception as e:
        logger.warning(f"Order {deal_id}: {kind} WhatsApp failed: {e}")
        result["reason"] = "send_failed"
    return result


def log_shared(db, tenant_id: str, deal_id: str, kind: str, text: str, user_id: str | None) -> None:
    """Staff sent it from their own phone with Share on WhatsApp."""
    _load(db, tenant_id, deal_id)
    db.table("deal_messages").insert({
        "tenant_id": tenant_id, "deal_id": deal_id, "kind": kind, "sent_via": "share",
        "body": (text or "")[:2000], "created_by": user_id,
    }).execute()


async def _balance_link(db, tenant_id: str, deal: dict) -> str | None:
    """A Razorpay link for what is left, or None when Razorpay isn't set up."""
    if balance_paise(deal) <= 0:
        return None
    if deal.get("payment_link") and not deal.get("paid_paise"):
        return deal["payment_link"]
    try:
        link = await deals_service.send_payment_link(tenant_id, deal["id"], send_whatsapp_message=False, db=db)
        return link["payment_link"]
    except Exception as e:
        logger.info(f"Order {deal['id']}: no balance link ({e})")
        return None


# ─────────────────────────────────────────────────────────────── payments + delivery

async def take_payment(db, tenant_id: str, deal_id: str, amount_paise: int, method: str, *,
                       user_id: str | None = None, caller_id: str | None = None, note: str | None = None) -> dict:
    if method not in CARD_METHODS + ("bank_transfer", "other"):
        raise OrderError("Pick how they paid")
    try:
        out = deals_service.record_payment(tenant_id, deal_id, amount_paise, method, received_by=user_id,
                                           received_by_caller=caller_id, note=note, db=db)
    except DealError as e:
        raise OrderError(str(e))
    if out["status"] == "over":
        raise OrderError("That is more than what is left to pay")
    if out["status"] == "closed":
        raise OrderError("This order is cancelled")
    ensure_invoice(db, tenant_id, deal_id)
    if out.get("stale_link"):
        await deals_service.cancel_stale_link(out["stale_link"])
    return out


async def send_pay_link(db, tenant_id: str, deal_id: str, *, user_id: str | None = None, kind: str = "pay_link",
                        sender: dict | None = None) -> dict:
    deal = _load(db, tenant_id, deal_id)
    if deal["stage"] in ("won", "lost") or balance_paise(deal) <= 0:
        raise OrderError("Nothing is left to pay on this order")
    link = await _balance_link(db, tenant_id, deal)
    if not link:
        raise OrderError("Payment links need Razorpay. Connect it in Settings › Payments, or record the payment by hand.")
    if kind == "reminder":
        _mark_reminded(db, tenant_id, deal)
    sent = await notify(db, tenant_id, deal_id, kind, user_id=user_id, pay_link=link, sender=sender)
    return {**sent, "payment_link": link}


def _mark_reminded(db, tenant_id: str, deal: dict) -> None:
    db.table("deals").update({
        "reminders_sent": int(deal.get("reminders_sent") or 0) + 1, "last_reminder_at": _now().isoformat(),
        "reminders_from": deal.get("reminders_from") or _now().isoformat(),
    }).eq("id", deal["id"]).eq("tenant_id", tenant_id).execute()


DELIVERY_ACTIONS = ("working", "ready", "shipped", "delivered")


async def move_delivery(db, tenant_id: str, deal_id: str, action: str, *, handover: str | None = None,
                        courier: str | None = None, tracking_id: str | None = None, tell_customer: bool = True,
                        user_id: str | None = None, sender: dict | None = None) -> dict:
    if action not in DELIVERY_ACTIONS:
        raise OrderError("Unknown step")
    deal = _load(db, tenant_id, deal_id)
    if deal["stage"] == "lost":
        raise OrderError("This order is cancelled")
    if deal.get("handover") == "taken":
        raise OrderError("The customer already took this order")
    now = _now().isoformat()
    patch: dict = {"delivery_status": action}
    if handover in ("pickup", "courier"):
        patch["handover"] = handover
    elif not deal.get("handover"):
        patch["handover"] = "courier" if action == "shipped" else "pickup"
    if action == "ready":
        patch["ready_at"] = now
        if balance_paise(deal) > 0:
            patch.update({"reminders_from": now, "reminders_sent": 0})
    if action == "shipped":
        name = (courier or "").strip()[:60]
        if not name:
            raise OrderError("Add the courier's name")
        patch.update({"shipped_at": now, "courier": name, "tracking_id": (tracking_id or "").strip()[:80] or None,
                      "handover": "courier"})
    if action == "delivered":
        patch["delivered_at"] = now
    db.table("deals").update(patch).eq("id", deal_id).eq("tenant_id", tenant_id).execute()
    message = None
    if tell_customer and action in ("ready", "shipped", "delivered"):
        link = await _balance_link(db, tenant_id, {**deal, **patch}) if action == "ready" else None
        message = await notify(db, tenant_id, deal_id, action, user_id=user_id, pay_link=link, sender=sender)
    return {"message": message}


# ─────────────────────────────────────────────────────────────── New bill

def _find_or_make_customer(db, tenant_id: str, phone: str | None, name: str | None) -> str | None:
    if not (phone or "").strip():
        return None
    from app.services.inbound_lead import create_inbound_lead
    lead_id = create_inbound_lead(tenant_id, phone.strip(), "store", name=(name or "").strip() or None,
                                  opt_in_source="manual", db=db)
    if not lead_id:
        raise OrderError("That phone number doesn't look right")
    if (name or "").strip():
        db.table("leads").update({"name": name.strip()[:120]}).eq("id", lead_id).eq("tenant_id", tenant_id).is_("name", "null").execute()
    return lead_id


def _check_stock(db, tenant_id: str, lines: list[dict]) -> list[dict]:
    """Lines asking for more than is on the shelf (not blocking: the bill shows a warning)."""
    short = []
    variant_ids = [li["variant_id"] for li in lines if li.get("variant_id")]
    item_ids = [li["catalog_item_id"] for li in lines if li.get("catalog_item_id") and not li.get("variant_id")]
    stock: dict[str, int | None] = {}
    if variant_ids:
        for r in db.table("catalog_item_variants").select("id, stock_quantity").eq("tenant_id", tenant_id).in_("id", variant_ids).execute().data or []:
            stock[r["id"]] = r.get("stock_quantity")
    if item_ids:
        for r in db.table("catalog_items").select("id, stock_quantity").eq("tenant_id", tenant_id).in_("id", item_ids).execute().data or []:
            stock[r["id"]] = r.get("stock_quantity")
    for li in lines:
        key = li.get("variant_id") or li.get("catalog_item_id")
        have = stock.get(key) if key else None
        if have is not None and int(li["qty"]) > int(have):
            short.append({"name": li["name"] + (f" ({li['variant_label']})" if li.get("variant_label") else ""), "available": have})
    return short


async def create_bill(db, tenant_id: str, data: dict, *, user_id: str | None = None, sender: dict | None = None) -> dict:
    """The shop counter. data:
       mode "now" (customer takes it) | "later" (pickup or courier, maybe an advance)
       phone, name                   -- optional; no phone = walk-in, nothing is sent
       items [{catalog_item_id, variant_id?, qty, unit_price_paise?, name?}]
       discount_paise, bill_type "gst"|"simple", gstin, business (B2B)
       sold_by (caller id) | sold_by_ai
       method "cash"|"upi"|"card"|"link", advance_paise (later only), handover, ready_by, notes"""
    from app.services.business_details import prices_include_gst
    mode = data.get("mode")
    if mode not in ("now", "later"):
        raise OrderError("Pick Taking it now or Deliver later")
    method = data.get("method")
    if method not in CARD_METHODS + ("link",):
        raise OrderError("Pick how they pay")
    bill_type = data.get("bill_type") or "gst"
    if bill_type not in ("gst", "simple"):
        raise OrderError("Pick GST bill or Simple bill")
    gstin = (data.get("gstin") or "").strip().upper() or None
    if gstin and not re.match(r"^[0-9]{2}[A-Z0-9]{13}$", gstin):
        raise OrderError("That GSTIN doesn't look right (15 letters and numbers)")
    if data.get("sold_by"):
        caller = db.table("callers").select("id").eq("id", data["sold_by"]).eq("tenant_id", tenant_id).limit(1).execute().data
        if not caller:
            raise OrderError("That teammate isn't on your team")
    lead_id = _find_or_make_customer(db, tenant_id, data.get("phone"), data.get("name"))
    if method == "link" and not lead_id:
        raise OrderError("A payment link needs the customer's phone number")
    try:
        lines = deals_service._resolve_lines(tenant_id, data.get("items") or [], db)
    except DealError as e:
        raise OrderError(str(e))
    bill = compute_bill(lines, discount_paise=int(data.get("discount_paise") or 0),
                        include_gst=prices_include_gst(tenant_id, db), bill_type=bill_type)
    total = bill["total_paise"]
    if total <= 0:
        raise OrderError("The bill total must be more than zero")
    advance = int(data.get("advance_paise") or 0) if mode == "later" else total
    if advance < 0 or advance > total:
        raise OrderError("The advance can't be more than the total")
    advance_note = None
    if mode == "later":
        from app.services.order_quotes import advance_for, advance_rule, rule_text
        rule = advance_rule(tenant_id)
        asked = advance_for(total, rule)
        if rule["kind"] != "none" and advance != asked:
            advance_note = (f"Advance rule {rule_text(rule)} ({_rupees(asked)}). "
                            f"Staff changed it to {_rupees(advance)} for this order.")
    ready_by = None
    if data.get("ready_by"):
        try:
            ready_by = date.fromisoformat(str(data["ready_by"])).isoformat()
        except ValueError:
            raise OrderError("Pick a ready date")
    handover = "taken" if mode == "now" else (data.get("handover") if data.get("handover") in ("pickup", "courier") else "pickup")
    now = _now().isoformat()
    row = {
        "tenant_id": tenant_id, "lead_id": lead_id, "deal_number": deals_service._next_deal_number(db, tenant_id),
        "stage": "quoted", "source": "walk_in", "channel": "store", "handover": handover,
        "delivery_status": "delivered" if mode == "now" else "working",
        "delivered_at": now if mode == "now" else None,
        "total_paise": total, "discount_paise": bill["discount_paise"], "gst_paise": bill["gst_paise"],
        "bill_type": bill_type, "buyer_gstin": gstin, "buyer_business": (data.get("business") or "").strip()[:120] or None,
        "customer_name": (data.get("name") or "").strip()[:120] or None,
        "sold_by": data.get("sold_by") or None, "sold_by_ai": bool(data.get("sold_by_ai")) and not data.get("sold_by"),
        "created_by": user_id, "ready_by": ready_by, "notes": (data.get("notes") or "").strip()[:2000] or None,
        "bill_token": secrets.token_urlsafe(16), "advance_note": advance_note,
    }
    deal = db.table("deals").insert(row).execute().data[0]
    if advance_note:
        _audit(db, tenant_id, user_id, "order.advance_changed", deal["id"], {"note": advance_note})
    deals_service._insert_items(tenant_id, deal["id"], lines, db)
    stock_short = _check_stock(db, tenant_id, lines) if mode == "now" else []

    outcome, link, warnings = None, None, []
    caller_id = data.get("sold_by") or None
    if method == "link":
        # No advance typed on a later order: the link is for the whole bill.
        try:
            made = await deals_service.send_payment_link(tenant_id, deal["id"], send_whatsapp_message=False,
                                                         amount_paise=advance or total, db=db)
            link = made["payment_link"]
        except Exception as e:
            logger.warning(f"Bill {deal['id']}: payment link failed: {e}")
            raise OrderError("Couldn't make a payment link. Check Razorpay in Settings, or pick Cash / UPI / Card.")
    elif advance > 0:
        outcome = await take_payment(db, tenant_id, deal["id"], advance, method, user_id=user_id, caller_id=caller_id)
        warnings = outcome.get("stock_warnings") or []
    else:
        db.table("deals").update({"stage": "awaiting_payment"}).eq("id", deal["id"]).eq("tenant_id", tenant_id).execute()

    message = None
    if lead_id:
        kind = "pay_link" if method == "link" else "bill"
        message = await notify(db, tenant_id, deal["id"], kind, user_id=user_id, pay_link=link, sender=sender)
    return {"order": order_detail(db, tenant_id, deal["id"]), "message": message, "payment_link": link,
            "stock_short": stock_short, "stock_warnings": warnings}


def _audit(db, tenant_id: str, user_id: str | None, action: str, target_id: str, metadata: dict) -> None:
    """Activity log row; never stops the order change it follows."""
    try:
        from app.services.audit_log import record_audit_event
        record_audit_event(db, tenant_id=tenant_id, actor_user_id=user_id, actor_role=None, action=action,
                           target_type="order", target_id=target_id, metadata=metadata)
    except Exception as e:
        logger.warning(f"Audit {action} for {target_id} failed: {e}")


# ─────────────────────────────────────────────────────────────── payment reminders (scheduler)

async def send_due_reminders(db=None, now: datetime | None = None, limit: int = 200) -> int:
    """Day 1, 3 and 7 after a payment link or Mark ready, between 10 AM and 7 PM IST, while
    something is left to pay. Each reminder makes a fresh link for what is left."""
    db = db or get_supabase()
    now = now or _now()
    hour = now.astimezone(IST).hour
    if not (REMINDER_HOURS_IST[0] <= hour < REMINDER_HOURS_IST[1]):
        return 0
    try:
        from app.services.order_quotes import sweep_quotes
        await sweep_quotes(db, now)
    except Exception as e:
        logger.warning(f"Quote reminders/expiry failed: {e}")
    try:
        from app.services.purchases import sweep_unanswered
        sweep_unanswered(db, now)  # purchase orders a supplier hasn't answered in 2 days
    except Exception as e:
        logger.warning(f"Purchase order reminders failed: {e}")
    rows = (
        db.table("deals").select("*").eq("stage", "awaiting_payment").not_.is_("reminders_from", "null")
        .lt("reminders_sent", len(REMINDER_DAYS)).not_.is_("lead_id", "null").limit(limit).execute()
    ).data or []
    sent = 0
    for deal in rows:
        start = _parse(deal.get("reminders_from"))
        step = int(deal.get("reminders_sent") or 0)
        if not start or step >= len(REMINDER_DAYS) or balance_paise(deal) <= 0:
            continue
        if now < start + timedelta(days=REMINDER_DAYS[step]):
            continue
        # Counted even if WhatsApp refuses it, so a closed window can't make it retry every hour.
        _mark_reminded(db, deal["tenant_id"], deal)
        try:
            link = await _balance_link(db, deal["tenant_id"], deal)
            out = await notify(db, deal["tenant_id"], deal["id"], "reminder", pay_link=link)
            sent += 1 if out.get("sent") else 0
        except Exception as e:
            logger.warning(f"Reminder for order {deal['id']} failed: {e}")
    return sent


# ─────────────────────────────────────────────────────────────── New bill: what to show

def bill_options(db, tenant_id: str) -> dict:
    """Items with their sizes/colours and what is free to sell (stock minus unpaid holds),
    the team for Handled by, and the GST setup."""
    from app.services.business_details import get_business_details
    items = (
        db.table("catalog_items").select("id, name, item_type, price_paise, gst_rate, stock_quantity, attributes, status")
        .eq("tenant_id", tenant_id).eq("status", "ready").order("name").limit(1000).execute()
    ).data or []
    variants = (
        db.table("catalog_item_variants").select("id, catalog_item_id, size, colour, stock_quantity, price_paise, sort_order")
        .eq("tenant_id", tenant_id).order("sort_order").limit(5000).execute()
    ).data or []
    by_item: dict[str, list[dict]] = {}
    for v in variants:
        by_item.setdefault(v["catalog_item_id"], []).append(v)
    team = (
        db.table("callers").select("id, name, active").eq("tenant_id", tenant_id).order("name").execute()
    ).data or []
    details = get_business_details(tenant_id, db) or {}
    out_items = []
    for it in items:
        attrs = it.get("attributes") if isinstance(it.get("attributes"), dict) else {}
        out_items.append({
            "id": it["id"], "name": it["name"], "kind": it.get("item_type") or "product",
            "group": (attrs.get("category") or attrs.get("group") or "").strip() or None,
            "price_paise": it.get("price_paise"), "gst_rate": it.get("gst_rate"),
            "stock": it.get("stock_quantity"),
            "variants": [
                {"id": v["id"], "size": v.get("size"), "colour": v.get("colour"), "stock": v["stock_quantity"],
                 "price_paise": v.get("price_paise"), "label": deals_service.variant_label(v)}
                for v in by_item.get(it["id"], [])
            ],
        })
    return {
        "items": out_items,
        "team": [{"id": c["id"], "name": c["name"]} for c in team if c.get("active") is not False],
        "prices_include_gst": bool(details.get("prices_include_gst", True)),
        "gstin_set": bool((details.get("gstin") or "").strip()),
    }


def add_waitlist(db, tenant_id: str, *, item_id: str, variant_id: str | None, phone: str | None,
                 name: str | None, user_id: str | None) -> dict:
    from app.services import stock_asks

    item = db.table("catalog_items").select("id").eq("id", item_id).eq("tenant_id", tenant_id).limit(1).execute().data
    if not item:
        raise OrderError("Product not found")
    if variant_id:
        v = db.table("catalog_item_variants").select("id").eq("id", variant_id).eq("catalog_item_id", item_id).eq("tenant_id", tenant_id).limit(1).execute().data
        if not v:
            raise OrderError("That size or colour isn't on this product")
    lead_id = _find_or_make_customer(db, tenant_id, phone, name)
    if not lead_id:
        raise OrderError("Add their phone number so they can be told")
    # One open request per customer per item / size (migration 305): asking again updates it.
    try:
        return stock_asks.record_ask(db, tenant_id, lead_id=lead_id, item_id=item_id, variant_id=variant_id,
                                     wants_message=True, source="staff", name=name, user_id=user_id)
    except stock_asks.StockAskError as exc:
        raise OrderError(str(exc))


# ─────────────────────────────────────────────────────────────── customer's bill page

def public_bill(db, token: str) -> dict | None:
    """The customer's bill from its secret link. Only what is printed on the bill."""
    if not token or not re.match(r"^[A-Za-z0-9_-]{16,64}$", token):
        return None
    rows = db.table("deals").select("*").eq("bill_token", token).limit(1).execute().data or []
    if not rows:
        return None
    deal = rows[0]
    tenant_id = deal["tenant_id"]
    from app.services.business_details import get_business_details
    business = get_business_details(tenant_id, db) or {}
    items = (
        db.table("deal_items").select("name, variant_label, qty, unit_price_paise, gst_rate")
        .eq("deal_id", deal["id"]).eq("tenant_id", tenant_id).order("created_at").execute()
    ).data or []
    lead = {}
    if deal.get("lead_id"):
        res = db.table("leads").select("name, phone").eq("id", deal["lead_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
        lead = (res.data if res else None) or {}
    bill = compute_bill(
        [{"unit_price_paise": i["unit_price_paise"], "qty": i["qty"], "gst_rate": i.get("gst_rate"), "name": i["name"],
          "variant_label": i.get("variant_label")} for i in items],
        discount_paise=int(deal.get("discount_paise") or 0), include_gst=bool(business.get("prices_include_gst", True)),
        bill_type=deal.get("bill_type") or "gst",
    )
    gst = int(deal.get("gst_paise") or bill["gst_paise"])
    paid_by = (
        db.table("deal_payments").select("method").eq("deal_id", deal["id"]).eq("tenant_id", tenant_id).execute()
    ).data or []
    methods = list(dict.fromkeys(METHOD_LABELS.get(p.get("method"), "") for p in paid_by if p.get("method")))
    return {
        "methods": [m for m in methods if m],
        "business": {k: business.get(k) or "" for k in ("legal_name", "address", "city", "state", "pincode", "gstin", "phone", "email")},
        "bill_type": deal.get("bill_type") or "gst",
        "invoice_number": deal.get("invoice_number"),
        "invoice_date": deal.get("invoice_issued_at") or deal.get("created_at"),
        "order_label": order_label(deal),
        "customer": {"name": lead.get("name") or deal.get("customer_name"), "phone": _mask(lead.get("phone")),
                     "business": deal.get("buyer_business"), "gstin": deal.get("buyer_gstin")},
        "lines": [
            {"name": li["name"], "variant": li.get("variant_label"), "qty": li["qty"], "unit_price_paise": li["unit_price_paise"],
             "gst_rate": li.get("gst_rate") if (deal.get("bill_type") or "gst") == "gst" else None,
             "amount_paise": li["unit_price_paise"] * li["qty"]}
            for li in bill["lines"]
        ],
        "subtotal_paise": bill["subtotal_paise"],
        "discount_paise": int(deal.get("discount_paise") or 0),
        "gst_paise": gst,
        **gst_split(business.get("gstin"), deal.get("buyer_gstin"), gst),
        "prices_include_gst": bool(business.get("prices_include_gst", True)),
        "total_paise": int(deal.get("total_paise") or 0),
        "paid_paise": int(deal.get("paid_paise") or 0),
        "balance_paise": balance_paise(deal) if deal.get("stage") != "lost" else 0,
        "cancelled": deal.get("stage") == "lost",
        "refunded_paise": int(deal.get("refunded_paise") or 0),
        "pay_link": deal.get("payment_link") if deal.get("stage") == "awaiting_payment" else None,
        "quote": _public_quote(deal),
    }


def _public_quote(deal: dict) -> dict | None:
    """Quote details while it is open, so the page can show Accept."""
    if deal.get("stage") != "quoted" or not deal.get("quote_sent_at"):
        return None
    valid = deal.get("quote_valid_until")
    expired = bool(valid and str(valid)[:10] < _now().astimezone(IST).date().isoformat())
    return {"valid_until": valid, "expired": expired, "advance_paise": int(deal.get("advance_paise") or 0),
            "ready_in_days": deal.get("ready_in_days")}


def _mask(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 6:
        return None
    return f"{digits[-10:-8]}•• ••{digits[-3:]}"
