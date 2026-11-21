"""Asked but out of stock (plan: docs/plans/commerce-stock-plan.md, part 1; migration 305).

Every customer who asked for an out-of-stock item or size is one OPEN stock_waitlist row: the AI
adds them in chat (tool note_out_of_stock_request), staff add them from Orders. "Mark back in
stock" messages the ones who said yes -- a normal WhatsApp inside 24 hours, otherwise the
business's approved anril_back_in_stock template -- and closes the rows. Whoever can't be reached
yet (no approved template) stays waiting, so the button can be pressed again later."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

SETTINGS_KEY = "back_in_stock_message"
TEMPLATE_NAME = "anril_back_in_stock"
LANGUAGES = ("en", "ta", "tanglish")
META_LANGUAGE = {"en": "en", "ta": "ta", "tanglish": "en"}  # Tanglish is Roman script
# {{1}} first name, {{2}} shop, {{3}} item (and size/colour), {{4}} price. Starting words only:
# the business edits them before submitting.
STARTING_BODY = {
    "en": "Vanakkam {{1}}, good news from {{2}}: {{3}} is back in stock at {{4}}. Reply to this message to order.",
    "ta": "வணக்கம் {{1}}, {{2}} இலிருந்து நல்ல செய்தி: {{3}} மீண்டும் வந்துவிட்டது, விலை {{4}}. ஆர்டர் செய்ய இந்த மெசேஜுக்கு பதில் அனுப்புங்கள்.",
    "tanglish": "Vanakkam {{1}}, {{2}}-la irundhu good news: {{3}} stock vandhachu, vilai {{4}}. Order panna indha message-ku reply pannunga.",
}
EXAMPLES = ["Priya", "Demo Silks", "Kanchi pattu (Red · XL)", "₹10,500"]
NO_NAME = {"en": "there", "ta": "நண்பரே", "tanglish": "there"}
BODY_LIMIT = 1024
_PLACEHOLDER = re.compile(r"\{\{(\d+)\}\}")


class StockAskError(ValueError):
    """Something staff can fix; routes turn it into a 400."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── the message (one text for the 24-hour message and the template) ──────────


def body_problems(body: str) -> list[str]:
    body = (body or "").strip()
    if not body:
        return ["Write the message."]
    out = []
    if len(body) > BODY_LIMIT:
        out.append(f"The message can be at most {BODY_LIMIT} characters.")
    found = _PLACEHOLDER.findall(body)
    if sorted(found) != ["1", "2", "3", "4"]:
        out.append("Keep {{1}} name, {{2}} shop, {{3}} item and {{4}} price, each once.")
    if body.startswith("{{") or body.endswith("}}"):
        out.append("WhatsApp doesn't allow the message to start or end with a {{…}} box. Add a word around it.")
    return out


def message_settings(db, tenant_id: str) -> dict:
    from app.config_dynamic import get_setting
    import json

    raw = get_setting(SETTINGS_KEY, tenant_id=tenant_id)
    try:
        saved = json.loads(raw) if raw else {}
    except ValueError:
        saved = {}
    language = saved.get("language") if saved.get("language") in LANGUAGES else "en"
    body = (saved.get("body") or "").strip() or STARTING_BODY[language]
    return {"language": language, "body": body, "edited": bool((saved.get("body") or "").strip())}


def save_message_settings(db, tenant_id: str, language: str, body: str | None) -> dict:
    from app.config_dynamic import save_setting
    import json

    if language not in LANGUAGES:
        raise StockAskError("Pick English, Tamil or Tanglish.")
    body = (body or "").strip()
    if body:
        problems = body_problems(body)
        if problems:
            raise StockAskError(problems[0])
    save_setting(SETTINGS_KEY, json.dumps({"language": language, "body": body}, ensure_ascii=False),
                 tenant_id=tenant_id)
    return message_settings(db, tenant_id)


