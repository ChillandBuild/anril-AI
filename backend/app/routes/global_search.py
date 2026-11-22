"""GET /api/v1/search?q= — the search box in the top bar. Any signed-in user; each group is cut by
its own permission inside the service (see app/services/global_search.py)."""
from fastapi import APIRouter, Depends, HTTPException

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_and_role
from app.services import global_search as svc

router = APIRouter()


@router.get("")
def global_search(q: str = "", ctx: dict = Depends(get_tenant_and_role)):
    text = (q or "").strip()
    if not svc.MIN_LEN <= len(text) <= svc.MAX_LEN:
        raise HTTPException(status_code=422, detail=f"Type {svc.MIN_LEN} to {svc.MAX_LEN} characters to search")
    return svc.search(get_supabase(), ctx, text)
