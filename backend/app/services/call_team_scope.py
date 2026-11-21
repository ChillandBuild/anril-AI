"""Call IQ teams: what a Team leader may see (v9.2 Batch C, migration 307).

A Team leader (tenant_roles.slug = 'team_leader') sees ONLY the telecallers of the team(s) they
lead (call_team_leaders) plus themself. Everyone else is unchanged: the owner and every other
role keep seeing all telecallers, exactly as before teams existed.

    scoped_caller_ids(db, ctx) -> None        sees everyone (no filter)
                               -> set[str]    only these callers.id values (may be empty)

Every Call IQ list that a Team leader can open filters by this: Team performance, Leads to call
(uploads, scheduled calls, who got which lead) and Call reviews. A failed read returns an EMPTY
set for a Team leader (fail closed: a leader never sees other teams because of a DB blip).
"""
import logging

logger = logging.getLogger(__name__)

TEAM_LEADER_SLUG = "team_leader"


def is_team_leader(db, ctx: dict) -> bool:
    if ctx.get("role") == "owner":
        return False
    try:
        rows = (
            db.table("tenant_users").select("role_id").eq("tenant_id", ctx["tenant_id"])
            .eq("user_id", ctx["user_id"]).limit(1).execute().data or []
        )
        role_id = rows[0].get("role_id") if rows else None
        if not role_id:
            return False
        role = (
            db.table("tenant_roles").select("slug").eq("id", role_id).eq("tenant_id", ctx["tenant_id"])
            .limit(1).execute().data or []
        )
        return bool(role and role[0].get("slug") == TEAM_LEADER_SLUG)
    except Exception as e:
        logger.warning("call_team_scope: could not read role for user %s (%s)", ctx.get("user_id"), e)
        return False


def led_team_ids(db, tenant_id: str, user_id: str) -> set[str]:
    rows = (
        db.table("call_team_leaders").select("team_id").eq("tenant_id", tenant_id)
        .eq("user_id", user_id).execute().data or []
    )
    return {str(r["team_id"]) for r in rows if r.get("team_id")}


def scoped_caller_ids(db, ctx: dict) -> set[str] | None:
    if not is_team_leader(db, ctx):
        return None
    tenant_id = ctx["tenant_id"]
    try:
        team_ids = led_team_ids(db, tenant_id, ctx["user_id"])
        ids: set[str] = set()
        if team_ids:
            rows = (
                db.table("callers").select("id").eq("tenant_id", tenant_id)
                .in_("team_id", list(team_ids)).execute().data or []
            )
            ids = {str(r["id"]) for r in rows}
        if ctx.get("caller_id"):
            ids.add(str(ctx["caller_id"]))
        return ids
    except Exception as e:
        logger.warning("call_team_scope: could not read team for leader %s (%s); showing nothing", ctx.get("user_id"), e)
        return set()


def leader_user_ids_for_caller(db, tenant_id: str, caller_id: str) -> list[str]:
    """The auth user ids of the leaders of this telecaller's team ([] when no team or no leader)."""
    rows = (
        db.table("callers").select("team_id").eq("tenant_id", tenant_id).eq("id", caller_id)
        .limit(1).execute().data or []
    )
    team_id = rows[0].get("team_id") if rows else None
    if not team_id:
        return []
    leaders = (
        db.table("call_team_leaders").select("user_id").eq("tenant_id", tenant_id)
        .eq("team_id", team_id).execute().data or []
    )
    return [str(r["user_id"]) for r in leaders if r.get("user_id")]
