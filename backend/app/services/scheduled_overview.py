"""The "Scheduled templates" page: every scheduled template and broadcast of a tenant in one list.

Reads `scheduled_template_sends` (one row per lead, grouped into batches by batch_id) and
`scheduled_broadcasts` (a drip is one row per day, grouped by drip_group_id). The changes themselves
(cancel, undo, move to a new time) reuse scheduled_templates for templates and are applied here for
broadcasts. Needs migration 236.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.services import scheduled_templates as templates
from app.services.call_details_share import ShareError

logger = logging.getLogger(__name__)

BROADCASTS = "scheduled_broadcasts"
FILE_BUCKET = "broadcast-csvs"
# Rows that are done (sent, not sent, cancelled) stay on the page this long, then drop off.
HISTORY_DAYS = 7
ROW_LIMIT = 1000
# A broadcast sent straight away is also a scheduled_broadcasts row; treat it as scheduled only when
# it was set to go out later than this after it was made.
SEND_NOW_SLACK = timedelta(minutes=2)

_BROADCAST_STATUS = {
    "pending": "scheduled", "running": "sending", "done": "sent",
    "failed": "failed", "aborted": "failed", "cancelled": "cancelled",
}
_TEMPLATE_BASE = (
    "id", "lead_id", "template_name", "content", "send_at", "status", "reason", "created_by", "batch_id", "batch_label",
)
_BROADCAST_BASE = (
    "id", "template_name", "schedule_type", "fire_at", "status", "created_by", "created_at", "drip_group_id",
    "recipient_count", "csv_file_name", "csv_file_path", "error",
)


def _iso(value) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _names(db, tenant_id: str, user_ids: set[str]) -> dict[str, str]:
    """user id -> display name. The owner may not be a caller, so they are named by role."""
    names: dict[str, str] = {}
    if not user_ids:
        return names
    ids = sorted(user_ids)
    for row in (db.table("callers").select("user_id,name").eq("tenant_id", tenant_id).in_("user_id", ids).execute().data or []):
        if row.get("user_id") and row.get("name"):
            names[row["user_id"]] = row["name"]
    owners = db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner").in_("user_id", ids).execute().data or []
    for row in owners:
        names.setdefault(row["user_id"], "Owner")
    return names


def _recent(now: datetime) -> str:
    return (now - timedelta(days=HISTORY_DAYS)).isoformat()


def _assigned_lead_ids(db, tenant_id: str, caller_id: str, lead_ids: list[str]) -> set[str]:
    """The leads among lead_ids that are assigned to this caller (Leads shows a caller only those)."""
    mine: set[str] = set()
    for i in range(0, len(lead_ids), 200):
        chunk = lead_ids[i:i + 200]
        rows = db.table("leads").select("id").eq("tenant_id", tenant_id).eq("assigned_to", caller_id).in_("id", chunk).execute().data or []
        mine.update(r["id"] for r in rows)
    return mine


def list_templates(db, tenant_id: str, now: datetime, caller_id: str | None = None) -> list[dict]:
    """caller_id: set for a caller, who only sees messages for leads assigned to them."""
    cols = ",".join(_TEMPLATE_BASE)
    base = db.table(templates.TABLE).select(cols).eq("tenant_id", tenant_id)
    waiting = base.in_("status", ["scheduled", "sending"]).order("send_at").limit(ROW_LIMIT).execute().data or []
    done = (
        db.table(templates.TABLE).select(cols).eq("tenant_id", tenant_id)
        .in_("status", ["sent", "failed", "skipped", "cancelled"]).gte("send_at", _recent(now))
        .order("send_at", desc=True).limit(ROW_LIMIT).execute()
    ).data or []
    rows = waiting + done
    if caller_id:
        mine = _assigned_lead_ids(db, tenant_id, caller_id, sorted({r["lead_id"] for r in rows}))
        rows = [r for r in rows if r["lead_id"] in mine]
    lead_ids = sorted({r["lead_id"] for r in rows})
    leads: dict[str, dict] = {}
    for i in range(0, len(lead_ids), 200):
        chunk = lead_ids[i:i + 200]
        for lead in (db.table("leads").select("id,name,phone,source").eq("tenant_id", tenant_id).in_("id", chunk).execute().data or []):
            leads[lead["id"]] = lead
    by = _names(db, tenant_id, {r["created_by"] for r in rows if r.get("created_by")})
    out = []
    for r in rows:
        lead = leads.get(r["lead_id"]) or {}
        out.append({
            "id": r["id"], "lead_id": r["lead_id"], "lead_name": lead.get("name"), "lead_phone": lead.get("phone"),
            "lead_source": lead.get("source"), "template_name": r["template_name"], "content": r["content"],
            "send_at": r["send_at"], "status": r["status"], "reason": r.get("reason"),
            "created_by_name": by.get(r.get("created_by") or "", "Team member"),
            "batch_id": r.get("batch_id"), "batch_label": r.get("batch_label"),
        })
    return out


def _is_later(row: dict) -> bool:
    if row.get("schedule_type") == "drip" or row.get("status") == "pending":
        return True
    try:
        return _iso(row["fire_at"]) - _iso(row["created_at"]) > SEND_NOW_SLACK
    except (KeyError, ValueError, TypeError):
        return False


def list_broadcasts(db, tenant_id: str, now: datetime) -> list[dict]:
    cols = ",".join(_BROADCAST_BASE)
    waiting = (
        db.table(BROADCASTS).select(cols).eq("tenant_id", tenant_id).in_("status", ["pending", "running"])
        .order("fire_at").limit(ROW_LIMIT).execute()
    ).data or []
    done = (
        db.table(BROADCASTS).select(cols).eq("tenant_id", tenant_id).in_("status", ["done", "failed", "aborted", "cancelled"])
        .gte("fire_at", _recent(now)).order("fire_at", desc=True).limit(ROW_LIMIT).execute()
    ).data or []
    rows = [r for r in waiting + done if _is_later(r)]
    by = _names(db, tenant_id, {r["created_by"] for r in rows if r.get("created_by")})
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r.get("drip_group_id") or r["id"], []).append(r)
    out = []
    for members in groups.values():
        members.sort(key=lambda r: r["fire_at"])
        statuses = {_BROADCAST_STATUS.get(m["status"], "failed") for m in members}
        # One status for the whole drip: still going out while any day is waiting.
        status = next((s for s in ("sending", "scheduled", "failed", "cancelled", "sent") if s in statuses), "sent")
        waiting_days = [m for m in members if m["status"] == "pending"]
        head = waiting_days[0] if waiting_days else members[0]
        first = members[0]
        out.append({
            "id": head["id"], "ids": [m["id"] for m in members], "kind": "drip" if len(members) > 1 or head.get("schedule_type") == "drip" else "scheduled",
            "template_name": first["template_name"], "send_at": head["fire_at"], "status": status,
            "recipients": sum(int(m.get("recipient_count") or 0) for m in members), "days": len(members),
            "file_name": first.get("csv_file_name"), "has_file": bool(first.get("csv_file_path")),
            "created_by_name": by.get(first.get("created_by") or "", "Team member"),
            "error": next((m["error"] for m in members if m.get("error")), None),
        })
    out.sort(key=lambda b: b["send_at"])
    return out


def file_link(db, tenant_id: str, broadcast_id: str) -> dict:
    """A short-lived download link for the file a broadcast was uploaded from."""
    rows = db.table(BROADCASTS).select("csv_file_name,csv_file_path").eq("id", broadcast_id).eq("tenant_id", tenant_id).limit(1).execute().data or []
    if not rows or not rows[0].get("csv_file_path"):
        raise templates.NotFound("There is no file for this broadcast.")
    path = rows[0]["csv_file_path"]
    # The path came from the client at upload time: a "../" segment could climb into another tenant's folder.
    if not path.startswith(f"{tenant_id}/") or ".." in path.split("/") or "\\" in path:
        raise templates.NotFound("There is no file for this broadcast.")
    result = db.storage.from_(FILE_BUCKET).create_signed_url(path, 300)
    url = (result.get("signedURL") or result.get("signedUrl")) if isinstance(result, dict) else (
        getattr(result, "signedURL", None) or getattr(result, "signedUrl", None) or getattr(result, "url", None))
    if not url:
        raise ShareError("Couldn't prepare the file. Try again.")
    return {"url": url, "file_name": rows[0].get("csv_file_name") or "broadcast.csv"}


# ---------------------------------------------------------------- changes to broadcasts

def _pending_rows(db, tenant_id: str, broadcast_id: str) -> list[dict]:
    """Every day still waiting in the drip this broadcast belongs to (or just this broadcast)."""
    row = db.table(BROADCASTS).select("id,drip_group_id,fire_at,status").eq("id", broadcast_id).eq("tenant_id", tenant_id).limit(1).execute().data or []
    if not row:
        raise templates.NotFound("Scheduled broadcast not found.")
    group = row[0].get("drip_group_id")
    if not group:
        return [row[0]]
    return db.table(BROADCASTS).select("id,drip_group_id,fire_at,status").eq("tenant_id", tenant_id).eq("drip_group_id", group).execute().data or []


def cancel_broadcast(db, tenant_id: str, broadcast_id: str, now: datetime) -> int:
    rows = [r for r in _pending_rows(db, tenant_id, broadcast_id) if r["status"] == "pending"]
    if not rows:
        raise ShareError("It is not waiting any more.")
    for r in rows:
        db.table(BROADCASTS).update({"status": "cancelled"}).eq("id", r["id"]).eq("tenant_id", tenant_id).eq("status", "pending").execute()
    return len(rows)


def restore_broadcast(db, tenant_id: str, broadcast_id: str, now: datetime) -> int:
    rows = [r for r in _pending_rows(db, tenant_id, broadcast_id) if r["status"] == "cancelled" and _iso(r["fire_at"]) > now]
    if not rows:
        raise ShareError("Too late to undo: its send time has passed.")
    for r in rows:
        db.table(BROADCASTS).update({"status": "pending"}).eq("id", r["id"]).eq("tenant_id", tenant_id).eq("status", "cancelled").execute()
    return len(rows)


def reschedule_broadcast(db, tenant_id: str, broadcast_id: str, send_at: datetime, now: datetime) -> int:
    """Moves the waiting days so the first one goes at send_at; later drip days keep their spacing."""
    send_at = templates.check_send_at(send_at, now)
    rows = sorted((r for r in _pending_rows(db, tenant_id, broadcast_id) if r["status"] == "pending"), key=lambda r: r["fire_at"])
    if not rows:
        raise ShareError("It is not waiting any more.")
    shift = send_at - _iso(rows[0]["fire_at"])
    for r in rows:
        moved = _iso(r["fire_at"]) + shift
        db.table(BROADCASTS).update({"fire_at": moved.astimezone(timezone.utc).isoformat()}).eq("id", r["id"]).eq("tenant_id", tenant_id).eq("status", "pending").execute()
    return len(rows)


# ---------------------------------------------------------------- bulk

def apply_bulk(db, tenant_id: str, action: str, template_ids: list[str], broadcast_ids: list[str],
               send_at: datetime | None, can_templates: bool, can_broadcasts: bool, now: datetime,
               caller_id: str | None = None) -> dict:
    """Runs one change over many rows. Each row succeeds or fails on its own; the failures come back
    with a plain reason so the page can say what was left alone. caller_id: a caller may only change
    messages for leads assigned to them."""
    if action not in ("cancel", "restore", "reschedule"):
        raise ShareError("Unknown action.")
    if action == "reschedule" and send_at is None:
        raise ShareError("Pick a date and time.")
    done, failed = 0, []
    allowed: set[str] | None = None
    if caller_id and template_ids and can_templates:
        owned = []
        for i in range(0, len(template_ids), 200):
            chunk = template_ids[i:i + 200]
            owned += db.table(templates.TABLE).select("id,lead_id").eq("tenant_id", tenant_id).in_("id", chunk).execute().data or []
        mine = _assigned_lead_ids(db, tenant_id, caller_id, sorted({r["lead_id"] for r in owned}))
        allowed = {r["id"] for r in owned if r["lead_id"] in mine}

    def attempt(kind: str, item_id: str, run):
        nonlocal done
        try:
            run()
            done += 1
        except ShareError as e:
            failed.append({"kind": kind, "id": item_id, "reason": str(e)})
        except Exception as e:  # one bad row must not stop the rest
            logger.error(f"scheduled_overview: {action} {kind} {item_id} failed: {e}")
            failed.append({"kind": kind, "id": item_id, "reason": "Something went wrong."})

    for item_id in template_ids:
        if not can_templates:
            failed.append({"kind": "template", "id": item_id, "reason": "You can't change scheduled templates."})
            continue
        if allowed is not None and item_id not in allowed:
            failed.append({"kind": "template", "id": item_id, "reason": "Scheduled message not found."})
            continue
        fn = {"cancel": lambda i=item_id: templates.cancel(db, tenant_id, i, now),
              "restore": lambda i=item_id: templates.restore(db, tenant_id, i, now),
              "reschedule": lambda i=item_id: templates.reschedule(db, tenant_id, i, send_at, now)}[action]
        attempt("template", item_id, fn)
    for item_id in broadcast_ids:
        if not can_broadcasts:
            failed.append({"kind": "broadcast", "id": item_id, "reason": "You can't change scheduled broadcasts."})
            continue
        fn = {"cancel": lambda i=item_id: cancel_broadcast(db, tenant_id, i, now),
              "restore": lambda i=item_id: restore_broadcast(db, tenant_id, i, now),
              "reschedule": lambda i=item_id: reschedule_broadcast(db, tenant_id, i, send_at, now)}[action]
        attempt("broadcast", item_id, fn)
    return {"done": done, "failed": failed}
