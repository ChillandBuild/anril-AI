import csv
import io
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_owner_tenant_id, require_owner
from app.services.download_gate import log_download, require_download

logger = logging.getLogger(__name__)
router = APIRouter()

_ASSIGN_EVENTS = ("assigned", "reassigned")


def _rows(tenant_id: str, *, caller_id: str | None, segment: str | None,
          from_date: str | None, to_date: str | None, limit: int, offset: int,
          with_count: bool = False):
    db = get_supabase()
    q = (
        db.table("lead_stage_events")
        .select("id,lead_id,to_segment,event_type,metadata,created_at",
                count="exact" if with_count else None)
        .eq("tenant_id", tenant_id)
        .in_("event_type", list(_ASSIGN_EVENTS))
    )
    if caller_id:
        q = q.eq("metadata->>caller_id", caller_id)
    if segment:
        q = q.eq("to_segment", segment)
    if from_date:
        q = q.gte("created_at", from_date)
    if to_date:
        q = q.lte("created_at", to_date)
    q = q.order("created_at", desc=True).range(offset, offset + limit - 1)
    return q.execute()


def _hydrate(tenant_id: str, events: list[dict]) -> list[dict]:
    """Attach lead name/phone to each assignment event."""
    db = get_supabase()
    lead_ids = list({e["lead_id"] for e in events if e.get("lead_id")})
    leads_by_id: dict[str, dict] = {}
    if lead_ids:
        res = (
            db.table("leads")
            .select("id,name,phone")
            .eq("tenant_id", tenant_id)
            .in_("id", lead_ids)
            .execute()
        )
        leads_by_id = {l["id"]: l for l in (res.data or [])}

    out = []
    for e in events:
        meta = e.get("metadata") or {}
        lead = leads_by_id.get(e.get("lead_id"), {})
        out.append({
            "id": e["id"],
            "lead_id": e.get("lead_id"),
            "lead_name": lead.get("name"),
            "lead_phone": lead.get("phone"),
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
    from_date: str | None = Query(None, description="ISO timestamp lower bound"),
    to_date: str | None = Query(None, description="ISO timestamp upper bound"),
    format: str | None = Query(None),
    ctx: dict = Depends(require_owner),
):
    """Proof feed of every auto/manual assignment + reassignment for the tenant."""
    tenant_id = ctx["tenant_id"]
    if format == "csv":
        require_download(ctx)  # owner always passes; the rule is kept in one place
        res = _rows(tenant_id, caller_id=caller_id, segment=segment,
                    from_date=from_date, to_date=to_date, limit=10000, offset=0)
        items = _hydrate(tenant_id, res.data or [])
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            "created_at", "lead_name", "lead_phone", "segment", "event_type",
            "caller_name", "prev_caller_name", "reason", "method", "score",
        ])
        writer.writeheader()
        for it in items:
            writer.writerow({k: it.get(k) for k in writer.fieldnames})
        output.seek(0)
        log_download(get_supabase(), ctx, list_name="Assignment log", row_count=len(items), filters={
            "caller_id": caller_id, "segment": segment, "from_date": from_date, "to_date": to_date,
        })
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=assignment-log.csv"},
        )

    offset = (page - 1) * limit
    res = _rows(tenant_id, caller_id=caller_id, segment=segment,
                from_date=from_date, to_date=to_date, limit=limit, offset=offset,
                with_count=True)
    items = _hydrate(tenant_id, res.data or [])
    return {
        "data": items,
        "meta": {"total": res.count or 0, "page": page, "limit": limit},
    }


@router.get("/summary")
async def assignment_summary(tenant_id: str = Depends(get_owner_tenant_id)):
    """Today's assignment counts overall + per caller + per segment."""
    from datetime import datetime, timezone
    db = get_supabase()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00+00:00")
    res = (
        db.table("lead_stage_events")
        .select("to_segment,metadata")
        .eq("tenant_id", tenant_id)
        .in_("event_type", list(_ASSIGN_EVENTS))
        .gte("created_at", today)
        .execute()
    )
    rows = res.data or []
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
