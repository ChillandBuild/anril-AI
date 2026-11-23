"""v9.2 Batch H. Customers > Feedback: switch, star message, results, "Mark fixed".

Base permission leads.view; "Mark fixed" needs leads.manage; the switch and the star message need
settings.manage (owner passes everything). The star message also needs templates.manage, like the
booking messages do.
"""
import logging
import unicodedata
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, require_any_permission, require_permission
from app.services import customer_feedback as fb
from app.services.actor import actor_name

logger = logging.getLogger(__name__)
router = APIRouter()

view = require_permission("leads.view")
manage = require_permission("leads.manage")
settings_manage = require_any_permission("settings.manage")

IST = timezone(timedelta(hours=5, minutes=30))
MAX_DAYS = 366
SELECT = ("id, lead_id, phone, kind, status, staff_name, asked_at, stars, answered_at, reason, reason_at, "
          "fixed_by_name, review_link_sent")

_STOP = {
    "the", "and", "was", "were", "for", "with", "that", "this", "have", "had", "has", "not", "but", "are",
    "very", "too", "they", "them", "you", "your", "our", "its", "it's", "from", "when", "then", "than",
    "been", "get", "got", "did", "didn", "don", "can", "could", "would", "will", "just", "all", "any",
    "one", "out", "who", "what", "why", "how", "also", "after", "before", "again", "about", "into",
    "me", "my", "we", "is", "in", "on", "of", "to", "at", "it", "a", "an", "i", "so", "be", "no", "by",
}


class SettingsBody(BaseModel):
    on: bool
    offer: str | None = None


def _day(value: str | None, default: date, name: str) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"'{name}' should look like 2026-11-23.")


def _words(reason: str) -> set[str]:
    """Plain word list of one reason: letters, marks and digits only (Tamil vowel signs stay attached)."""
    out, cur = set(), []
    for ch in (reason or "").lower() + " ":
        if unicodedata.category(ch)[0] in "LMN":
            cur.append(ch)
            continue
        if cur:
            w = "".join(cur)
            if len(w) >= 3 and w not in _STOP and not w.isdigit():
                out.add(w)
            cur = []
    return out


def group_reasons(reasons: list[str], top: int = 8) -> list[dict]:
    """Simple word grouping: each word counted once per reason, most common first."""
    counts: Counter = Counter()
    for r in reasons:
        counts.update(_words(r))
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"text": w, "count": n} for w, n in ranked[:top]]


def _names(db, tenant_id: str, rows: list[dict]) -> dict:
    ids = list({r["lead_id"] for r in rows if r.get("lead_id")})
    if not ids:
        return {}
    got = db.table("leads").select("id, name").eq("tenant_id", tenant_id).in_("id", ids).execute().data or []
    return {str(r["id"]): r.get("name") for r in got}


def _shape(r: dict, names: dict) -> dict:
    return {"id": r["id"], "lead_id": r.get("lead_id"), "name": names.get(str(r.get("lead_id"))) or None,
            "phone": r.get("phone"), "stars": r.get("stars"), "reason": r.get("reason"),
            "staff_name": r.get("staff_name"), "asked_at": r.get("asked_at"),
            "answered_at": r.get("answered_at"), "status": r.get("status"), "kind": r.get("kind"),
            "fixed_by_name": r.get("fixed_by_name"), "review_link_sent": bool(r.get("review_link_sent"))}


@router.get("/settings")
async def get_settings(ctx: dict = Depends(view)):
    tenant_id = ctx["tenant_id"]
    return {"on": fb.is_on(tenant_id), "offer": fb.offer_text(tenant_id), "review_link": fb.review_link(tenant_id),
            "template_status": fb.template_status(get_supabase(), tenant_id),
            "cost_per_message_rupees": fb.COST_PER_MESSAGE_RUPEES}


@router.put("/settings")
async def put_settings(body: SettingsBody, ctx: dict = Depends(settings_manage)):
    tenant_id = ctx["tenant_id"]
    try:
        fb.save_settings(get_supabase(), tenant_id, body.on, body.offer)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await get_settings(ctx)


@router.post("/setup-template")
async def setup_template(ctx: dict = Depends(settings_manage)):
    if not _has_permission(ctx, "templates.manage"):
        raise HTTPException(status_code=403, detail="Permission required: templates.manage")
    return await fb.submit_template(get_supabase(), ctx["tenant_id"], ctx)


