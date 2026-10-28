"""Schedule a template: pick a time instead of sending a template straight away.

Offered wherever a template can be sent (chat, Leads, Telecalling, the New message form). One row
per message in `scheduled_template_sends` (migration 235); the `scheduled-templates` scheduler job
sends the due ones. Only templates can be scheduled: the 24-hour window may have closed by send time.

Status: scheduled -> sending -> sent | failed | skipped, or scheduled -> cancelled (and back, for the
Undo toast). `sending` is the claim, so two runs never double-send. A row stuck in `sending` is marked
failed, never re-sent: Meta may already have delivered it.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.services.call_details_share import ShareError, _lead, _whatsapp_ready, prepare_template, send_approved_template

logger = logging.getLogger(__name__)

TABLE = "scheduled_template_sends"
MIN_AHEAD = timedelta(minutes=5)
MAX_AHEAD = timedelta(days=30)
MAX_PENDING_PER_LEAD = 10
STUCK_AFTER = timedelta(minutes=15)
# A message that was not sent stays visible in the chat for this long, then drops off the list.
PROBLEM_VISIBLE_FOR = timedelta(days=2)

INTERRUPTED = "Interrupted while sending. Check the chat to see whether it went out."

PUBLIC_FIELDS = ("id", "lead_id", "template_name", "content", "send_at", "status", "reason", "created_at")


class NotFound(ShareError):
    """The scheduled message doesn't exist for this tenant; the route turns it into a 404."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def public(row: dict) -> dict:
    return {k: row.get(k) for k in PUBLIC_FIELDS}


def check_send_at(send_at: datetime, now: datetime) -> datetime:
    """The send time as UTC, or a ShareError the person can act on."""
    if send_at.tzinfo is None:
        raise ShareError("Pick a date and time.")
    send_at = send_at.astimezone(timezone.utc)
    if send_at - now < MIN_AHEAD:
        raise ShareError("Pick a time at least 5 minutes from now.")
    if send_at - now > MAX_AHEAD:
        raise ShareError("Scheduling goes up to 30 days ahead.")
    return send_at


def schedule_template(db, tenant_id: str, user_id: str | None, lead_id: str, template_id: str,
                      variables: list[str], send_at: datetime, now: datetime | None = None) -> dict:
    now = now or utcnow()
    send_at = check_send_at(send_at, now)
    lead = _lead(db, tenant_id, lead_id)
    if not lead:
        raise NotFound("Lead not found.")
    if not _whatsapp_ready(tenant_id, lead):
        raise ShareError("WhatsApp isn't available for this lead.")
    pending = (
        db.table(TABLE).select("id").eq("tenant_id", tenant_id).eq("lead_id", lead_id).eq("status", "scheduled")
        .limit(MAX_PENDING_PER_LEAD).execute()
    ).data or []
    if len(pending) >= MAX_PENDING_PER_LEAD:
        raise ShareError(f"This lead already has {MAX_PENDING_PER_LEAD} messages scheduled.")
    template, values, content = prepare_template(db, tenant_id, template_id, variables)
    rows = db.table(TABLE).insert({
        "tenant_id": tenant_id, "lead_id": lead_id, "template_id": template["id"], "template_name": template["name"],
        "variables": values, "content": content, "send_at": send_at.isoformat(), "status": "scheduled",
        "created_by": user_id,
    }).execute().data or []
    return public(rows[0])


def list_for_lead(db, tenant_id: str, lead_id: str, now: datetime | None = None) -> list[dict]:
    """Waiting messages, plus any that were not sent in the last two days (so the chat can say why)."""
    now = now or utcnow()
    base = db.table(TABLE).select("*").eq("tenant_id", tenant_id).eq("lead_id", lead_id)
    # Two reads, so a pile of old failures can never push a waiting message past the row limit.
    waiting = base.in_("status", ["scheduled", "sending"]).order("send_at").limit(50).execute().data or []
    cutoff = (now - PROBLEM_VISIBLE_FOR).isoformat()
    problems = (
        db.table(TABLE).select("*").eq("tenant_id", tenant_id).eq("lead_id", lead_id)
        .in_("status", ["failed", "skipped"]).gte("send_at", cutoff).order("send_at").limit(20).execute()
    ).data or []
    return [public(r) for r in sorted(waiting + problems, key=lambda r: r["send_at"])]


def _why_not(db, tenant_id: str, schedule_id: str, action: str) -> ShareError:
    rows = db.table(TABLE).select("status").eq("id", schedule_id).eq("tenant_id", tenant_id).limit(1).execute().data or []
    if not rows:
        return NotFound("Scheduled message not found.")
    status = rows[0]["status"]
    if status == "sent":
        return ShareError("It has already been sent.")
    if status == "sending":
        return ShareError("It is being sent right now.")
    if status == "cancelled" and action != "restore":
        return ShareError("It was already cancelled.")
    if status in ("failed", "skipped"):
        return ShareError("It was not sent.")
    return ShareError("It can't be changed any more.")


def cancel(db, tenant_id: str, schedule_id: str, now: datetime | None = None) -> dict:
    now = now or utcnow()
    rows = (
        db.table(TABLE).update({"status": "cancelled", "cancelled_at": now.isoformat()})
        .eq("id", schedule_id).eq("tenant_id", tenant_id).eq("status", "scheduled").execute()
    ).data or []
    if not rows:
        raise _why_not(db, tenant_id, schedule_id, "cancel")
    return public(rows[0])


