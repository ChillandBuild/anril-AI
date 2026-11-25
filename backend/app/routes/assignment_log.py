import csv
import io
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, require_any_permission
from app.services.call_rules import phone_mask_for
from app.services.call_teams import caller_scope
from app.services.download_gate import log_download, require_download
from app.services.reports_common import phone_cell

logger = logging.getLogger(__name__)
router = APIRouter()

_ASSIGN_EVENTS = ("assigned", "reassigned")
_BY_HAND_METHODS = ("admin",)  # a person picked the telecaller (lead page or bulk assign), not the system
_CSV_ROW_CAP = 10000
_PAGE = 1000  # the API hands back at most 1000 rows per answer


def _allowed_callers(db, ctx: dict) -> set[str] | None:
    """None = every telecaller. A set = only these callers.id values: a Team leader sees their team (and
    themself); a telecaller (no team.view) sees only themself."""
    if not _has_permission(ctx, "team.view"):
        return {str(ctx["caller_id"])} if ctx.get("caller_id") else set()
    return caller_scope(db, ctx)


def _rows(db, tenant_id: str, *, caller_id: str | None, segment: str | None,
          from_date: str | None, to_date: str | None, by_hand: bool = False,
          allowed: set[str] | None = None, limit: int, offset: int, with_count: bool = False):
    q = (
        db.table("lead_stage_events")
        .select("id,lead_id,to_segment,event_type,metadata,created_at",
                count="exact" if with_count else None)
        .eq("tenant_id", tenant_id)
        .in_("event_type", list(_ASSIGN_EVENTS))
    )
    if allowed is not None:
        q = q.in_("metadata->>caller_id", sorted(allowed))
    if caller_id:
        q = q.eq("metadata->>caller_id", caller_id)
    if segment:
        q = q.eq("to_segment", segment)
    if by_hand:
        q = q.in_("metadata->>method", list(_BY_HAND_METHODS))
    if from_date:
        q = q.gte("created_at", from_date)
    if to_date:
        q = q.lte("created_at", to_date)
    q = q.order("created_at", desc=True).order("id").range(offset, offset + limit - 1)
    return q.execute()


def _all_rows(db, tenant_id: str, **filters) -> list[dict]:
    """Every matching event (newest first, up to the cap), a page at a time past the 1000-row API cap."""
    out: list[dict] = []
    while len(out) < _CSV_ROW_CAP:
        page = _rows(db, tenant_id, limit=_PAGE, offset=len(out), **filters).data or []
        out.extend(page)
        if len(page) < _PAGE:
            break
    return out[:_CSV_ROW_CAP]


def _hydrate(db, tenant_id: str, events: list[dict], mask=None) -> list[dict]:
    """Attach lead name/phone to each assignment event. `mask` hides numbers the way the leads list does."""
    lead_ids = list({e["lead_id"] for e in events if e.get("lead_id")})
    leads_by_id: dict[str, dict] = {}
    for i in range(0, len(lead_ids), 200):  # chunked: a long id list would overflow the request line
        res = (
            db.table("leads")
            .select("id,name,phone")
            .eq("tenant_id", tenant_id)
            .in_("id", lead_ids[i:i + 200])
            .execute()
        )
        leads_by_id.update({l["id"]: l for l in (res.data or [])})

    out = []
    for e in events:
        meta = e.get("metadata") or {}
        lead = leads_by_id.get(e.get("lead_id"), {})
        phone = lead.get("phone")
        out.append({
            "id": e["id"],
            "lead_id": e.get("lead_id"),
            "lead_name": lead.get("name"),
            "lead_phone": mask(phone) if (mask and phone) else phone,
            "segment": e.get("to_segment"),
            "event_type": e.get("event_type"),
            "caller_id": meta.get("caller_id"),
            "caller_name": meta.get("caller_name"),
            "prev_caller_name": meta.get("prev_caller_name"),
            "reason": meta.get("reason"),
            "method": meta.get("method"),
            "score": meta.get("score"),
            "matched_segments": meta.get("matched_segments"),
            "created_at": e.get("created_at"),
        })
    return out


