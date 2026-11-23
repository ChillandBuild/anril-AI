"""v9.2 screen 118: stop a Reach campaign when too many people push back.

"Push back" = the person said stop to this campaign (broadcast_recipients.opted_out_at, written by the webhook's
opt-out path) or Meta reported they turned off marketing messages (131050 on messages.delivery_error_code).
Above 2% of what was sent (once at least 100 went out), the rest of the run stops, the remaining days of a
multi-day send are not started, and the owner gets one bell. Meta lowers a number's quality on exactly these
signals, so stopping early protects the number for everyone.

Read-only on the webhook's data: nothing here changes how delivery statuses are written.
"""
import logging

logger = logging.getLogger(__name__)

STOP_RATE = 0.02
MIN_SENT = 100
STOPPED_MARKETING = "131050"
BELL_TYPE = "campaign_paused"


def _chunks(items: list, n: int = 200):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def pushback(db, tenant_id: str, broadcast_row_ids: list[str]) -> dict:
    """{"sent", "said_stop", "stopped_marketing", "rate"} over these scheduled_broadcasts rows."""
    from app.services.reports_common import paged
    sent, said_stop, message_ids = 0, 0, []
    for chunk in _chunks([str(x) for x in broadcast_row_ids if x]):
        rows = paged(lambda: (db.table("broadcast_recipients").select("id, meta_message_id, opted_out_at, send_status")
                              .eq("tenant_id", tenant_id).in_("broadcast_id", chunk)
                              .in_("send_status", ["sent", "opted_out_skip"])))
        for r in rows:
            # A row the webhook moved to opted_out_skip was sent first (the person replied "stop" to it).
            if r.get("send_status") == "sent" or r.get("opted_out_at"):
                sent += 1
            if r.get("opted_out_at"):
                said_stop += 1
            elif r.get("meta_message_id"):
                message_ids.append(r["meta_message_id"])
    stopped = 0
    for chunk in _chunks(message_ids, 50):  # ids are long: keep the request URL small
        res = (db.table("messages").select("id").eq("tenant_id", tenant_id).in_("meta_message_id", chunk)
               .eq("delivery_error_code", STOPPED_MARKETING).execute())
        stopped += len(res.data or [])
    rate = (said_stop + stopped) / sent if sent else 0.0
    return {"sent": sent, "said_stop": said_stop, "stopped_marketing": stopped, "rate": rate}


def live_pushback(db, tenant_id: str, lead_ids: list[str], message_ids: list[str], since_iso: str, sent: int) -> dict:
    """The same numbers for a Send Now run still in progress (its recipient rows are only written at the end):
    of the people sent to so far, who said stop since the run started, and who turned off marketing."""
    said_stop = 0
    for chunk in _chunks([str(x) for x in lead_ids if x]):
        res = (db.table("leads").select("id").eq("tenant_id", tenant_id).in_("id", chunk)
               .gte("opted_out_at", since_iso).execute())
        said_stop += len(res.data or [])
    stopped = 0
    for chunk in _chunks([m for m in message_ids if m], 50):
        res = (db.table("messages").select("id").eq("tenant_id", tenant_id).in_("meta_message_id", chunk)
               .eq("delivery_error_code", STOPPED_MARKETING).execute())
        stopped += len(res.data or [])
    rate = (said_stop + stopped) / sent if sent else 0.0
    return {"sent": sent, "said_stop": said_stop, "stopped_marketing": stopped, "rate": rate}


def too_much_pushback(stats: dict) -> bool:
    return stats["sent"] >= MIN_SENT and stats["rate"] > STOP_RATE


def group_row_ids(db, tenant_id: str, row: dict) -> list[str]:
    """This row plus the days of the same multi-day send that already ran."""
    ids = [str(row["id"])]
    if row.get("drip_group_id"):
        res = (db.table("scheduled_broadcasts").select("id").eq("tenant_id", tenant_id)
               .eq("drip_group_id", row["drip_group_id"]).in_("status", ["done", "running", "aborted"]).execute())
        ids += [str(r["id"]) for r in (res.data or []) if str(r["id"]) not in ids]
    return ids


def stop_rest(db, tenant_id: str, row: dict, stats: dict) -> None:
    """Ask the other days of a multi-day send to stop and tell the owner once. Never raises."""
    try:
        if row.get("drip_group_id"):
            (db.table("scheduled_broadcasts").update({"abort_requested": True}).eq("tenant_id", tenant_id)
             .eq("drip_group_id", row["drip_group_id"]).in_("status", ["pending", "running"]).execute())
        from app.services.automation_store import owner_user_ids
        from app.services.notify import notify_user
        pct = round(stats["rate"] * 100, 1)
        name = row.get("template_name") or "your campaign"
        message = (f"{pct}% of the people who got {name} said stop or turned off marketing messages "
                   f"({stats['said_stop'] + stats['stopped_marketing']} of {stats['sent']}). We stopped the rest so "
                   f"WhatsApp doesn't lower your number's quality. Check who it went to before sending again.")
        for uid in owner_user_ids(db, tenant_id):
            notify_user(tenant_id, uid, BELL_TYPE, "A campaign was stopped", message, db=db,
                        push_url="/dashboard/outbound-leads")
    except Exception as e:
        logger.warning(f"campaign stop for broadcast {row.get('id')} tenant {tenant_id} failed: {e}")
