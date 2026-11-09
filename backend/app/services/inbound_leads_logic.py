"""Pure logic for inbound lead reporting. No DB, no network — unit-testable."""

INBOUND_SOURCES = ("whatsapp", "instagram", "facebook", "telegram", "indiamart", "justdial", "meta_form")


def is_inbound_lead(lead: dict) -> bool:
    """True when the lead arrived through a messaging channel (not upload/manual)."""
    return (lead.get("source") or "") in INBOUND_SOURCES


def lead_origin(lead: dict) -> str:
    """'ad' when an ad campaign is attributed or the lead came from a Meta
    Instant form (a lead ad), else 'organic'."""
    return "ad" if lead.get("ad_campaign_id") or lead.get("source") == "meta_form" else "organic"


def aggregate_inbound(leads: list[dict], days_iso: list[str], today_iso: str) -> dict:
    """
    Aggregate already-fetched inbound leads into the analytics payload.
    Day bucketing uses UTC date (created_at[:10]) to match existing analytics tabs.
    Non-inbound leads are skipped defensively.
    """
    daily = {d: {"organic": 0, "ad": 0} for d in days_iso}
    by_segment = {"A": 0, "B": 0, "C": 0, "D": 0}
    by_channel = {s: 0 for s in INBOUND_SOURCES}
    today = {"total": 0, "organic": 0, "ad": 0}
    rng = {"total": 0, "organic": 0, "ad": 0}

    for lead in leads:
        if not is_inbound_lead(lead):
            continue
        origin = lead_origin(lead)
        day = (lead.get("created_at") or "")[:10]

        rng["total"] += 1
        rng[origin] += 1
        if day in daily:
            daily[day][origin] += 1
        if day == today_iso:
            today["total"] += 1
            today[origin] += 1

        seg = lead.get("segment")
        if seg in by_segment:
            by_segment[seg] += 1
        src = lead.get("source")
        if src in by_channel:
            by_channel[src] += 1

    return {
        "kpis": {"today": today, "range": rng},
        "daily": [
            {"day": d, "organic": daily[d]["organic"], "ad": daily[d]["ad"]}
            for d in days_iso
        ],
        "by_segment": by_segment,
        "by_channel": by_channel,
    }
