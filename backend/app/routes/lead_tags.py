"""Customers > tags. Plain words on a person; see services/lead_tags.py for the rules."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services import lead_tags

router = APIRouter()

require_leads_view = require_permission("leads.view")
require_leads_manage = require_permission("leads.manage")


class TagChange(BaseModel):
    lead_ids: list[str] = Field(min_length=1, max_length=lead_tags.MAX_LEADS_PER_CALL)
    tags: list[str] = Field(min_length=1, max_length=20)


@router.get("")
def list_tags(ctx: dict = Depends(require_leads_view)):
    """Every tag in use: {"tags": [{"tag": "VIP", "count": 12}]}, most used first."""
    return {"tags": lead_tags.tags_in_use(get_supabase(), ctx["tenant_id"])}


@router.post("/add")
def add(body: TagChange, ctx: dict = Depends(require_leads_manage)):
    return lead_tags.add_tags(get_supabase(), ctx["tenant_id"], body.lead_ids, body.tags, user_id=ctx.get("user_id"))


@router.post("/remove")
def remove(body: TagChange, ctx: dict = Depends(require_leads_manage)):
    return lead_tags.remove_tags(get_supabase(), ctx["tenant_id"], body.lead_ids, body.tags)