@router.get("")
@router.get("/")
async def results(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    ctx: dict = Depends(view),
):
    """Stars for people asked between `from` and `to` (IST days, `to` included). Default: last 30 days.
    "Unhappy and still open" ignores the dates: an open complaint stays until someone fixes it."""
    tenant_id = ctx["tenant_id"]
    today = datetime.now(IST).date()
    end = _day(to, today, "to")
    start = _day(from_, end - timedelta(days=29), "from")
    if start > end:
        raise HTTPException(status_code=400, detail="The 'from' day is after the 'to' day.")
    if (end - start).days >= MAX_DAYS:
        raise HTTPException(status_code=400, detail="Pick a period of one year or less.")
    lo = datetime(start.year, start.month, start.day, tzinfo=IST).astimezone(timezone.utc).isoformat()
    hi = datetime(end.year, end.month, end.day, tzinfo=IST) + timedelta(days=1)
    hi = hi.astimezone(timezone.utc).isoformat()
    empty = {"average": None, "answered_pct": 0, "asked": 0, "answered": 0, "unhappy": 0, "google_reviews": 0,
             "unhappy_open": [], "reasons": [], "unhappy_reasons": [], "by_staff": [], "recent": []}
    db = get_supabase()
    try:
        rows = (db.table("customer_feedback").select(SELECT).eq("tenant_id", tenant_id)
                .gte("asked_at", lo).lt("asked_at", hi).neq("status", "failed").limit(5000).execute()).data or []
        open_rows = (db.table("customer_feedback").select(SELECT).eq("tenant_id", tenant_id)
                     .eq("status", "answered").lte("stars", fb.UNHAPPY_MAX)
                     .order("answered_at", desc=True).limit(200).execute()).data or []
    except Exception as e:
        logger.warning("feedback results: table not readable: %s", e)
        return empty
    if ctx.get("role") == "caller":  # a telecaller sees only the people given to them, as on the Customers list
        mine = _assigned_to_caller(db, ctx, [r.get("lead_id") for r in rows + open_rows])
        rows = [r for r in rows if str(r.get("lead_id")) in mine]
        open_rows = [r for r in open_rows if str(r.get("lead_id")) in mine]
    answered = [r for r in rows if r.get("stars")]
    recent = sorted(answered, key=lambda r: r.get("answered_at") or "", reverse=True)[:20]
    try:
        names = _names(db, tenant_id, open_rows + recent)
    except Exception as e:
        logger.warning("feedback results: names not read: %s", e)
        names = {}
    per_staff: dict[str, list[int]] = {}
    for r in answered:
        if r.get("staff_name"):
            per_staff.setdefault(r["staff_name"], []).append(int(r["stars"]))
    return {
        "average": round(sum(int(r["stars"]) for r in answered) / len(answered), 2) if answered else None,
        "answered_pct": round(len(answered) * 100 / len(rows), 1) if rows else 0,
        "asked": len(rows),
        "answered": len(answered),
        "unhappy": sum(1 for r in answered if int(r["stars"]) <= fb.UNHAPPY_MAX),
        "google_reviews": sum(1 for r in answered if r.get("review_link_sent")),
        "unhappy_open": [{k: v for k, v in _shape(r, names).items()
                          if k in ("id", "lead_id", "name", "phone", "stars", "reason", "staff_name", "asked_at")}
                         for r in open_rows],
        "reasons": group_reasons([r["reason"] for r in answered if (r.get("reason") or "").strip()]),
        # Why people were unhappy: the same word grouping over the 1-3 star reasons only.
        "unhappy_reasons": group_reasons([r["reason"] for r in answered
                                          if int(r["stars"]) <= fb.UNHAPPY_MAX and (r.get("reason") or "").strip()], top=6),
        "by_staff": sorted(({"staff_name": n, "avg": round(sum(v) / len(v), 2), "count": len(v)}
                            for n, v in per_staff.items()), key=lambda s: (-s["avg"], s["staff_name"])),
        "recent": [_shape(r, names) for r in recent],
    }


def _assigned_to_caller(db, ctx: dict, lead_ids: list) -> set[str]:
    caller_id = ctx.get("caller_id")
    ids = sorted({str(i) for i in lead_ids if i})
    if not caller_id or not ids:
        return set()
    mine: set[str] = set()
    for i in range(0, len(ids), 200):
        got = (db.table("leads").select("id").eq("tenant_id", ctx["tenant_id"]).eq("assigned_to", caller_id)
               .in_("id", ids[i:i + 200]).execute().data or [])
        mine |= {str(r["id"]) for r in got}
    return mine


@router.post("/{feedback_id}/fixed")
async def mark_fixed(feedback_id: str, ctx: dict = Depends(manage)):
    tenant_id = ctx["tenant_id"]
    try:
        uuid.UUID(feedback_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="That feedback was not found.")
    db = get_supabase()
    try:
        rows = (db.table("customer_feedback").select("id, status, stars").eq("id", feedback_id)
                .eq("tenant_id", tenant_id).limit(1).execute()).data or []
    except Exception as e:
        logger.warning("feedback fixed: table not readable: %s", e)
        rows = []
    if not rows:
        raise HTTPException(status_code=404, detail="That feedback was not found.")
    if rows[0].get("status") == "fixed":
        return {"id": feedback_id, "status": "fixed"}
    if not rows[0].get("stars"):
        raise HTTPException(status_code=400, detail="This person has not given stars yet.")
    by_name = actor_name(db, ctx)
    db.table("customer_feedback").update({
        "status": "fixed", "fixed_by": ctx.get("user_id"), "fixed_by_name": by_name,
        "fixed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", feedback_id).eq("tenant_id", tenant_id).execute()
    return {"id": feedback_id, "status": "fixed", "fixed_by_name": by_name}
