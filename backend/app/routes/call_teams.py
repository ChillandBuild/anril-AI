"""Call IQ teams (v9.2 Batch C): /api/v1/call-teams.

Reading needs team.view. Changing needs "manage teams": the owner, roles.manage, or team.manage as
long as the person is not a Team leader (a leader can see their own team but never changes teams).
Everything is scoped to the caller's own client; an id from another client answers 404."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services import call_teams as svc
from app.services.audit_log import record_audit_event
from app.services.call_team_scope import led_team_ids

logger = logging.getLogger(__name__)
router = APIRouter()
require_team_view = require_permission("team.view")


class TeamNamePayload(BaseModel):
    name: str = Field(..., max_length=200)


class MembersPayload(BaseModel):
    caller_ids: list[str] = Field(default_factory=list, max_length=500)


class LeadersPayload(BaseModel):
    user_ids: list[str] = Field(default_factory=list, max_length=100)


def _require_manage(db, ctx: dict) -> None:
    if not svc.can_manage_teams(db, ctx):
        raise HTTPException(status_code=403, detail="Only the owner or an admin can change teams.")


def _audit(db, ctx: dict, action: str, team_id: str | None, metadata: dict) -> None:
    record_audit_event(
        db, tenant_id=ctx["tenant_id"], actor_user_id=ctx["user_id"], actor_role=ctx.get("role_slug") or ctx.get("role"),
        action=action, target_type="call_team", target_id=team_id, metadata=metadata,
    )


@router.get("")
def list_teams(ctx: dict = Depends(require_team_view)):
    db = get_supabase()
    scope = svc.caller_scope(db, ctx)
    can_manage = svc.can_manage_teams(db, ctx)
    only = None
    if scope is not None:
        # A Team leader sees only the teams they lead. Fail closed on a read error.
        try:
            only = led_team_ids(db, ctx["tenant_id"], ctx["user_id"])
        except Exception as e:
            if not svc.teams_schema_missing(e):
                logger.warning("call_teams: could not read led teams: %s", e)
            only = set()
    overview = svc.teams_overview(db, ctx["tenant_id"], only_team_ids=only)
    return {
        "data": overview["teams"],
        "unteamed": overview["unassigned"] if can_manage else [],
        "can_manage": can_manage,
        "teams_ready": overview["ready"],
    }


@router.post("", status_code=201)
def create_team(payload: TeamNamePayload, ctx: dict = Depends(require_team_view)):
    db = get_supabase()
    _require_manage(db, ctx)
    team = svc.create_team(db, ctx["tenant_id"], payload.name)
    _audit(db, ctx, "team.call_team_created", str(team["id"]), {"name": team.get("name")})
    return {"data": {"id": str(team["id"]), "name": team.get("name"), "members": [], "leaders": []}}


@router.patch("/{team_id}")
def rename_team(team_id: str, payload: TeamNamePayload, ctx: dict = Depends(require_team_view)):
    db = get_supabase()
    _require_manage(db, ctx)
    old = svc.get_team(db, ctx["tenant_id"], team_id)
    team = svc.rename_team(db, ctx["tenant_id"], team_id, payload.name)
    _audit(db, ctx, "team.call_team_renamed", str(team["id"]), {"from": old.get("name"), "to": team.get("name")})
    return {"data": {"id": str(team["id"]), "name": team.get("name")}}


@router.delete("/{team_id}")
def delete_team(team_id: str, ctx: dict = Depends(require_team_view)):
    db = get_supabase()
    _require_manage(db, ctx)
    team = svc.delete_team(db, ctx["tenant_id"], team_id)
    _audit(db, ctx, "team.call_team_deleted", str(team["id"]), {"name": team.get("name")})
    return {"ok": True}


@router.put("/{team_id}/members")
def put_members(team_id: str, payload: MembersPayload, ctx: dict = Depends(require_team_view)):
    db = get_supabase()
    _require_manage(db, ctx)
    ids = svc.set_members(db, ctx["tenant_id"], team_id, payload.caller_ids)
    _audit(db, ctx, "team.call_team_members", team_id, {"caller_ids": ids, "count": len(ids)})
    return {"ok": True, "caller_ids": ids}


@router.put("/{team_id}/leaders")
def put_leaders(team_id: str, payload: LeadersPayload, ctx: dict = Depends(require_team_view)):
    db = get_supabase()
    _require_manage(db, ctx)
    res = svc.set_leaders(db, ctx["tenant_id"], team_id, payload.user_ids)
    _audit(db, ctx, "team.call_team_leaders", team_id, {
        "user_ids": res["user_ids"], "made_team_leader_role": res["promoted"], "kept_role": res["kept_role"],
    })
    note = svc.LEADER_KEPT_ROLE_NOTE if res["kept_role"] else None
    return {"ok": True, "user_ids": res["user_ids"], "promoted": res["promoted"], "note": note}
