"""Shared setup for the Call IQ teams tests: one client (T1) with Team A, Team B, a Team leader of
Team A, an owner, and a second client (T2) that must never be reachable from T1."""
import uuid
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services.rbac import DEFAULT_TELECALLER_PERMISSIONS, DEFAULT_TEAM_LEADER_PERMISSIONS
from fake_supabase import FakeSupabase, _Query


def uid(n: int) -> str:
    return str(uuid.UUID(int=n))


T1, T2 = uid(1), uid(2)
OWNER_U, LEADER_U, TC_U, CUSTOM_U, A1_U, A2_U, B1_U, U1_U, X1_U = (uid(i) for i in range(10, 19))
OC, LC, A1, A2, B1, U1, X1 = (uid(i) for i in range(30, 37))   # callers.id
TA, TB, TX = uid(50), uid(51), uid(52)                          # call_teams.id (TX belongs to T2)
RID_TC, RID_TL, RID_CU = uid(60), uid(61), uid(62)

# every module that builds its own db with get_supabase()
DB_MODULES = [
    "app.routes.call_teams", "app.routes.team", "app.routes.callers", "app.routes.analytics",
    "app.routes.calls", "app.routes.call_review", "app.routes.follow_ups", "app.routes.leads",
    "app.routes.rbac", "app.services.call_teams",
]


def build_db() -> FakeSupabase:
    db = FakeSupabase()
    for tid, role_id, name, slug, perms in (
        (T1, RID_TC, "Telecaller", "telecaller", DEFAULT_TELECALLER_PERMISSIONS),
        (T1, RID_TL, "Team leader", "team_leader", DEFAULT_TEAM_LEADER_PERMISSIONS),
        (T1, RID_CU, "Supervisor", None, ["team.view", "team.manage"]),
    ):
        db.add("tenant_roles", id=role_id, tenant_id=tid, name=name, slug=slug, permissions=perms)
    for user, role, role_id in (
        (OWNER_U, "owner", None), (LEADER_U, "caller", RID_TL), (TC_U, "caller", RID_TC),
        (CUSTOM_U, "caller", RID_CU), (A1_U, "caller", RID_TC), (A2_U, "caller", RID_TC),
        (B1_U, "caller", RID_TC), (U1_U, "caller", RID_TC),
    ):
        db.add("tenant_users", tenant_id=T1, user_id=user, role=role, role_id=role_id, full_name=f"user-{user[-2:]}")
    db.add("tenant_users", tenant_id=T2, user_id=X1_U, role="owner", role_id=None, full_name="other owner")
    db.add("call_teams", id=TA, tenant_id=T1, name="Team A")
    db.add("call_teams", id=TB, tenant_id=T1, name="Team B")
    db.add("call_teams", id=TX, tenant_id=T2, name="Other client team")
    for cid, user, name, team, tenant in (
        (OC, OWNER_U, "Owner Caller", None, T1), (LC, LEADER_U, "Leader Lena", TA, T1),
        (A1, A1_U, "Anitha", TA, T1), (A2, A2_U, "Arun", TA, T1), (B1, B1_U, "Bala", TB, T1),
        (U1, U1_U, "Uma", None, T1), (X1, X1_U, "Xavier", TX, T2),
    ):
        db.add("callers", id=cid, tenant_id=tenant, user_id=user, name=name, phone="+910000000000", active=True, team_id=team)
    db.add("call_team_leaders", team_id=TA, tenant_id=T1, user_id=LEADER_U)
    return db


def ctx_for(user: str, role: str = "caller", slug: str | None = "telecaller", perms=None, caller_id: str | None = None, tenant: str = T1) -> dict:
    return {
        "tenant_id": tenant, "role": role, "user_id": user, "caller_id": caller_id,
        "role_id": None, "role_name": slug, "role_slug": slug, "permissions": list(perms or []),
    }


OWNER_CTX = ctx_for(OWNER_U, "owner", "owner", ["team.view", "team.manage", "analytics.view"])
LEADER_CTX = ctx_for(LEADER_U, "caller", "team_leader", DEFAULT_TEAM_LEADER_PERMISSIONS, caller_id=LC)
# a manager with a CUSTOM role (team.view + team.manage + analytics.view): sees everyone, as today
MANAGER_CTX = ctx_for(CUSTOM_U, "caller", "supervisor", ["team.view", "team.manage", "analytics.view"])
TELECALLER_CTX = ctx_for(A1_U, "caller", "telecaller", DEFAULT_TELECALLER_PERMISSIONS, caller_id=A1)


class Harness:
    """Patches every module's get_supabase to one FakeSupabase and lets a test pick who is logged in."""

    def __init__(self, db: FakeSupabase | None = None):
        self.db = db or build_db()
        self.client = TestClient(app)
        self.stack = ExitStack()

    def __enter__(self):
        for module in DB_MODULES:
            self.stack.enter_context(patch(f"{module}.get_supabase", return_value=self.db))
        for target in ("app.routes.analytics.get_telecalling_config", "app.routes.callers.get_telecalling_config",
                       "app.routes.calls.get_telecalling_config", "app.routes.call_review.get_telecalling_config",
                       "app.routes.team.get_telecalling_config"):
            self.stack.enter_context(patch(target, return_value={"calling_provider": "telecmi"}))
        self.stack.enter_context(patch("app.routes.leads.record_assignment_event"))
        self.stack.enter_context(patch("app.services.notify.notify_user"))
        self.stack.enter_context(patch("app.services.notify.clear_pool_notifications_for_lead"))
        self.stack.enter_context(patch("app.routes.call_teams.record_audit_event"))
        self.stack.enter_context(patch("app.routes.rbac.record_audit_event"))
        self.stack.enter_context(patch("app.routes.rbac._auth_user", return_value={"email": "x@example.com", "full_name": None}))
        # the fake has no .single(); the status-summary route uses it
        self.stack.enter_context(patch.object(_Query, "single", lambda self: self.maybe_single(), create=True))
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
        return self

    def __exit__(self, *exc):
        app.dependency_overrides.clear()
        self.stack.close()

    def as_(self, ctx: dict):
        app.dependency_overrides[get_tenant_and_role] = lambda: ctx
        return self.client
