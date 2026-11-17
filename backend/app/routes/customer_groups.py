"""Customers > Groups: named lists of leads, picked by hand (kind 'picked').

Rule groups (kind 'rule', filling themselves from a saved filter) are not built yet; a
rule group's members cannot be changed by hand, so the member routes refuse it.
Every query is scoped to the caller's tenant. A group of another tenant reads as 404.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.db.supabase import get_supabase
from app.routes.leads import _fetch_all, _in_scopes, require_leads_manage, require_leads_view

logger = logging.getLogger(__name__)

router = APIRouter()

DUPLICATE_NAME = "A group with this name already exists"


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name", mode="before")
    @classmethod
    def _trim(cls, v):
        return v.strip() if isinstance(v, str) else v


class LeadIdsIn(BaseModel):
    lead_ids: list[str] = Field(min_length=1, max_length=1000)


def _valid_ids(raw: list[str]) -> list[str]:
    """Distinct, well-formed lead ids in lowercase (the form PostgREST returns). Others are dropped."""
    seen: dict[str, None] = {}
    for item in raw:
        try:
            seen[str(UUID(str(item)))] = None
        except ValueError:
            continue
    return list(seen)


def _group_or_404(db, tenant_id: str, group_id: str) -> dict:
    res = (db.table("customer_groups").select("id,name,kind,created_at")
           .eq("id", group_id).eq("tenant_id", tenant_id).maybe_single().execute())
    if not (res and res.data):
        raise HTTPException(status_code=404, detail="Group not found")
    return res.data


def _name_taken(db, tenant_id: str, name: str, exclude_id: str | None = None) -> bool:
    """Case-insensitive, the same rule as the unique index on customer_groups."""
    wanted = name.strip().lower()
    rows = _fetch_all(lambda: db.table("customer_groups").select("id,name").eq("tenant_id", tenant_id))
    return any(str(r["id"]) != exclude_id and (r.get("name") or "").strip().lower() == wanted for r in rows)


def _live_lead_ids(db, tenant_id: str, lead_ids: list[str]) -> set[str]:
    """The ids that are leads of this tenant and not deleted."""
    found: set[str] = set()
    for scope in _in_scopes(lead_ids):
        rows = _fetch_all(lambda scope=scope: db.table("leads").select("id").eq("tenant_id", tenant_id)
                          .is_("deleted_at", "null").in_("id", scope))
        found.update(str(r["id"]) for r in rows)
    return found


def _member_counts(db, tenant_id: str, group_ids: list[str] | None = None) -> dict[str, int]:
    """group id -> number of members whose lead is not deleted."""
    wanted = set(group_ids) if group_ids is not None else None
    members = _fetch_all(lambda: db.table("customer_group_members").select("group_id,lead_id")
                         .eq("tenant_id", tenant_id), order_by=("group_id", "lead_id"))
    members = [m for m in members if wanted is None or str(m["group_id"]) in wanted]
    live = _live_lead_ids(db, tenant_id, sorted({str(m["lead_id"]) for m in members}))
    counts: dict[str, int] = {}
    for m in members:
        if str(m["lead_id"]) in live:
            gid = str(m["group_id"])
            counts[gid] = counts.get(gid, 0) + 1
    return counts


def _shape(row: dict, member_count: int) -> dict:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "kind": row.get("kind") or "picked",
        "member_count": member_count,
        "created_at": row.get("created_at"),
    }


@router.get("")
def list_groups(ctx: dict = Depends(require_leads_view)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    rows = _fetch_all(lambda: db.table("customer_groups").select("id,name,kind,created_at")
                      .eq("tenant_id", tenant_id).order("created_at", desc=True))
    counts = _member_counts(db, tenant_id, [str(r["id"]) for r in rows])
    return [_shape(r, counts.get(str(r["id"]), 0)) for r in rows]


@router.post("")
def create_group(body: GroupIn, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    if _name_taken(db, tenant_id, body.name):
        raise HTTPException(status_code=409, detail=DUPLICATE_NAME)
    try:
        res = db.table("customer_groups").insert({
            "tenant_id": tenant_id,
            "name": body.name,
            "kind": "picked",
            "created_by": ctx.get("user_id"),
        }).execute()
    except Exception as e:
        if "23505" in str(e):
            raise HTTPException(status_code=409, detail=DUPLICATE_NAME)
        raise
    return _shape(res.data[0], 0)


@router.patch("/{group_id}")
def rename_group(group_id: UUID, body: GroupIn, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    gid = str(group_id)
    group = _group_or_404(db, tenant_id, gid)
    if _name_taken(db, tenant_id, body.name, exclude_id=gid):
        raise HTTPException(status_code=409, detail=DUPLICATE_NAME)
    try:
        db.table("customer_groups").update({
            "name": body.name,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", gid).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        if "23505" in str(e):
            raise HTTPException(status_code=409, detail=DUPLICATE_NAME)
        raise
    return _shape({**group, "name": body.name}, _member_counts(db, tenant_id, [gid]).get(gid, 0))


@router.delete("/{group_id}")
def delete_group(group_id: UUID, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    gid = str(group_id)
    _group_or_404(db, tenant_id, gid)
    # customer_group_members rows go with it (ON DELETE CASCADE).
    db.table("customer_groups").delete().eq("id", gid).eq("tenant_id", tenant_id).execute()
    return {"deleted": True}


@router.post("/{group_id}/members")
def add_members(group_id: UUID, body: LeadIdsIn, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    gid = str(group_id)
    group = _group_or_404(db, tenant_id, gid)
    if group.get("kind") == "rule":
        raise HTTPException(status_code=400, detail="This group fills itself")
    accepted = sorted(_live_lead_ids(db, tenant_id, _valid_ids(body.lead_ids)))
    if accepted:
        db.table("customer_group_members").upsert(
            [{"group_id": gid, "lead_id": lid, "tenant_id": tenant_id, "added_by": ctx.get("user_id")}
             for lid in accepted],
            on_conflict="group_id,lead_id",
            ignore_duplicates=True,
        ).execute()
    return {"added": len(accepted)}


@router.delete("/{group_id}/members")
def remove_members(group_id: UUID, body: LeadIdsIn, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    gid = str(group_id)
    _group_or_404(db, tenant_id, gid)
    ids = _valid_ids(body.lead_ids)
    removed = 0
    if ids:
        res = (db.table("customer_group_members").delete()
               .eq("group_id", gid).eq("tenant_id", tenant_id).in_("lead_id", ids).execute())
        removed = len(res.data or [])
    return {"removed": removed}