def restore(db, tenant_id: str, schedule_id: str, now: datetime | None = None) -> dict:
    """Undo a cancel. Only while its send time is still ahead."""
    now = now or utcnow()
    rows = (
        db.table(TABLE).update({"status": "scheduled", "cancelled_at": None})
        .eq("id", schedule_id).eq("tenant_id", tenant_id).eq("status", "cancelled")
        .gte("send_at", now.isoformat()).execute()
    ).data or []
    if not rows:
        existing = db.table(TABLE).select("status").eq("id", schedule_id).eq("tenant_id", tenant_id).limit(1).execute().data or []
        if existing and existing[0]["status"] == "cancelled":
            raise ShareError("Too late to undo: its send time has passed.")
        raise _why_not(db, tenant_id, schedule_id, "restore")
    return public(rows[0])


def reschedule(db, tenant_id: str, schedule_id: str, send_at: datetime, now: datetime | None = None) -> dict:
    now = now or utcnow()
    send_at = check_send_at(send_at, now)
    rows = (
        db.table(TABLE).update({"send_at": send_at.isoformat()})
        .eq("id", schedule_id).eq("tenant_id", tenant_id).eq("status", "scheduled").execute()
    ).data or []
    if not rows:
        raise _why_not(db, tenant_id, schedule_id, "reschedule")
    return public(rows[0])


# ---------------------------------------------------------------- sending

def _finish(db, schedule_id: str, status: str, reason: str | None = None) -> None:
    patch: dict = {"status": status, "reason": reason[:300] if reason else None}
    if status == "sent":
        patch["sent_at"] = utcnow().isoformat()
    db.table(TABLE).update(patch).eq("id", schedule_id).execute()


def _plain_reason(message: str) -> str:
    """Meta's refusals come back as raw JSON inside the message; show the plain version."""
    if "WhatsApp didn't send it" not in message:
        return message
    from app.services.auto_messages import _plain_failure
    return _plain_failure(message)


def _notify_failure(db, row: dict, lead: dict | None, reason: str) -> None:
    if not row.get("created_by"):
        return
    from app.services.notify import notify_user
    who = ((lead or {}).get("name") or "").strip() or "a lead"
    notify_user(
        row["tenant_id"], row["created_by"], "scheduled_template_failed", "Scheduled template not sent",
        f"The template you scheduled for {who} wasn't sent: {reason}", db=db, push_url="/dashboard/conversations",
    )


async def send_one(db, row: dict) -> bool:
    """Claims a scheduled row, then sends. Final status: sent | failed | skipped, with a reason."""
    claimed = (
        db.table(TABLE).update({"status": "sending", "claimed_at": utcnow().isoformat()})
        .eq("id", row["id"]).eq("status", "scheduled").execute()
    ).data or []
    if not claimed:
        return False
    tenant_id = row["tenant_id"]
    lead = _lead(db, tenant_id, row["lead_id"])
    if not lead:
        _finish(db, row["id"], "skipped", "The lead was removed.")
        return False
    if lead.get("opted_out"):
        _finish(db, row["id"], "skipped", "The customer opted out.")
        return False
    if not _whatsapp_ready(tenant_id, lead):
        _finish(db, row["id"], "skipped", "WhatsApp isn't available for this lead.")
        return False
    try:
        sid, content = await send_approved_template(
            db, tenant_id, lead["phone"], row.get("template_id") or "", list(row.get("variables") or []),
        )
    except ShareError as e:
        reason = _plain_reason(str(e))
        _finish(db, row["id"], "failed", reason)
        _notify_failure(db, row, lead, reason)
        return False
    except Exception as e:
        logger.error(f"scheduled_templates: send {row['id']} crashed for tenant {tenant_id}: {e}")
        reason = "Something went wrong while sending it."
        _finish(db, row["id"], "failed", reason)
        _notify_failure(db, row, lead, reason)
        return False
    _finish(db, row["id"], "sent")
    try:
        db.table("messages").insert({
            "lead_id": row["lead_id"], "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
            "content": content, "is_ai_generated": False, "meta_message_id": sid,
        }).execute()
    except Exception as e:
        logger.warning(f"scheduled_templates: message log insert failed for {row['id']}: {e}")
    return True


async def process_due(limit: int = 50) -> int:
    """Scheduler job: send every scheduled row whose time has come. Rows left in `sending` by a crash
    are marked failed, never re-sent."""
    db = get_supabase()
    now = utcnow()
    stuck = (
        db.table(TABLE).update({"status": "failed", "reason": INTERRUPTED})
        .eq("status", "sending").lt("claimed_at", (now - STUCK_AFTER).isoformat()).execute()
    ).data or []
    for row in stuck:
        # Nobody can tell whether the customer got it, so whoever scheduled it is told to look.
        _notify_failure(db, row, _lead(db, row["tenant_id"], row["lead_id"]), INTERRUPTED)
    due = (
        db.table(TABLE).select("*").eq("status", "scheduled").lte("send_at", now.isoformat())
        .order("send_at").limit(limit).execute()
    ).data or []
    sent = 0
    for row in due:
        try:
            if await send_one(db, row):
                sent += 1
        except Exception as e:
            logger.error(f"scheduled_templates: unexpected error on {row.get('id')}: {e}")
    return sent
