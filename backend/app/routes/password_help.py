"""v9.2 #27 Forgot password = a request to the Anril team (PUBLIC, no login). Built by agent L."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.dependencies.system_admin import get_system_admin
from app.routes.auto_messages import _client_ip
from app.services import password_help as svc

router = APIRouter()


class PasswordHelpIn(BaseModel):
    identifier: str = Field("", max_length=svc.MAX_IDENTIFIER)
    business_name: str = Field("", max_length=svc.MAX_BUSINESS)
    note: str = Field("", max_length=svc.MAX_NOTE)


@router.post("/request")
def request_help(payload: PasswordHelpIn, request: Request):
    """Public. Same reply whatever the input, so it never shows whether an account exists."""
    if not payload.identifier.strip():
        raise HTTPException(status_code=422, detail="Type your login email or phone number")
    svc.submit_request(payload.identifier, payload.business_name, payload.note, _client_ip(request))
    return {"message": svc.REPLY}


# Anril team only (system admins): the list to work through, and "done" once they have called back.
@router.get("/requests")
def list_requests(status: str = "open", _admin: dict = Depends(get_system_admin)):
    if status not in ("open", "done"):
        raise HTTPException(status_code=422, detail="status must be open or done")
    return {"data": svc.list_requests(status)}


@router.post("/requests/{request_id}/done")
def mark_done(request_id: str, _admin: dict = Depends(get_system_admin)):
    try:
        UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Request not found")
    if not svc.mark_done(request_id):
        raise HTTPException(status_code=404, detail="Request not found")
    return {"done": True}
