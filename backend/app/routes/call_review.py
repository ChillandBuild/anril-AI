"""Call Review — the admin page for reviewing a telecaller's calls, scores and notes."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.routes.calls import CALL_CARD_FIELDS
from app.services.assignment import get_telecalling_config
from app.services.call_evaluation import strip_evaluation
from app.services.call_review import summarize_leads
from app.services.call_transcript import mask_transcripts

router = APIRouter()

# Reviewing other people's calls is a manager's job; owners always pass.
require_reviewer = require_permission("team.manage")

_PAGE = 1000
_MAX_ROWS = 20000
_ID_CHUNK = 200


def _parse_range(start: str, end: str) -> tuple[str, str]:
    try:
        s, e = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=422, detail="start and end must be ISO dates, e.g. 2026-10-01T00:00:00+05:30")
    if e <= s:
        raise HTTPException(status_code=422, detail="end must be after start")
    return s.isoformat(), e.isoformat()


def _paged(build) -> list[dict]:
    rows: list[dict] = []
    while len(rows) < _MAX_ROWS:
        page = build().range(len(rows), len(rows) + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            break
    return rows


@router.get("/leads")
async def review_leads(
    start: str = Query(..., description="Range start, ISO datetime with offset"),
    end: str = Query(..., description="Range end (exclusive), ISO datetime with offset"),
    caller_id: UUID | None = Query(None, description="Omit for every telecaller"),
    ctx: dict = Depends(require_reviewer),
):
    """Leads the telecaller owns, called or noted in the range, each with call and note totals."""
    start_iso, end_iso = _parse_range(start, end)
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    cid = str(caller_id) if caller_id else None

    def calls_query():
        q = (
            db.table("call_logs")
            .select("id,lead_id,caller_id,created_at,status,manual_status,duration_seconds,score,score_status,call_group,provider")
            .eq("tenant_id", tenant_id)
            .gte("created_at", start_iso)
            .lt("created_at", end_iso)
            .not_.is_("lead_id", "null")
        )
        return (q.eq("caller_id", cid) if cid else q).order("created_at")

    def notes_query():
        q = (
            db.table("lead_notes")
            .select("id,lead_id,caller_id,created_at")
            .eq("tenant_id", tenant_id)
            .gte("created_at", start_iso)
            .lt("created_at", end_iso)
            # Anril writes an "AI Summary:" note after each scored call; only people's notes count here.
            .not_.like("content", "AI Summary:%")
        )
        return (q.eq("caller_id", cid) if cid else q).order("created_at")

    calls = _paged(calls_query)
    notes = _paged(notes_query)

    lead_fields = "id,name,phone,segment,score,assigned_to"
    assigned: list[dict] = []
    if cid:
        assigned = _paged(
            lambda: db.table("leads").select(lead_fields)
            .eq("tenant_id", tenant_id).eq("assigned_to", cid).is_("deleted_at", "null").order("created_at")
        )
    assigned_ids = {str(l["id"]) for l in assigned}

    touched = sorted({str(r["lead_id"]) for r in calls + notes if r.get("lead_id")} - assigned_ids)
    leads = list(assigned)
    for i in range(0, len(touched), _ID_CHUNK):
        chunk = touched[i:i + _ID_CHUNK]
        leads += (
            db.table("leads").select(lead_fields)
            .eq("tenant_id", tenant_id).in_("id", chunk).is_("deleted_at", "null")
            .execute().data or []
        )

    rows = summarize_leads(calls, notes, leads, assigned_ids)
    if get_telecalling_config(tenant_id, db=db).get("calling_provider", "telecmi") == "sim_basic":
        # SIM clients get no evaluation fields (same rule as strip_evaluation).
        for r in rows:
            r.update(scored=0, score_sum=0, avg_score=None, early_exits=0, needs_review=False)
            if r["last_call"]:
                r["last_call"].update(score=None, score_status=None, call_group=None)
    return {"data": rows, "truncated": len(calls) >= _MAX_ROWS or len(notes) >= _MAX_ROWS}


@router.get("/leads/{lead_id}/calls")
async def review_lead_calls(
    lead_id: UUID,
    start: str = Query(...),
    end: str = Query(...),
    caller_id: UUID | None = Query(None),
    ctx: dict = Depends(require_reviewer),
):
    """Full call cards (recording, score, summary, transcript preview) for one lead in the range."""
    start_iso, end_iso = _parse_range(start, end)
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    q = (
        db.table("call_logs")
        .select(f"{CALL_CARD_FIELDS},callers(name)")
        .eq("tenant_id", tenant_id)
        .eq("lead_id", str(lead_id))
        .gte("created_at", start_iso)
        .lt("created_at", end_iso)
    )
    if caller_id:
        q = q.eq("caller_id", str(caller_id))
    rows = q.order("created_at", desc=True).limit(50).execute().data or []
    is_sim = get_telecalling_config(tenant_id, db=db).get("calling_provider", "telecmi") == "sim_basic"
    return {"data": strip_evaluation(mask_transcripts(rows), is_sim, keep_report=True)}
