"""Orders & payments > New quote: a price offer the customer accepts with one tap.

Accept comes three ways, all landing in accept_quote: the WhatsApp reply button (inside the
24-hour window), the quick-reply button on the approved anril_order_quote template, and the
Accept button on the quote's own page (/bill/<token>, which also works for a quote sent with
"Share on WhatsApp"). Accepting makes it an order (awaiting_payment), sends the advance link,
and rings the owners' bell. No reply in 2 days: one reminder. Past its valid date: lost,
"Quote expired". The shop's advance rule (none / percent / fixed, optionally only above an
amount) fills the advance; staff can change it on one quote.
"""
import json
import logging
import secrets
from datetime import date, datetime, timedelta

from app.services import deals as deals_service
from app.services import orders
from app.services.deals import DealError
from app.services.orders import IST, OrderError, _now, _rupees

logger = logging.getLogger(__name__)

ADVANCE_RULE_KEY = "orders_advance_rule"
DEFAULT_RULE = {"kind": "none", "value": 0, "min_total_paise": 0}
REMIND_AFTER = timedelta(days=2)


# ── the shop's advance rule ───────────────────────────────────────────────────

def advance_rule(tenant_id: str) -> dict:
    from app.config_dynamic import get_setting
    raw = get_setting(ADVANCE_RULE_KEY, fallback=None, tenant_id=tenant_id)
    try:
        saved = json.loads(raw) if raw else {}
    except ValueError:
        saved = {}
    rule = {**DEFAULT_RULE, **{k: v for k, v in (saved or {}).items() if k in DEFAULT_RULE}}
    if rule["kind"] not in ("none", "percent", "fixed"):
        rule["kind"] = "none"
    return rule


def save_advance_rule(db, tenant_id: str, rule: dict) -> dict:
    from app.config_dynamic import invalidate_cache
    kind = rule.get("kind")
    if kind not in ("none", "percent", "fixed"):
        raise OrderError("Pick no advance, a percent or a fixed amount")
    value = float(rule.get("value") or 0)
    if kind == "percent" and not (0 < value <= 100):
        raise OrderError("The percent must be between 1 and 100")
    if kind == "fixed" and value <= 0:
        raise OrderError("Type the advance amount")
    clean = {"kind": kind, "value": value if kind != "none" else 0,
             "min_total_paise": max(int(rule.get("min_total_paise") or 0), 0)}
    db.table("app_settings").upsert({
        "tenant_id": tenant_id, "key": ADVANCE_RULE_KEY, "value": json.dumps(clean), "is_secret": False,
        "updated_at": "now()",
    }, on_conflict="tenant_id,key").execute()
    invalidate_cache(ADVANCE_RULE_KEY)
    return clean


def clean_item_rule(raw) -> dict | None:
    """An item's own advance rule (migration 315); None = the shop's rule."""
    if not isinstance(raw, dict) or raw.get("kind") not in ("none", "percent", "fixed"):
        return None
    if raw["kind"] == "none":
        return {"kind": "none", "value": 0}
    try:
        value = float(raw.get("value") or 0)
    except (TypeError, ValueError):
        raise OrderError("Type the advance as a number")
    if raw["kind"] == "percent" and not 0 < value <= 100:
        raise OrderError("The advance percent must be between 1 and 100")
    if raw["kind"] == "fixed" and not 0 < value <= 10_000_000:
        raise OrderError("Type the advance amount")
    return {"kind": raw["kind"], "value": value}


def order_advance(db, tenant_id: str, lines: list[dict], total_paise: int) -> int:
    """The advance for an order: lines of items with their own rule use it (a fixed amount is per
    piece, a percent is of that line's share of the total); the rest use the shop's rule on their
    share. Never more than the total. Every item on the shop rule = the shop rule on the total."""
    shop = advance_rule(tenant_id)
    ids = list({li["catalog_item_id"] for li in lines if li.get("catalog_item_id")})
    own: dict[str, dict] = {}
    if ids:
        for r in (db.table("catalog_items").select("id, advance_rule").eq("tenant_id", tenant_id).in_("id", ids)
                  .execute().data or []):
            rule = clean_item_rule(r.get("advance_rule")) if isinstance(r.get("advance_rule"), dict) else None
            if rule:
                own[r["id"]] = rule
    if not own:
        return advance_for(total_paise, shop)
    subtotal = sum(int(li.get("line_total_paise") or 0) for li in lines) or 1
    share = lambda li: round(total_paise * int(li.get("line_total_paise") or 0) / subtotal)  # noqa: E731
    shop_part = sum(share(li) for li in lines if li.get("catalog_item_id") not in own)
    advance = advance_for(shop_part, shop) if shop_part else 0
    for li in lines:
        rule = own.get(li.get("catalog_item_id") or "")
        if not rule or rule["kind"] == "none":
            continue
        part = share(li)
        ask = round(part * rule["value"] / 100) if rule["kind"] == "percent" else round(rule["value"] * 100) * int(li.get("qty") or 1)
        advance += max(0, min(ask, part))
    return max(0, min(advance, total_paise))


