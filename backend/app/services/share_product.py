"""Conversations 'Share product': a team member sends one catalogue item to a lead on WhatsApp.

The item's first photo goes out with its name and price as the caption; an item
with no photo goes out as a text message. Same 24-hour rule as any free
message: WhatsApp only delivers it inside the window.
"""
from datetime import datetime, timedelta, timezone

from app.services.ai_reply import get_last_send_error, send_whatsapp
from app.services.meta_cloud import send_media_message

BUCKET = "catalog-media"
CAPTION_LIMIT = 1024  # WhatsApp caption limit


class ShareProductError(Exception):
    pass


def _rupees(paise: int) -> str:
    rupees = paise / 100
    return f"₹{rupees:,.0f}" if rupees == int(rupees) else f"₹{rupees:,.2f}"


def product_caption(item: dict) -> str:
    lines = [str(item.get("name") or "").strip()]
    price = item.get("price_paise")
    if price:
        price_line = _rupees(int(price))
        if item.get("price_note"):
            price_line += f" ({str(item['price_note']).strip()})"
        lines.append(price_line)
    description = str(item.get("description") or "").strip()
    if description:
        lines.append("")
        lines.append(description)
    return "\n".join(line for line in lines if line is not None).strip()[:CAPTION_LIMIT]


def window_open(last_inbound_at: str | None, now: datetime) -> bool:
    if not last_inbound_at:
        return False
    at = datetime.fromisoformat(str(last_inbound_at).replace("Z", "+00:00"))
    return now - at < timedelta(hours=24)


async def share_product(
    db, tenant_id: str, lead_id: str, item_id: str, *, now: datetime | None = None, sender: dict | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    leads = (
        db.table("leads").select("id,phone,source,opted_out,last_inbound_at")
        .eq("id", lead_id).eq("tenant_id", tenant_id).is_("deleted_at", "null").limit(1).execute()
    ).data or []
    if not leads:
        raise ShareProductError("Lead not found.")
    lead = leads[0]
    if lead.get("source") in ("instagram", "facebook", "telegram") or not lead.get("phone"):
        raise ShareProductError("Products can be shared on WhatsApp chats only.")
    if lead.get("opted_out"):
        raise ShareProductError("This lead opted out of messages.")
    if not window_open(lead.get("last_inbound_at"), now):
        raise ShareProductError("The customer hasn't messaged in the last 24 hours, so WhatsApp won't deliver this. Send a template instead.")

    items = (
        db.table("catalog_items").select("id,name,price_paise,price_note,description")
        .eq("id", item_id).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not items:
        raise ShareProductError("Product not found.")
    item = items[0]
    caption = product_caption(item)

    photos = (
        db.table("catalog_media").select("storage_path")
        .eq("catalog_item_id", item_id).eq("tenant_id", tenant_id)
        .order("sort_order").limit(1).execute()
    ).data or []

    if photos:
        url = db.storage.from_(BUCKET).get_public_url(photos[0]["storage_path"])
        try:
            resp = await send_media_message(
                to_number=lead["phone"], media_link=url, wa_type="image", caption=caption, tenant_id=tenant_id,
            )
        except Exception as e:
            raise ShareProductError(f"WhatsApp didn't send it: {str(e)[:300]}")
        sid = ((resp or {}).get("messages") or [{}])[0].get("id")
        media = {"media_type": "image", "media_url": url}
    else:
        sid = await send_whatsapp(lead["phone"], caption, tenant_id=tenant_id)
        media = {}
    if not sid:
        raise ShareProductError(f"WhatsApp didn't send it: {get_last_send_error() or 'unknown error'}")

    rows = db.table("messages").insert({
        "lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
        "content": caption, "is_ai_generated": False, "meta_message_id": sid, **media, **(sender or {}),
    }).execute().data or []
    db.table("leads").update({"needs_human_intervention": False}).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
    return rows[0] if rows else {"sent": True}
