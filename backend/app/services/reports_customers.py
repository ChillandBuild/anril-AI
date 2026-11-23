"""Reports > Customers: first chat -> hot -> paid, new vs repeat buyers, where people came from.

New chats = people who came in through a chat channel (WhatsApp, Instagram, QR, Instant form...) and whose
record was created in the days. Hot = segment A. Paid (buyers) = people with a paid order in the days;
repeat = they had a paid order before the days. The funnel follows the new chats of the days: how many
turned hot, how many have paid since.
"""
from app.services.reports_common import Flags, Period, chunks, count_phrase, paged, plural, sentence
from app.services.reports_data import buyers_split, is_hot, new_chats, new_leads, won_deals

CAME_FROM_LABELS = {
    "qr": "QR code", "instant_form": "Instant form", "google_ads": "Google Ads", "meta_ad": "Meta ad",
    "organic": "Chatted with you directly", "upload": "Uploaded list", "manual": "Added by hand",
    "indiamart": "IndiaMART", "justdial": "JustDial", "website": "Website", "api": "Website form", "store": "Store",
}


def came_from_key(lead: dict, platforms: dict[str, str]) -> str:
    """Where one person came from, first touch first: QR, Instant form, an ad, a direct chat, a list."""
    if lead.get("qr_link_id") or lead.get("source") == "qr":
        return "qr"
    source = lead.get("source") or ""
    if source == "meta_form":
        return "instant_form"
    if lead.get("ad_campaign_id"):
        return "google_ads" if platforms.get(str(lead["ad_campaign_id"])) == "google" else "meta_ad"
    if source in ("whatsapp", "instagram", "facebook", "telegram"):
        return "organic"
    return source or "organic"


def campaign_platforms(db, tenant_id: str) -> dict[str, str]:
    rows = paged(lambda: db.table("ad_campaigns").select("id,platform").eq("tenant_id", tenant_id))
    return {str(r["id"]): r.get("platform") or "" for r in rows}


def cohort_buyer_ids(db, tenant_id: str, lead_ids: list[str]) -> set[str]:
    """Which of these people have a paid order (any time)."""
    out: set[str] = set()
    for part in chunks(lead_ids):
        rows = paged(lambda part=part: db.table("deals").select("id,lead_id").eq("tenant_id", tenant_id)
                     .eq("stage", "won").in_("lead_id", part))
        out |= {r["lead_id"] for r in rows if r.get("lead_id")}
    return out


def compute(db, tenant_id: str, period: Period, flags: Flags) -> tuple[dict, dict]:
    chats = new_chats(db, tenant_id, period)
    hot = [lead for lead in chats if is_hot(lead)]
    split = buyers_split(db, tenant_id, period, won_deals(db, tenant_id, period))
    bought = cohort_buyer_ids(db, tenant_id, [lead["id"] for lead in chats])
    platforms = campaign_platforms(db, tenant_id)

    counts: dict[str, int] = {}
    for lead in new_leads(db, tenant_id, period):
        key = came_from_key(lead, platforms)
        counts[key] = counts.get(key, 0) + 1
    came_from = [{"key": k, "label": CAME_FROM_LABELS.get(k, k.replace("_", " ").capitalize()), "count": n,
                  "people": {"metric": "came_from", "id": k}}
                 for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    numbers = {"first_chats": len(chats), "hot": len(hot), "paid": len(split["buyer_ids"]),
               "new_buyers": len(split["new_ids"]), "repeat_buyers": len(split["repeat_ids"])}
    funnel = [
        {"key": "first_chats", "label": "First chat", "count": len(chats), "people": {"metric": "new_chats"}},
        {"key": "hot", "label": "Turned hot", "count": len(hot), "people": {"metric": "hot"}},
        {"key": "paid", "label": "Paid", "count": len(bought), "people": {"metric": "funnel_paid"}},
    ]
    return numbers, {"funnel": funnel, "came_from": came_from}


def in_short(numbers: dict, before: dict | None) -> str:
    b = before or {}
    parts = [count_phrase(numbers.get("first_chats"), b.get("first_chats"), "new chat")]
    if numbers.get("hot"):
        parts.append(f"{numbers['hot']} hot")
    if numbers.get("paid"):
        mix = ""
        if numbers.get("repeat_buyers"):
            mix = f" ({numbers['repeat_buyers']} came back)"
        parts.append(f"{plural(numbers['paid'], 'person')} paid{mix}")
    return sentence(parts, "No new chats in these days.")
