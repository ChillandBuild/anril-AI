"""v9.2 #157 "Nobody has replied": tell the owner when a chat was handed to a person and 15 minutes later
no teammate has written back.

Runs every 5 minutes (queue task handover-stale-alert). One alert per handover: stale_alerted_at is set first,
with a condition ("still null"), and only the run that wins that update sends the alert, so an overlap or a
re-run can never alert twice. A handover that gets a reply, is resolved, or is older than 2 hours is left alone
(an old pile after an outage, or on the first run after deploy, must not wake the owner). The alert goes through the normal alerts system
(app_notifications + web push), so the owner's alert on/off choices apply."""
import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=15)
GIVE_UP_AFTER = timedelta(hours=2)  # older than this is not "just now": and the first run after deploy must not burst old alerts
_query_failed_logged = False
ALERT_TYPE = "handover_unanswered"
_BATCH = 200


def _team_replied(db, tenant_id: str, lead_id: str, since: str) -> bool:
    """A teammate (not the AI, not an automatic message) wrote in this chat after the handover opened."""
    rows = (db.table("messages").select("id").eq("tenant_id", tenant_id).eq("lead_id", lead_id)
            .eq("direction", "outbound").not_.is_("sent_by_user_id", "null").gte("created_at", since)
            .limit(1).execute().data) or []
    return bool(rows)


def _owner_ids(db, tenant_id: str) -> list[str]:
    rows = (db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner").execute().data) or []
    return [r["user_id"] for r in rows if r.get("user_id")]


def sweep_stale_handovers(now: datetime | None = None, db=None) -> int:
    """Returns how many handovers were alerted this run."""
    db = db or get_supabase()
    now = now or datetime.now(timezone.utc)
    newest_open = (now - STALE_AFTER).isoformat()
    oldest_open = (now - GIVE_UP_AFTER).isoformat()
    global _query_failed_logged
    try:
        rows = (db.table("chat_handovers").select("id,tenant_id,lead_id,opened_at")
                .eq("status", "pending").is_("stale_alerted_at", "null")
                .lte("opened_at", newest_open).gte("opened_at", oldest_open)
                .order("opened_at").limit(_BATCH).execute().data) or []
    except Exception as e:  # noqa: BLE001  most likely migration 332 (stale_alerted_at) is not applied yet
        if not _query_failed_logged:
            _query_failed_logged = True
            logger.warning("handover stale sweep skipped: query failed (%s). Is migration 332 applied?", type(e).__name__)
        return 0
    _query_failed_logged = False
    alerted = 0
    for h in rows:
        try:
            if _team_replied(db, h["tenant_id"], h["lead_id"], h["opened_at"]):
                continue  # answered: no alert (and it ages out of the 24 hour window by itself)
            won = (db.table("chat_handovers").update({"stale_alerted_at": now.isoformat()})
                   .eq("id", h["id"]).eq("status", "pending").is_("stale_alerted_at", "null").execute().data) or []
            if not won:
                continue  # another run took it, or it was resolved a moment ago
            alerted += _alert_owner(db, h)
        except Exception as e:  # noqa: BLE001  one bad row must not stop the rest
            logger.warning("handover stale alert failed for %s: %s", h.get("id"), e)
    return alerted


def _alert_owner(db, h: dict) -> int:
    from app.services.notify import notify_user
    name = None
    try:
        lead = (db.table("leads").select("name").eq("id", h["lead_id"]).eq("tenant_id", h["tenant_id"]).limit(1).execute().data) or []
        name = (lead[0].get("name") or "").strip() if lead else None
    except Exception:  # noqa: BLE001
        pass
    who = name or "A customer"
    told = 0
    for uid in _owner_ids(db, h["tenant_id"]):
        notify_user(
            h["tenant_id"], uid, ALERT_TYPE,
            "Nobody has replied yet",
            f"{who} was handed to your team 15 minutes ago and nobody has replied.",
            db=db, push_url=f"/dashboard/conversations?lead={h['lead_id']}",
        )
        told += 1
    return 1 if told else 0
