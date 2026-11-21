"""Home (Today): the first screen's boxes and lists, and each person's own Edit Today layout.

The numbers live in services/home_today.py. The layout is one row per (client, person) in
public.home_layouts (migration 306). That table may not be applied yet: a missing table reads
as "no saved layout" and a save answers 503, never a crash.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services import home_today

logger = logging.getLogger(__name__)
router = APIRouter()
require_dashboard_view = require_permission("dashboard.view")

NOT_READY = "Home layouts not ready"
_NO_ROW = {"boxes": None, "lists": None, "is_custom": False}


class LayoutIn(BaseModel):
    boxes: list[str] = Field(default_factory=list)
    lists: dict[str, bool] = Field(default_factory=dict)

    @field_validator("boxes")
    @classmethod
    def _boxes(cls, v: list[str]) -> list[str]:
        if len(v) > home_today.MAX_BOXES:
            raise ValueError(f"At most {home_today.MAX_BOXES} boxes")
        if len(set(v)) != len(v):
            raise ValueError("Each box can be on Today only once")
        unknown = [k for k in v if k not in home_today.BOX_KEYS]
        if unknown:
            raise ValueError(f"Unknown box: {', '.join(unknown)}")
        return v

    @field_validator("lists")
    @classmethod
    def _lists(cls, v: dict[str, bool]) -> dict[str, bool]:
        unknown = [k for k in v if k not in home_today.LIST_KEYS]
        if unknown:
            raise ValueError(f"Unknown list: {', '.join(unknown)}")
        return v


def _table_missing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "home_layouts" in msg and any(
        m in msg for m in ("pgrst205", "schema cache", "does not exist", "42p01", "could not find")
    )


def _shape(row: dict | None) -> dict:
    if not row:
        return dict(_NO_ROW)
    boxes = row.get("boxes")
    lists = row.get("lists")
    return {
        "boxes": boxes if isinstance(boxes, list) else [],
        "lists": lists if isinstance(lists, dict) and lists else None,
        "is_custom": True,
    }


@router.get("/today")
def today(ctx: dict = Depends(require_dashboard_view)):
    return home_today.compute_today(get_supabase(), ctx)


@router.get("/layout")
def get_layout(ctx: dict = Depends(require_dashboard_view)):
    try:
        rows = (
            get_supabase().table("home_layouts").select("boxes, lists")
            .eq("tenant_id", ctx["tenant_id"]).eq("user_id", ctx["user_id"]).limit(1).execute().data or []
        )
    except Exception as e:
        # Table missing (migration not applied) or a hiccup: show the suggested set.
        (logger.info if _table_missing(e) else logger.warning)("home layout read failed: %s", e)
        return dict(_NO_ROW)
    return _shape(rows[0] if rows else None)


@router.put("/layout")
def put_layout(body: LayoutIn, ctx: dict = Depends(require_dashboard_view)):
    lists = {k: bool(body.lists.get(k, True)) for k in home_today.LIST_KEYS}
    row = {
        "tenant_id": ctx["tenant_id"], "user_id": ctx["user_id"],
        "boxes": body.boxes, "lists": lists,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        get_supabase().table("home_layouts").upsert(row, on_conflict="tenant_id,user_id").execute()
    except Exception as e:
        logger.warning("home layout save failed: %s", e)
        raise HTTPException(status_code=503, detail=NOT_READY if _table_missing(e) else "Couldn't save right now")
    return _shape(row)


@router.delete("/layout")
def delete_layout(ctx: dict = Depends(require_dashboard_view)):
    try:
        get_supabase().table("home_layouts").delete().eq("tenant_id", ctx["tenant_id"]).eq("user_id", ctx["user_id"]).execute()
    except Exception as e:
        logger.warning("home layout reset failed: %s", e)
        raise HTTPException(status_code=503, detail=NOT_READY if _table_missing(e) else "Couldn't reset right now")
    return dict(_NO_ROW)
