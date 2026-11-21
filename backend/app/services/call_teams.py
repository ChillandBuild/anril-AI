"""Call IQ teams (v9.2 Batch C, migration 307): read and change teams, plus the small helpers every
scoped route shares.

Teams are optional. A client with no teams, or a database where migration 307 has not been applied,
behaves exactly as before: nobody is limited, the teams list is empty, and changing teams answers
"not switched on yet" (503) instead of crashing.

Who is limited: only a Team leader (role slug team_leader). `caller_scope()` is the one place routes
ask "which callers may this person see?": None means everyone (owner and every other role, unchanged),
a set means only those callers.id values.
"""
import logging
from uuid import UUID

from fastapi import Depends, HTTPException

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_and_role

from app.services.call_team_scope import TEAM_LEADER_SLUG, is_team_leader, scoped_caller_ids

logger = logging.getLogger(__name__)

_SCHEMA_MARKERS = ("call_teams", "call_team_leaders", "team_id")
_NOT_READY = "Teams are not switched on yet. Ask support to turn them on."


def teams_schema_missing(exc: Exception) -> bool:
    """True when a database error means migration 307's tables/columns are not there."""
    msg = str(exc).lower()
    missing = any(m in msg for m in ("pgrst", "schema cache", "does not exist", "could not find", "42703", "42p01"))
    return missing and any(m in msg for m in _SCHEMA_MARKERS)


# ── Who may see what ─────────────────────────────────────────────────────────


def caller_scope(db, ctx: dict) -> set[str] | None:
    """None = sees everyone. A set = only these callers.id values (a Team leader: their team + themself).

    Fails closed for leaders: if the role read blips, a person whose cached role is Team leader is still
    treated as a leader (their own caller only), never as "sees everyone"."""
    if ctx.get("role") == "owner":
        return None
    scope = scoped_caller_ids(db, ctx)
    if scope is None and ctx.get("role_slug") == TEAM_LEADER_SLUG and not is_team_leader(db, ctx):
        # The fresh read said "not a leader" but the cached role says leader. Only a role change in the
        # last minute (cache is cleared on role edits) or a failed read gets here: stay restricted.
        return {str(ctx["caller_id"])} if ctx.get("caller_id") else set()
    return scope


def assert_caller_in_scope(db, ctx: dict, caller_id: str, scope: set[str] | None = None) -> None:
    """403 when a Team leader asks about a telecaller outside their team. No-op for everyone else."""
    scope = caller_scope(db, ctx) if scope is None else scope
    if scope is not None and str(caller_id) not in scope:
        raise HTTPException(status_code=403, detail="That person is not in your team.")


def is_leader_ctx(db, ctx: dict) -> bool:
    return caller_scope(db, ctx) is not None


def can_manage_teams(db, ctx: dict) -> bool:
    """Owner, or roles.manage, or team.manage as long as the person is not a Team leader."""
    if ctx.get("role") == "owner":
        return True
    perms = set(ctx.get("permissions") or [])
    if "roles.manage" in perms:
        return True
    return "team.manage" in perms and not is_leader_ctx(db, ctx)


# ── Reading ──────────────────────────────────────────────────────────────────


def _owner_user_id(db, tenant_id: str) -> str | None:
    rows = db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner").limit(1).execute().data or []
    return rows[0].get("user_id") if rows else None


def team_by_caller(db, tenant_id: str) -> dict[str, dict]:
    """{caller_id: {"team_id", "team_name"}} for callers that are in a team. {} if teams are not set up."""
    try:
        callers = db.table("callers").select("id,team_id").eq("tenant_id", tenant_id).execute().data or []
        in_team = {str(c["id"]): str(c["team_id"]) for c in callers if c.get("team_id")}
        if not in_team:
            return {}
        teams = db.table("call_teams").select("id,name").eq("tenant_id", tenant_id).execute().data or []
        names = {str(t["id"]): t.get("name") for t in teams}
        return {cid: {"team_id": tid, "team_name": names.get(tid)} for cid, tid in in_team.items() if tid in names}
    except Exception as e:
        if not teams_schema_missing(e):
            logger.warning("call_teams: could not read teams for tenant %s: %s", tenant_id, e)
        return {}


