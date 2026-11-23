"""v9.2 #23 Is a WhatsApp number disconnected? Feeds the red banner across the dashboard.

Same state the "number disconnected" alert uses: phone_numbers.meta_status, which Meta reports and
number_sync.py keeps up to date (DISCONNECTED_STATUSES). Any signed-in team member may ask (the banner shows
for everyone); only the name Meta approved for the number is returned, never its phone number."""
import logging

from fastapi import APIRouter, Depends

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id
from app.services.number_sync import DISCONNECTED_STATUSES

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/whatsapp")
def whatsapp_connection(tenant_id: str = Depends(get_tenant_id)):
    """{disconnected: bool, numbers: [{id, name}]}. A failed read says "not disconnected": a banner that cries
    wolf on a database blip is worse than one that shows up a minute later."""
    try:
        rows = (get_supabase().table("phone_numbers").select("id,display_name,status,meta_status")
                .eq("tenant_id", tenant_id).in_("meta_status", sorted(DISCONNECTED_STATUSES)).limit(20).execute().data) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("connection-status: could not read numbers for %s (%s)", tenant_id, type(e).__name__)
        return {"disconnected": False, "numbers": []}
    rows = [r for r in rows if r.get("status") != "archived"]
    return {
        "disconnected": bool(rows),
        "numbers": [{"id": r["id"], "name": r.get("display_name") or "Your WhatsApp number"} for r in rows],
    }