def rule_text(rule: dict) -> str:
    """"30%" / "₹1,000" / "30% above ₹5,000"."""
    if rule.get("kind") == "percent":
        base = f"{float(rule['value']):g}%"
    elif rule.get("kind") == "fixed":
        base = _rupees(round(float(rule["value"]) * 100))
    else:
        return "none"
    return base + (f" above {_rupees(int(rule['min_total_paise']))}" if int(rule.get("min_total_paise") or 0) else "")


def advance_for(total_paise: int, rule: dict) -> int:
    """The advance a rule asks for on this total (never more than the total)."""
    if rule.get("kind") == "none" or total_paise <= 0:
        return 0
    if int(rule.get("min_total_paise") or 0) and total_paise < int(rule["min_total_paise"]):
        return 0
    if rule["kind"] == "percent":
        amount = round(total_paise * float(rule["value"]) / 100)
    else:
        amount = round(float(rule["value"]) * 100)
    return max(0, min(amount, total_paise))


# ── make and send ─────────────────────────────────────────────────────────────

def _lead_for(db, tenant_id: str, data: dict) -> str:
    if data.get("lead_id"):
        rows = db.table("leads").select("id").eq("id", data["lead_id"]).eq("tenant_id", tenant_id).limit(1).execute().data
        if not rows:
            raise OrderError("Customer not found")
        return data["lead_id"]
    phone = (data.get("phone") or "").strip()
    if not phone:
        raise OrderError("Add the customer's phone number")
    from app.services.inbound_lead import create_inbound_lead
    lead_id = create_inbound_lead(tenant_id, phone, "manual", name=(data.get("name") or "").strip() or None,
                                  opt_in_source="manual", db=db)
    if not lead_id:
        raise OrderError("That phone number doesn't look right")
    if (data.get("name") or "").strip():
        db.table("leads").update({"name": data["name"].strip()[:120]}).eq("id", lead_id).eq("tenant_id", tenant_id).is_("name", "null").execute()
    return lead_id


def _lines(db, tenant_id: str, items: list[dict]) -> list[dict]:
    """Catalogue lines (price from the catalogue unless typed) or typed lines (name + price)."""
    clean = []
    for it in items or []:
        qty = int(it.get("qty") or 1)
        line = {"qty": qty}
        if it.get("catalog_item_id"):
            line["catalog_item_id"] = it["catalog_item_id"]
            if it.get("variant_id"):
                line["variant_id"] = it["variant_id"]
        else:
            line["name"] = (it.get("name") or "").strip()[:200]
        if it.get("unit_price_paise") is not None:
            line["unit_price_paise"] = int(it["unit_price_paise"])
        clean.append(line)
    try:
        return deals_service._resolve_lines(tenant_id, clean, db)
    except DealError as e:
        raise OrderError(str(e))


