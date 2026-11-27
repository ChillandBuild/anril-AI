import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_permission
from app.services import reach_audience
from app.services.delivery_status import nearest_status, parse_ts as _parse_ts

logger = logging.getLogger(__name__)
require_outbound_read = require_permission("outbound_leads.view")
require_outbound_manage = require_permission("outbound_leads.manage")

router = APIRouter(dependencies=[Depends(require_outbound_read)])


class TagCreate(BaseModel):
    name: str
    color: str = "#6D28D9"


class TagUpdate(BaseModel):
    name: str | None = None
    color: str | None = None


@router.get("/")
def list_tags(tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    tags = db.table("broadcast_tags").select("*").eq("tenant_id", tenant_id).order("created_at", desc=False).execute()
    return {"data": tags.data or []}


@router.post("/")
def create_tag(
    body: TagCreate,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    db = get_supabase()
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tag name is required")
    try:
        result = db.table("broadcast_tags").insert({
            "tenant_id": tenant_id,
            "name": name,
            "color": body.color,
        }).execute()
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Tag '{name}' already exists")
        raise HTTPException(status_code=500, detail=str(e))
    return {"data": result.data[0] if result.data else None}


@router.patch("/{tag_id}")
def update_tag(
    tag_id: str,
    body: TagUpdate,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    db = get_supabase()
    update: dict = {}
    if body.name is not None:
        update["name"] = body.name.strip()
    if body.color is not None:
        update["color"] = body.color
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    result = db.table("broadcast_tags").update(update).eq("id", tag_id).eq("tenant_id", tenant_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"data": result.data[0]}


@router.delete("/{tag_id}")
def delete_tag(
    tag_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    db = get_supabase()
    result = db.table("broadcast_tags").delete().eq("id", tag_id).eq("tenant_id", tenant_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"deleted": True}


@router.get("/stats")
def get_tag_stats(tenant_id: str = Depends(get_tenant_id)):
    """Per-tag stats: total_sent, hot, warm, cold, disqualified, opted_out, failed.

    Each recipient row is one send EVENT and is classified independently. Delivery
    success/failure is attributed PER BROADCAST from messages.delivery_status within
    the send's time window — not from a sticky per-lead flag — so a number that fails
    one campaign and succeeds in a later one is counted correctly in each. This is the
    same authoritative signal Broadcast History uses. Outcomes partition total_sent
    exactly: hot + warm + cold + disqualified + opted_out + failed == total_sent.
    """
    db = get_supabase()

    tags = db.table("broadcast_tags").select("id").eq("tenant_id", tenant_id).execute()
    tag_ids = [t["id"] for t in (tags.data or [])]
    if not tag_ids:
        return {"data": []}

    # Optional broadcast_recipients columns (migration compatibility)
    has_br_opted_out_at = True
    try:
        db.table("broadcast_recipients").select("opted_out_at").limit(1).execute()
    except Exception:
        has_br_opted_out_at = False
    has_fail_reason = True
    try:
        db.table("broadcast_recipients").select("fail_reason").limit(1).execute()
    except Exception:
        has_fail_reason = False

    select_cols = "tag_id, lead_id, send_status, created_at"
    if has_br_opted_out_at:
        select_cols += ", opted_out_at"
    if has_fail_reason:
        select_cols += ", fail_reason"
    recipients = (
        db.table("broadcast_recipients")
        .select(select_cols)
        .eq("tenant_id", tenant_id)
        .in_("tag_id", tag_ids)
        .execute()
        .data
        or []
    )

    lead_ids = list({r["lead_id"] for r in recipients if r.get("lead_id")})

    # Current lead state: segment + opt-out (with timestamp for per-send scoping)
    lead_segment: dict[str, str] = {}
    lead_opted_out_at: dict[str, datetime] = {}
    for i in range(0, len(lead_ids), 200):
        chunk = lead_ids[i:i + 200]
        resp = (
            db.table("leads")
            .select("id, segment, opted_out, opted_out_at")
            .eq("tenant_id", tenant_id)
            .in_("id", chunk)
            .execute()
        )
        for l in (resp.data or []):
            lead_segment[l["id"]] = l.get("segment") or "C"
            opted_at = _parse_ts(l.get("opted_out_at"))
            if l.get("opted_out") and opted_at:
                lead_opted_out_at[l["id"]] = opted_at

    # If the per-broadcast opt-out stamp was missed, attribute the global
    # fallback only to the single latest send at/before the opt-out.
    owning_send_at: dict[str, datetime] = {}
    oo_lead_ids = list(lead_opted_out_at.keys())
    for i in range(0, len(oo_lead_ids), 200):
        chunk = oo_lead_ids[i:i + 200]
        resp = (
            db.table("broadcast_recipients")
            .select("lead_id, created_at")
            .eq("tenant_id", tenant_id)
            .in_("lead_id", chunk)
            .execute()
        )
        for row in (resp.data or []):
            lid = row.get("lead_id")
            sent_at = _parse_ts(row.get("created_at"))
            opted_at = lead_opted_out_at.get(lid)
            if not lid or not sent_at or not opted_at or sent_at > opted_at:
                continue
            if lid not in owning_send_at or sent_at > owning_send_at[lid]:
                owning_send_at[lid] = sent_at

    # Outbound delivery statuses per lead, for per-send window matching
    msgs_by_lead: dict[str, list[tuple[datetime, str]]] = {}
    for i in range(0, len(lead_ids), 200):
        chunk = lead_ids[i:i + 200]
        resp = (
            db.table("messages")
            .select("lead_id, delivery_status, created_at")
            .eq("tenant_id", tenant_id)
            .eq("direction", "outbound")
            .in_("lead_id", chunk)
            .execute()
        )
        for m in (resp.data or []):
            lid = m.get("lead_id")
            status = m.get("delivery_status")
            ts = _parse_ts(m.get("created_at"))
            if lid and status and ts:
                msgs_by_lead.setdefault(lid, []).append((ts, status))

    def delivery_failed(lead_id: str, sent_at: datetime | None) -> bool:
        """True if THIS send bounced — attributed by the message nearest the send,
        so an adjacent broadcast's status can't mask it (services/delivery_status)."""
        if not sent_at:
            return False
        return nearest_status(msgs_by_lead.get(lead_id, []), sent_at) == "failed"

    def new_counter() -> dict[str, int]:
        return {tid: 0 for tid in tag_ids}

    sent_c = new_counter()
    hot_c = new_counter()
    warm_c = new_counter()
    cold_c = new_counter()
    dq_c = new_counter()
    oo_c = new_counter()
    failed_c = new_counter()

    for r in recipients:
        tid = r.get("tag_id")
        if not tid:
            continue
        if (r.get("send_status") or "") == "opted_out_skip" and (r.get("fail_reason") or "") in reach_audience.SKIP_REASONS:
            continue  # skipped on purpose at send time (Reach weekly limit / blocked): not an attempt, not an opt-out
        sent_c[tid] += 1  # every attempt is one "sent" (the denominator)

        lid = r.get("lead_id")
        sent_at = _parse_ts(r.get("created_at"))

        # 1. Send-time (API) failure — message never left
        if (r.get("send_status") or "") in ("failed", "rejected", "delivery_failed"):
            failed_c[tid] += 1
            continue

        # 2. Opted out — per-broadcast flag, or lead opt-out scoped to sends at/before it
        opted = False
        if r.get("opted_out_at"):
            opted = True
        elif (r.get("send_status") or "") == "opted_out_skip":
            opted = (r.get("fail_reason") or "opted_out") != "negative_reply_excluded"
        elif lid and sent_at and owning_send_at.get(lid) == sent_at:
            opted = True
        if opted:
            oo_c[tid] += 1
            continue

        # 3. Delivery failure for THIS send (per-broadcast, not sticky)
        if lid and delivery_failed(lid, sent_at):
            failed_c[tid] += 1
            continue

        # 4. Delivered — bucket by the lead's current segment
        seg = lead_segment.get(lid, "C") if lid else "C"
        if seg == "A":
            hot_c[tid] += 1
        elif seg == "B":
            warm_c[tid] += 1
        elif seg == "D":
            dq_c[tid] += 1
        else:
            cold_c[tid] += 1

    data = [
        {
            "tag_id": tid,
            "total_sent": sent_c[tid],
            "hot": hot_c[tid],
            "warm": warm_c[tid],
            "cold": cold_c[tid],
            "disqualified": dq_c[tid],
            "opted_out": oo_c[tid],
            "failed": failed_c[tid],
        }
        for tid in tag_ids
    ]
    return {"data": data}