def teams_led_by_user(db, tenant_id: str) -> dict[str, list[dict]]:
    """{user_id: [{"id","name"}]} for every leader. {} if teams are not set up."""
    try:
        leaders = db.table("call_team_leaders").select("team_id,user_id").eq("tenant_id", tenant_id).execute().data or []
        if not leaders:
            return {}
        teams = db.table("call_teams").select("id,name").eq("tenant_id", tenant_id).execute().data or []
        names = {str(t["id"]): t.get("name") for t in teams}
        out: dict[str, list[dict]] = {}
        for row in leaders:
            tid = str(row["team_id"])
            if tid in names:
                out.setdefault(str(row["user_id"]), []).append({"id": tid, "name": names[tid]})
        return out
    except Exception as e:
        if not teams_schema_missing(e):
            logger.warning("call_teams: could not read leaders for tenant %s: %s", tenant_id, e)
        return {}


def attach_team(callers: list[dict], teams: dict[str, dict]) -> None:
    """Adds team_id / team_name to each caller dict in place (None when the caller is in no team)."""
    for c in callers:
        info = teams.get(str(c.get("id"))) or {}
        c["team_id"] = info.get("team_id")
        c["team_name"] = info.get("team_name")


def teams_overview(db, tenant_id: str, only_team_ids: set[str] | None = None) -> dict:
    """{"ready": bool, "teams": [...], "unassigned": [...]} (members and leaders spelled out by name).

    only_team_ids limits the answer to those teams (a Team leader sees only the teams they lead) and
    leaves out the "unassigned" list, which would show who else works for the client."""
    try:
        teams = db.table("call_teams").select("id,name,created_at").eq("tenant_id", tenant_id).order("name").execute().data or []
        leaders = db.table("call_team_leaders").select("team_id,user_id").eq("tenant_id", tenant_id).execute().data or []
        callers = db.table("callers").select("id,name,user_id,team_id,active").eq("tenant_id", tenant_id).eq("active", True).order("name").execute().data or []
    except Exception as e:
        if teams_schema_missing(e):
            return {"ready": False, "teams": [], "unassigned": []}
        raise
    owner_uid = _owner_user_id(db, tenant_id)
    callers = [c for c in callers if not owner_uid or c.get("user_id") != owner_uid]
    members_rows = db.table("tenant_users").select("user_id,full_name").eq("tenant_id", tenant_id).execute().data or []
    names_by_user = {str(m["user_id"]): m.get("full_name") for m in members_rows}
    caller_by_user = {str(c["user_id"]): c for c in callers if c.get("user_id")}

    def person_name(user_id: str) -> str:
        return names_by_user.get(user_id) or (caller_by_user.get(user_id) or {}).get("name") or "Team leader"

    out = []
    for t in teams:
        tid = str(t["id"])
        if only_team_ids is not None and tid not in only_team_ids:
            continue
        out.append({
            "id": tid,
            "name": t.get("name"),
            "members": [{"caller_id": str(c["id"]), "name": c.get("name"), "user_id": c.get("user_id")}
                        for c in callers if str(c.get("team_id") or "") == tid],
            "leaders": [{"user_id": str(r["user_id"]), "name": person_name(str(r["user_id"]))}
                        for r in leaders if str(r["team_id"]) == tid],
        })
    unassigned = []
    if only_team_ids is None:
        unassigned = [{"caller_id": str(c["id"]), "name": c.get("name"), "user_id": c.get("user_id")}
                      for c in callers if not c.get("team_id")]
    return {"ready": True, "teams": out, "unassigned": unassigned}


# ── Changing ─────────────────────────────────────────────────────────────────


def _uuid(value, what: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail=f"{what} not found")


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise HTTPException(status_code=400, detail="Give the team a name.")
    if len(name) > 60:
        raise HTTPException(status_code=400, detail="Team names can be up to 60 letters.")
    return name