def template_status(db, tenant_id: str) -> str:
    """MISSING / PENDING / APPROVED / REJECTED for the business's anril_back_in_stock."""
    row = _template_row(db, tenant_id, approved_only=False)
    return (row.get("status") or "PENDING").upper() if row else "MISSING"


def _template_row(db, tenant_id: str, *, approved_only: bool) -> dict | None:
    from app.config_dynamic import get_setting

    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    rows = (
        db.table("message_templates").select("*").eq("tenant_id", tenant_id).eq("name", TEMPLATE_NAME).execute()
    ).data or []
    rows = [r for r in rows if not waba_id or r.get("meta_waba_id") == waba_id]
    if approved_only:
        rows = [r for r in rows if (r.get("status") or "").upper() == "APPROVED"]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[0] if rows else None


def fill(body: str, values: list[str]) -> str:
    return _PLACEHOLDER.sub(lambda m: values[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(values) else "",
                            body)


# ── asks ──────────────────────────────────────────────────────────────────────


def _item_and_price(db, tenant_id: str, item_id: str, variant_id: str | None) -> tuple[dict, dict | None, int | None]:
    items = (
        db.table("catalog_items").select("id, name, price_paise, stock_quantity").eq("id", item_id)
        .eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not items:
        raise StockAskError("Product not found")
    variant = None
    if variant_id:
        rows = (
            db.table("catalog_item_variants").select("id, size, colour, price_paise, stock_quantity")
            .eq("id", variant_id).eq("catalog_item_id", item_id).eq("tenant_id", tenant_id).limit(1).execute()
        ).data or []
        if not rows:
            raise StockAskError("That size or colour isn't on this product")
        variant = rows[0]
    price = (variant or {}).get("price_paise")
    if price is None:
        price = items[0].get("price_paise")
    return items[0], variant, price


def record_ask(db, tenant_id: str, *, lead_id: str, item_id: str, variant_id: str | None = None,
               wants_message: bool = True, source: str = "staff", name: str | None = None,
               user_id: str | None = None) -> dict:
    """Note that this customer asked for an out-of-stock item / size. Asking again updates the
    same open row; a "yes, tell me" is never undone by a later ask without it."""
    _, _, price = _item_and_price(db, tenant_id, item_id, variant_id)
    now = _now().isoformat()
    for _ in range(2):
        q = (db.table("stock_waitlist").select("id, wants_message").eq("tenant_id", tenant_id)
             .eq("catalog_item_id", item_id).eq("lead_id", lead_id).is_("closed_at", "null"))
        q = q.eq("variant_id", variant_id) if variant_id else q.is_("variant_id", "null")
        open_rows = q.limit(1).execute().data or []
        if open_rows:
            row = open_rows[0]
            patch = {"last_asked_at": now, "wants_message": bool(row.get("wants_message")) or wants_message}
            if price is not None:
                patch["price_paise"] = price
            db.table("stock_waitlist").update(patch).eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
            return {**row, **patch}
        try:
            return (db.table("stock_waitlist").insert({
                "tenant_id": tenant_id, "catalog_item_id": item_id, "variant_id": variant_id, "lead_id": lead_id,
                "name": (name or "").strip()[:120] or None, "created_by": user_id, "source": source,
                "wants_message": wants_message, "last_asked_at": now, "price_paise": price,
            }).execute().data or [{}])[0]
        except Exception as exc:  # a parallel ask made the open row first: update it instead
            if "23505" not in str(exc) and "duplicate key" not in str(exc).lower():
                raise
    raise StockAskError("Couldn't save the request. Try again.")


def summary(db, tenant_id: str, *, days: int = 30, now: datetime | None = None) -> dict:
    """The tab: per item / size, people who asked in the last `days`, sales missed (the price
    when they asked), how many wait for a message (any age) and the last ask."""
    now = now or _now()
    since = (now - timedelta(days=days)).isoformat()
    recent = (
        db.table("stock_waitlist")
        .select("id, catalog_item_id, variant_id, lead_id, phone, wants_message, last_asked_at, price_paise, closed_at")
        .eq("tenant_id", tenant_id).gte("last_asked_at", since).limit(5000).execute()
    ).data or []
    waiting = (
        db.table("stock_waitlist")
        .select("id, catalog_item_id, variant_id, lead_id, phone, wants_message, last_asked_at, price_paise, closed_at")
        .eq("tenant_id", tenant_id).is_("closed_at", "null").eq("wants_message", True).limit(5000).execute()
    ).data or []
    groups: dict[tuple, dict] = {}

    def group(row):
        key = (row["catalog_item_id"], row.get("variant_id"))
        return groups.setdefault(key, {"catalog_item_id": key[0], "variant_id": key[1], "asked": set(),
                                       "missed_paise": 0, "waiting": set(), "last_asked_at": None})

    for r in recent:
        g = group(r)
        who = r.get("lead_id") or r.get("phone") or r["id"]
        if who not in g["asked"]:
            g["asked"].add(who)
            g["missed_paise"] += int(r.get("price_paise") or 0)
        if not g["last_asked_at"] or str(r["last_asked_at"]) > g["last_asked_at"]:
            g["last_asked_at"] = str(r["last_asked_at"])
    for r in waiting:
        g = group(r)
        g["waiting"].add(r["id"])
        if not g["last_asked_at"] or str(r["last_asked_at"]) > g["last_asked_at"]:
            g["last_asked_at"] = str(r["last_asked_at"])

    item_ids = list({k[0] for k in groups})
    variant_ids = [k[1] for k in groups if k[1]]
    items = {i["id"]: i for i in (
        db.table("catalog_items").select("id, name, stock_quantity").eq("tenant_id", tenant_id)
        .in_("id", item_ids or ["00000000-0000-0000-0000-000000000000"]).execute()
    ).data or []}
    variants = {v["id"]: v for v in (
        db.table("catalog_item_variants").select("id, size, colour, stock_quantity").eq("tenant_id", tenant_id)
        .in_("id", variant_ids or ["00000000-0000-0000-0000-000000000000"]).execute()
    ).data or []}
    from app.services.deals import variant_label

    rows = []
    for (item_id, variant_id), g in groups.items():
        item = items.get(item_id)
        if not item:
            continue
        variant = variants.get(variant_id) if variant_id else None
        stock = (variant or item).get("stock_quantity")
        rows.append({
            "catalog_item_id": item_id, "variant_id": variant_id, "name": item["name"],
            "variant_label": variant_label(variant) if variant else None,
            "asked": len(g["asked"]), "missed_paise": g["missed_paise"], "waiting": len(g["waiting"]),
            "last_asked_at": g["last_asked_at"],
            "in_stock": stock is None or stock > 0, "stock": stock,
        })
    rows.sort(key=lambda r: (-r["asked"], -r["waiting"], r["name"].lower()))
    people = {r.get("lead_id") or r.get("phone") or r["id"] for r in recent}
    return {
        "days": days,
        "people_asked": len(people),
        "missed_paise": sum(r["missed_paise"] for r in rows),
        "waiting": sum(r["waiting"] for r in rows),
        "rows": rows,
    }


# ── Mark back in stock ────────────────────────────────────────────────────────


def _item_label(item: dict, variant: dict | None) -> str:
    from app.services.deals import variant_label

    return f"{item['name']} ({variant_label(variant)})" if variant else item["name"]


async def mark_back(db, tenant_id: str, *, item_id: str, variant_id: str | None = None,
                    user_id: str | None = None, now: datetime | None = None) -> dict:
    """Message everyone waiting for this item / size, once. Team-triggered (the button), like
    Orders' messages. Returns {sent, not_reachable, skipped}; not_reachable stay waiting."""
    from app.config_dynamic import get_setting
    from app.services.call_details_share import window_open
    from app.services.deals import _rupees
    from app.services.orders import _first_name, _one_line, _shop_name

    now = now or _now()
    item, variant, price = _item_and_price(db, tenant_id, item_id, variant_id)
    stock = (variant or item).get("stock_quantity")
    if stock is not None and stock <= 0:
        raise StockAskError("It still shows 0 in stock. Add the new stock first, then mark it back in stock.")
    q = (db.table("stock_waitlist").select("id, lead_id, phone, name, wants_message").eq("tenant_id", tenant_id)
         .eq("catalog_item_id", item_id).is_("closed_at", "null"))
    q = q.eq("variant_id", variant_id) if variant_id else q.is_("variant_id", "null")
    rows = q.limit(1000).execute().data or []
    result = {"sent": 0, "not_reachable": 0, "skipped": 0}
    if not rows:
        return result
    connected = bool(get_setting("meta_phone_number_id", tenant_id=tenant_id)
                     and get_setting("meta_access_token", tenant_id=tenant_id))
    settings = message_settings(db, tenant_id)
    template = _template_row(db, tenant_id, approved_only=True)
    shop, label = _shop_name(db, tenant_id), _item_label(item, variant)
    price_text = _rupees(int(price)) if price is not None else "-"
    lead_ids = [r["lead_id"] for r in rows if r.get("lead_id")]
    leads = {l["id"]: l for l in (
        db.table("leads").select("id, name, phone, opted_out, last_inbound_at").eq("tenant_id", tenant_id)
        .in_("id", lead_ids or ["00000000-0000-0000-0000-000000000000"]).execute()
    ).data or []}
    closed = now.isoformat()
    for row in rows:
        lead = leads.get(row.get("lead_id")) or {}
        if not row.get("wants_message") or lead.get("opted_out") or not lead.get("phone"):
            db.table("stock_waitlist").update({"closed_at": closed}).eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
            result["skipped"] += 1
            continue
        first = _first_name(lead.get("name") or row.get("name"))
        if first == "there":
            first = NO_NAME[settings["language"]]
        values = [_one_line(v) for v in (first, shop, label, price_text)]
        text = fill(settings["body"], values)
        sid, via = None, None
        if connected:
            try:
                if window_open(lead.get("last_inbound_at"), now):
                    from app.services.ai_reply import send_whatsapp
                    sid, via = await send_whatsapp(lead["phone"], text, tenant_id=tenant_id), "text"
                elif template:
                    from app.services.orders import _send_order_template
                    sid, text = await _send_order_template(db, tenant_id, lead["phone"], template, values, None)
                    via = "template"
            except Exception as exc:
                logger.warning("Back-in-stock message to lead %s failed: %s", lead.get("id"), exc)
                sid = None
        if not sid:
            result["not_reachable"] += 1
            continue
        db.table("messages").insert({
            "lead_id": lead["id"], "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
            "content": text, "is_ai_generated": False, "meta_message_id": sid,
        }).execute()
        db.table("stock_waitlist").update({"closed_at": closed, "notified_at": closed, "notify_via": via}) \
            .eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
        result["sent"] += 1
    if user_id:
        from app.services.audit_log import record_audit_event

        record_audit_event(db, tenant_id=tenant_id, actor_user_id=user_id, actor_role=None,
                           action="catalog.back_in_stock", target_type="catalog_item", target_id=item_id,
                           metadata={"item": label, **result})
    return result


def csv_rows(data: dict) -> list[list[str]]:
    from app.services.deals import _rupees

    out = [["Item", "Size / colour", "People asked", "Sales missed", "Want a message", "Last asked", "In stock now"]]
    for r in data["rows"]:
        out.append([r["name"], r["variant_label"] or "", str(r["asked"]), _rupees(r["missed_paise"]),
                    str(r["waiting"]), (r["last_asked_at"] or "")[:10], "yes" if r["in_stock"] else "no"])
    return out