@router.get("")
async def list_assignment_log(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    caller_id: str | None = Query(None),
    segment: str | None = Query(None, pattern="^[ABCD]$"),
    from_date: str | None = Query(None, max_length=40, description="ISO timestamp lower bound"),
    to_date: str | None = Query(None, max_length=40, description="ISO timestamp upper bound"),
    by_hand: bool = Query(False, description="Only leads a person assigned by hand"),
    format: str | None = Query(None),
    ctx: dict = Depends(require_any_permission("team.view", "telecalling.dialer")),
):
    """Proof feed of every auto/manual assignment + reassignment for the tenant. The owner and anyone with
    team.view see every telecaller; a Team leader sees their team; a telecaller sees only their own rows.
    Phones are hidden for a telecaller when the business hides numbers."""
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    allowed = _allowed_callers(db, ctx)
    mask = phone_mask_for(db, tenant_id, ctx)
    filters = dict(caller_id=caller_id, segment=segment, from_date=from_date, to_date=to_date,
                   by_hand=by_hand, allowed=allowed)
    if allowed is not None and caller_id and caller_id not in allowed:
        # Asking for someone outside your scope returns nothing, never their rows.
        allowed = set()
        filters["allowed"] = allowed
    if format == "csv":
        require_download(ctx)  # owner always passes; the rule is kept in one place
        events = [] if allowed == set() else _all_rows(db, tenant_id, **filters)
        items = _hydrate(db, tenant_id, events, mask)
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            "created_at", "lead_name", "lead_phone", "segment", "event_type",
            "caller_name", "prev_caller_name", "reason", "method", "score",
        ])
        writer.writeheader()
        for it in items:
            writer.writerow({k: (phone_cell(it.get(k)) if k == "lead_phone" else it.get(k)) for k in writer.fieldnames})
        output.seek(0)
        log_download(db, ctx, list_name="Assignment log", row_count=len(items), filters={
            "caller_id": caller_id, "segment": segment, "from_date": from_date, "to_date": to_date,
            "by_hand": by_hand,
        })
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=assignment-log.csv"},
        )

    if allowed == set():
        return {"data": [], "meta": {"total": 0, "page": page, "limit": limit}}
    offset = (page - 1) * limit
    res = _rows(db, tenant_id, limit=limit, offset=offset, with_count=True, **filters)
    items = _hydrate(db, tenant_id, res.data or [], mask)
    return {
        "data": items,
        "meta": {"total": res.count or 0, "page": page, "limit": limit},
    }


@router.get("/summary")
async def assignment_summary(ctx: dict = Depends(require_any_permission("team.view", "telecalling.dialer"))):
    """Today's assignment counts overall + per caller + per segment (same people as the list)."""
    db, tenant_id = get_supabase(), ctx["tenant_id"]
    allowed = _allowed_callers(db, ctx)
    from app.services.reports_common import today_ist
    today = f"{today_ist().isoformat()}T00:00:00+05:30"   # India midnight, not UTC (05:30 IST)
    rows: list[dict] = []
    if allowed != set():
        while True:
            q = (
                db.table("lead_stage_events")
                .select("id,to_segment,metadata")
                .eq("tenant_id", tenant_id)
                .in_("event_type", list(_ASSIGN_EVENTS))
                .gte("created_at", today)
            )
            if allowed is not None:
                q = q.in_("metadata->>caller_id", sorted(allowed))
            page = q.order("id").range(len(rows), len(rows) + _PAGE - 1).execute().data or []
            rows.extend(page)
            if len(page) < _PAGE:
                break
    by_caller: dict[str, dict] = {}
    by_segment: dict[str, int] = {}
    for r in rows:
        meta = r.get("metadata") or {}
        cid = meta.get("caller_id") or "unknown"
        name = meta.get("caller_name") or "Unknown"
        if cid not in by_caller:
            by_caller[cid] = {"caller_name": name, "count": 0}
        by_caller[cid]["count"] += 1
        seg = r.get("to_segment") or "?"
        by_segment[seg] = by_segment.get(seg, 0) + 1
    return {
        "assigned_today": len(rows),
        "by_caller": by_caller,
        "by_segment": by_segment,
    }