def _db_write(fn):
    """Runs a write; a missing migration becomes a plain 503, a duplicate name a 409."""
    try:
        return fn()
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e).lower()
        if teams_schema_missing(e):
            raise HTTPException(status_code=503, detail=_NOT_READY)
        if "23505" in msg or "duplicate" in msg or "unique" in msg:
            raise HTTPException(status_code=409, detail="You already have a team with that name.")
        raise


def get_team(db, tenant_id: str, team_id: str) -> dict:
    team_id = _uuid(team_id, "Team")
    rows = _db_write(lambda: db.table("call_teams").select("id,name").eq("tenant_id", tenant_id).eq("id", team_id).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(status_code=404, detail="Team not found")
    return rows[0]


def _name_taken(db, tenant_id: str, name: str, except_id: str | None = None) -> bool:
    rows = db.table("call_teams").select("id,name").eq("tenant_id", tenant_id).execute().data or []
    return any(str(r["id"]) != except_id and (r.get("name") or "").strip().lower() == name.lower() for r in rows)


def create_team(db, tenant_id: str, name: str) -> dict:
    name = _clean_name(name)

    def run():
        if _name_taken(db, tenant_id, name):
            raise HTTPException(status_code=409, detail="You already have a team with that name.")
        return db.table("call_teams").insert({"tenant_id": tenant_id, "name": name}).execute().data[0]
    return _db_write(run)


def rename_team(db, tenant_id: str, team_id: str, name: str) -> dict:
    name = _clean_name(name)
    team = get_team(db, tenant_id, team_id)

    def run():
        if _name_taken(db, tenant_id, name, except_id=str(team["id"])):
            raise HTTPException(status_code=409, detail="You already have a team with that name.")
        return db.table("call_teams").update({"name": name}).eq("id", team["id"]).eq("tenant_id", tenant_id).execute().data[0]
    return _db_write(run)


def delete_team(db, tenant_id: str, team_id: str) -> dict:
    """Members fall back to no team (callers.team_id is set to NULL); leaders' rows go with the team."""
    team = get_team(db, tenant_id, team_id)

    def run():
        db.table("callers").update({"team_id": None}).eq("tenant_id", tenant_id).eq("team_id", team["id"]).execute()
        db.table("call_team_leaders").delete().eq("tenant_id", tenant_id).eq("team_id", team["id"]).execute()
        db.table("call_teams").delete().eq("tenant_id", tenant_id).eq("id", team["id"]).execute()
        return team
    return _db_write(run)


def set_members(db, tenant_id: str, team_id: str, caller_ids: list[str]) -> list[str]:
    """Makes exactly these telecallers the team's members. A telecaller is in one team at a time, so
    ticking someone here moves them out of their old team. Ids from another client -> 404."""
    team = get_team(db, tenant_id, team_id)
    wanted = list(dict.fromkeys(_uuid(c, "Telecaller") for c in (caller_ids or [])))

    def run():
        found = []
        if wanted:
            found = (db.table("callers").select("id,user_id,active").eq("tenant_id", tenant_id).in_("id", wanted).execute().data or [])
        if {str(c["id"]) for c in found} != set(wanted):
            raise HTTPException(status_code=404, detail="Telecaller not found")
        owner_uid = _owner_user_id(db, tenant_id)
        if owner_uid and any(c.get("user_id") == owner_uid for c in found):
            raise HTTPException(status_code=400, detail="The owner does not belong to a team.")
        db.table("callers").update({"team_id": None}).eq("tenant_id", tenant_id).eq("team_id", team["id"]).execute()
        if wanted:
            db.table("callers").update({"team_id": team["id"]}).eq("tenant_id", tenant_id).in_("id", wanted).execute()
        return wanted
    return _db_write(run)


def set_leaders(db, tenant_id: str, team_id: str, user_ids: list[str]) -> dict:
    """Makes exactly these people the team's leaders. Returns {"user_ids", "promoted", "kept_role"}.

    A leader whose role is Telecaller is moved to the built-in Team leader role (that is what limits
    them to their team). A person with a custom role keeps it: they are listed as leader but only the
    Team leader role limits what they see, so the caller shows a note. The owner cannot be a leader
    (they already see every team). Ids from another client -> 404."""
    from app.dependencies.tenant import invalidate_tenant_cache
    from app.services.rbac import ensure_team_leader_role, get_user_role

    team = get_team(db, tenant_id, team_id)
    wanted = list(dict.fromkeys(_uuid(u, "Person") for u in (user_ids or [])))

    def run():
        members = []
        if wanted:
            members = db.table("tenant_users").select("user_id,role,role_id").eq("tenant_id", tenant_id).in_("user_id", wanted).execute().data or []
        if {str(m["user_id"]) for m in members} != set(wanted):
            raise HTTPException(status_code=404, detail="Person not found")
        if any(m.get("role") == "owner" for m in members):
            raise HTTPException(status_code=400, detail="The owner already sees every team.")

        promoted: list[str] = []
        kept_role: list[str] = []
        leader_role = None
        for m in members:
            role = get_user_role(db, tenant_id, m.get("role_id"))
            slug = (role or {}).get("slug")
            if slug == TEAM_LEADER_SLUG:
                continue
            if slug == "telecaller":
                leader_role = leader_role or ensure_team_leader_role(db, tenant_id)
                db.table("tenant_users").update({"role_id": leader_role["id"]}).eq("tenant_id", tenant_id).eq("user_id", m["user_id"]).execute()
                invalidate_tenant_cache(str(m["user_id"]))
                promoted.append(str(m["user_id"]))
            else:
                kept_role.append(str(m["user_id"]))

        db.table("call_team_leaders").delete().eq("tenant_id", tenant_id).eq("team_id", team["id"]).execute()
        if wanted:
            db.table("call_team_leaders").insert(
                [{"team_id": team["id"], "tenant_id": tenant_id, "user_id": u} for u in wanted]
            ).execute()
        for u in wanted:
            invalidate_tenant_cache(u)
        return {"user_ids": wanted, "promoted": promoted, "kept_role": kept_role}
    return _db_write(run)


LEADER_KEPT_ROLE_NOTE = (
    "They keep their role. Give them the Team leader role in Team & roles to limit them to this team."
)


def forget_leader(db, tenant_id: str, user_id: str) -> None:
    """A removed person stops leading any team. Never raises."""
    try:
        db.table("call_team_leaders").delete().eq("tenant_id", tenant_id).eq("user_id", user_id).execute()
    except Exception as e:
        if not teams_schema_missing(e):
            logger.warning("call_teams: could not clear leader rows for %s: %s", user_id, e)


# ── Dependencies for owner-only reads a Team leader may also open ────────────


def owner_or_team_leader(ctx: dict = Depends(get_tenant_and_role)) -> dict:
    """Owner passes (as before). A Team leader with team.view passes too; their handler must then limit
    itself to caller_scope(). Everyone else gets the same 403 as the old owner-only gate."""
    if ctx.get("role") == "owner":
        return ctx
    if "team.view" in (ctx.get("permissions") or []) or "team.manage" in (ctx.get("permissions") or []):
        if caller_scope(get_supabase(), ctx) is not None:
            return ctx
    raise HTTPException(status_code=403, detail="Organization owner privileges required.")


def assign_scope(db, ctx: dict) -> set[str] | None:
    """Who may move leads between telecallers. Owner: anyone (None = no limit, as today).
    A Team leader with team.manage: only within their own team (a set). Everyone else: 403 as before."""
    if ctx.get("role") == "owner":
        return None
    scope = caller_scope(db, ctx)
    if scope is not None and "team.manage" in (ctx.get("permissions") or []):
        return scope
    raise HTTPException(status_code=403, detail="Owner only")


def assert_can_move_lead(scope: set[str] | None, from_caller_id, to_caller_id) -> None:
    """A Team leader may only move a lead that one of their team holds to another of their team."""
    if scope is None:
        return
    if not to_caller_id or str(to_caller_id) not in scope:
        raise HTTPException(status_code=403, detail="You can only give leads to people in your team.")
    if not from_caller_id or str(from_caller_id) not in scope:
        raise HTTPException(status_code=403, detail="That lead is not held by your team.")
