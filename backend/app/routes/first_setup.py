"""v9.2 #27 The 6-step first setup. Built by agent L.

Each step saves through the endpoint that already owns that setting (business details, the
catalogue, notifications, connections, the AI switch). This route only remembers how far the
owner got, so "Finish later" picks up in the same place and Today can say "Last step: connect
your accounts" when that step was skipped. The progress sits in app_settings as one small JSON value."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()
require_settings_manage = require_permission("settings.manage")

SETTING_KEY = "first_setup_progress"
# In the order the owner sees them.
STEPS = ("business", "items", "hours", "alerts", "connect", "ai")


class ProgressIn(BaseModel):
    step: str = Field("business", max_length=20)
    done_steps: list[str] = Field(default_factory=list, max_length=len(STEPS))


def clean_progress(step: object, done_steps: object) -> dict:
    """Only known step names survive, each once, in menu order. An unknown current step falls back to the first."""
    done_set = {s for s in (done_steps if isinstance(done_steps, list) else []) if isinstance(s, str)}
    return {
        "step": step if isinstance(step, str) and step in STEPS else STEPS[0],
        "done_steps": [s for s in STEPS if s in done_set],
    }


def read_progress(tenant_id: str, db=None) -> dict:
    """Never raises: a missing row, bad JSON or a failed read all look like "not started"."""
    try:
        row = (
            (db or get_supabase()).table("app_settings").select("value")
            .eq("tenant_id", tenant_id).eq("key", SETTING_KEY).maybe_single().execute()
        )
        if row and row.data and row.data.get("value"):
            stored = json.loads(row.data["value"])
            if isinstance(stored, dict):
                return clean_progress(stored.get("step"), stored.get("done_steps"))
    except Exception as e:  # noqa: BLE001
        logger.warning("first_setup: could not read progress for %s (%s)", tenant_id, type(e).__name__)
    return clean_progress(None, [])


@router.get("/progress")
def get_progress(ctx: dict = Depends(require_settings_manage)):
    return read_progress(ctx["tenant_id"])


@router.put("/progress")
def put_progress(payload: ProgressIn, ctx: dict = Depends(require_settings_manage)):
    progress = clean_progress(payload.step, payload.done_steps)
    try:
        get_supabase().table("app_settings").upsert(
            {"tenant_id": ctx["tenant_id"], "key": SETTING_KEY, "value": json.dumps(progress), "is_secret": False},
            on_conflict="tenant_id,key",
        ).execute()
    except Exception as e:  # noqa: BLE001
        logger.error("first_setup: save failed for %s (%s)", ctx["tenant_id"], type(e).__name__)
        raise HTTPException(status_code=500, detail="Couldn't save your progress. Please try again.")
    return progress