async def create_quote(db, tenant_id: str, data: dict, *, user_id: str | None = None, send: bool = True,
                       sender: dict | None = None) -> dict:
    """data: lead_id or phone (+ name), items, discount_paise, valid_until (YYYY-MM-DD),
    advance: {"kind": "rule"|"none"|"percent"|"fixed", "value"}, ready_in_days, notes, sold_by."""
    from app.services.business_details import charges_gst, prices_include_gst
    lead_id = _lead_for(db, tenant_id, data)
    bill_type = "gst" if charges_gst(tenant_id, db) else "simple"
    lines = _lines(db, tenant_id, data.get("items") or [])
    bill = orders.compute_bill(lines, discount_paise=int(data.get("discount_paise") or 0),
                               include_gst=prices_include_gst(tenant_id, db), bill_type=bill_type)
    total = bill["total_paise"]
    if total <= 0:
        raise OrderError("The quote total must be more than zero")
    today = _now().astimezone(IST).date()
    try:
        valid = date.fromisoformat(str(data.get("valid_until"))) if data.get("valid_until") else today + timedelta(days=7)
    except ValueError:
        raise OrderError("Pick the date the quote is valid till")
    if valid < today:
        raise OrderError("The valid-till date is already over")
    asked = data.get("advance") or {"kind": "rule"}
    shop_rule = advance_rule(tenant_id)
    rule = shop_rule if asked.get("kind") == "rule" else asked
    if rule.get("kind") not in ("none", "percent", "fixed"):
        raise OrderError("Pick how much advance to ask for")
    # "The rule" = each item's own rule, else the shop's (migration 315)
    shop_advance = order_advance(db, tenant_id, lines, total)
    advance = shop_advance if asked.get("kind") == "rule" else advance_for(total, rule)
    advance_note = None
    if asked.get("kind") != "rule" and shop_rule["kind"] != "none" and advance != shop_advance:
        advance_note = (f"Advance rule {rule_text(shop_rule)} ({_rupees(shop_advance)}). "
                        f"Staff changed it to {_rupees(advance)} for this order.")
    ready = data.get("ready_in_days")
    if ready is not None and not (0 <= int(ready) <= 365):
        raise OrderError("Ready in must be 0 to 365 days")
    if data.get("sold_by"):
        ok = db.table("callers").select("id").eq("id", data["sold_by"]).eq("tenant_id", tenant_id).limit(1).execute().data
        if not ok:
            raise OrderError("That teammate isn't on your team")
    deal = db.table("deals").insert({
        "tenant_id": tenant_id, "lead_id": lead_id, "deal_number": deals_service._next_deal_number(db, tenant_id),
        "stage": "quoted", "source": "manual", "channel": "online", "total_paise": total,
        "discount_paise": bill["discount_paise"], "gst_paise": bill["gst_paise"], "bill_type": bill_type,
        "quote_valid_until": valid.isoformat(), "advance_paise": advance,
        "ready_in_days": int(ready) if ready is not None else None,
        "notes": (data.get("notes") or "").strip()[:2000] or None, "created_by": user_id,
        "sold_by": data.get("sold_by") or None, "bill_token": secrets.token_urlsafe(16),
        "advance_note": advance_note,
    }).execute().data[0]
    if advance_note:
        orders.log_advance_change(db, tenant_id, user_id, deal["id"], advance_note,
                                  from_paise=shop_advance, to_paise=advance)
    deals_service._insert_items(tenant_id, deal["id"], lines, db)
    message = await send_quote(db, tenant_id, deal["id"], user_id=user_id, sender=sender) if send else None
    return {"order": orders.order_detail(db, tenant_id, deal["id"]), "message": message}


def _buttons(deal_id: str) -> list[dict]:
    return [{"id": f"{orders.QUOTE_ACCEPT}{deal_id}", "title": "Accept quote"},
            {"id": f"{orders.QUOTE_ASK}{deal_id}", "title": "Ask a question"}]


async def send_quote(db, tenant_id: str, deal_id: str, *, user_id: str | None = None, kind: str = "quote",
                     sender: dict | None = None) -> dict:
    deal = orders._load(db, tenant_id, deal_id)
    if deal["stage"] != "quoted":
        raise OrderError("This quote is already accepted or closed")
    patch = {"quote_sent_at": _now().isoformat()} if kind == "quote" else {"quote_reminded_at": _now().isoformat()}
    db.table("deals").update(patch).eq("id", deal_id).eq("tenant_id", tenant_id).execute()
    return await orders.notify(db, tenant_id, deal_id, kind, user_id=user_id, buttons=_buttons(deal_id), sender=sender)


# ── accept ────────────────────────────────────────────────────────────────────

def _expired(deal: dict) -> bool:
    valid = deal.get("quote_valid_until")
    return bool(valid and str(valid)[:10] < _now().astimezone(IST).date().isoformat())


def _ring_owners(db, tenant_id: str, deal: dict, title: str, message: str) -> None:
    try:
        from app.services.notify import notify_user
        owners = db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner").execute().data or []
        for o in owners:
            notify_user(tenant_id, o["user_id"], "quote_accepted", title, message, db=db,
                        push_url=f"/dashboard/deals/orders/{deal['id']}")
    except Exception as e:
        logger.warning(f"Quote {deal.get('id')}: owner bell failed: {e}")


async def accept_quote(db, tenant_id: str, deal_id: str, *, via: str) -> dict:
    """The customer accepted. Returns {"status": "accepted"|"already"|"expired"|"closed",
    "payment_link": str|None, "advance_paise": int}. Never sends twice: the claim is the
    stage moving from quoted, so a double tap is "already"."""
    deal = orders._load(db, tenant_id, deal_id)
    if deal["stage"] != "quoted":
        return {"status": "already" if deal.get("accepted_at") else "closed",
                "payment_link": deal.get("payment_link"), "advance_paise": int(deal.get("advance_paise") or 0)}
    if _expired(deal):
        return {"status": "expired", "payment_link": None, "advance_paise": 0}
    today = _now().astimezone(IST).date()
    ready_by = (today + timedelta(days=int(deal["ready_in_days"]))).isoformat() if deal.get("ready_in_days") is not None else None
    claimed = (
        db.table("deals").update({"stage": "awaiting_payment", "accepted_at": _now().isoformat(), "ready_by": ready_by,
                                  "delivery_status": "working"})
        .eq("id", deal_id).eq("tenant_id", tenant_id).eq("stage", "quoted").execute()
    ).data
    if not claimed:
        return {"status": "already", "payment_link": deal.get("payment_link"), "advance_paise": int(deal.get("advance_paise") or 0)}
    advance = int(deal.get("advance_paise") or 0)
    link = None
    if advance > 0:
        try:
            link = (await deals_service.send_payment_link(tenant_id, deal_id, send_whatsapp_message=False,
                                                          amount_paise=advance, db=db))["payment_link"]
        except Exception as e:
            logger.info(f"Quote {deal_id}: no advance link ({e})")
    msg = await orders.notify(db, tenant_id, deal_id, "confirmed", pay_link=link)
    lead = {}
    if deal.get("lead_id"):
        rows = db.table("leads").select("name, phone").eq("id", deal["lead_id"]).eq("tenant_id", tenant_id).limit(1).execute().data
        lead = rows[0] if rows else {}
    who = lead.get("name") or lead.get("phone") or "A customer"
    _ring_owners(db, tenant_id, deal, f"{who} accepted quote {orders.order_label(deal)}",
                 f"{_rupees(int(deal['total_paise']))}" + (f", advance {_rupees(advance)} link sent." if link else "."))
    return {"status": "accepted", "payment_link": link, "advance_paise": advance, "message": msg, "via": via}


async def accept_from_chat(db, tenant_id: str, lead_id: str, deal_id: str) -> dict:
    """The WhatsApp button: only this customer's own quote."""
    rows = (
        db.table("deals").select("id, lead_id").eq("id", deal_id).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not rows or rows[0].get("lead_id") != lead_id:
        return {"status": "closed"}
    out = await accept_quote(db, tenant_id, deal_id, via="whatsapp")
    if out["status"] in ("expired", "closed"):
        await _say(db, tenant_id, lead_id, "This quote has expired. We'll send you a fresh one shortly 🙏"
                   if out["status"] == "expired" else "This quote is no longer open. We'll get back to you shortly 🙏")
    elif out["status"] == "already":
        await _say(db, tenant_id, lead_id, "Your order is already confirmed 👍"
                   + (f" Pay here if you haven't yet: {out['payment_link']}" if out.get("payment_link") else ""))
    return out


async def _say(db, tenant_id: str, lead_id: str, text: str) -> None:
    try:
        rows = db.table("leads").select("phone").eq("id", lead_id).eq("tenant_id", tenant_id).limit(1).execute().data
        if not rows or not rows[0].get("phone"):
            return
        from app.services.ai_reply import send_whatsapp
        sid = await send_whatsapp(rows[0]["phone"], text, tenant_id=tenant_id)
        db.table("messages").insert({"lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound",
                                     "channel": "whatsapp", "content": text, "is_ai_generated": False,
                                     "meta_message_id": sid}).execute()
    except Exception as e:
        logger.warning(f"Quote reply to lead {lead_id} failed: {e}")


def deal_from_button(interactive_id: str) -> str | None:
    """'quote_accept:<deal id>' -> the deal id; anything else -> None."""
    if interactive_id and interactive_id.startswith(orders.QUOTE_ACCEPT):
        value = interactive_id[len(orders.QUOTE_ACCEPT):].strip()
        return value if len(value) == 36 else None
    return None


# ── reminders and expiry (from the hourly order-payment-reminders task) ───────

async def sweep_quotes(db, now: datetime | None = None, limit: int = 200) -> dict:
    now = now or _now()
    today = now.astimezone(IST).date().isoformat()
    open_quotes = (
        db.table("deals").select("*").eq("stage", "quoted").not_.is_("quote_sent_at", "null").limit(limit).execute()
    ).data or []
    reminded = expired = 0
    for deal in open_quotes:
        valid = str(deal.get("quote_valid_until") or "")[:10]
        if valid and valid < today:
            if deals_service.mark_lost(deal["tenant_id"], deal["id"], "Quote expired", only_from=("quoted",), db=db):
                expired += 1
            continue
        sent = orders._parse(deal.get("quote_sent_at"))
        if sent and not deal.get("quote_reminded_at") and now - sent >= REMIND_AFTER:
            try:
                await send_quote(db, deal["tenant_id"], deal["id"], kind="quote_reminder")
                reminded += 1
            except Exception as e:
                logger.warning(f"Quote reminder {deal['id']} failed: {e}")
    return {"reminded": reminded, "expired": expired}


